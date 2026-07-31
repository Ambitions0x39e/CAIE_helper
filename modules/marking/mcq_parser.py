"""Parse CIE MCQ mark schemes and detect student answers from annotated QP PDFs.

Two responsibilities:
1. Mark-scheme parsing: PyMuPDF block extraction reads the answer table directly —
   no vision model needed.
2. Student-answer detection: renders the annotated QP page-by-page, sends each
   page (or stitched pair for cross-page questions) to a VL model, and collects
   {question_number: letter} results.
"""
from __future__ import annotations

import base64
import io
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pdfminer.high_level import extract_text

from core.settings import GraderConfig
from modules.marking.ms_parser import PaperConfig, QuestionConfig
from modules.marking.renderer import page_count, to_pdf_bytes

if TYPE_CHECKING:
    from modules.marking.renderer import NativeRenderer

_ANSWER_LETTERS = frozenset("ABCD")

# ── VL prompt ──────────────────────────────────────────────────────────────

_MCQ_DETECTION_PROMPT = """\
This is a page (or pages) from a student's annotated CIE A-Level MCQ answer paper.
The student has marked their chosen answer for each question.
Marking styles vary: circling the letter, circling the option text, writing the
letter beside the question, ticking, crossing, or underlining.

For every question number visible, identify which option the student selected
(A, B, C, or D).

Return ONLY valid JSON — no markdown, no explanation:
{"<question_number>": "<letter>", ...}

Example: {"3": "C", "4": "A", "5": "B"}

Omit any question where you cannot clearly determine the selection."""


# ── Helpers ────────────────────────────────────────────────────────────────

_FILENAME_RE = re.compile(r"(\d{4})_([a-z])(\d{2})_(?:ms|qp)_(\d+)", re.IGNORECASE)


def _parse_paper_filename(stem: str) -> tuple[str, str, str, str] | None:
    """Parse a CIE paper filename stem into (subject, season_letter, year, component).

    Expected format: "<subject>_<season><year>_(ms|qp)_<component>", e.g.
    "9702_s25_qp_11". Returns None if the stem doesn't match.
    """
    m = _FILENAME_RE.match(stem)
    if not m:
        return None
    subject, season_letter, year, component = m.groups()
    return subject, season_letter, year, component


def _extract_paper_id(pdf_path: Path) -> str:
    """Derive a human-readable paper_id from the PDF filename stem."""
    parsed = _parse_paper_filename(pdf_path.stem)  # e.g. "9702_s25_ms_11"
    if parsed is None:
        return pdf_path.stem
    syllabus, season_letter, year, variant = parsed
    session_map = {"s": "M/J", "w": "O/N", "m": "F/M"}
    session = session_map.get(season_letter.lower(), season_letter.upper())
    return f"{syllabus}/{variant}/{session}/{year}"


def _call_vl(
    grader_config: GraderConfig,
    images: list[bytes],
) -> dict[str, str]:
    """Send page image(s) to VL; return {question_num_str: letter} dict."""
    from openai import OpenAI

    content: list[dict[str, object]] = []
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    content.append({"type": "text", "text": _MCQ_DETECTION_PROMPT})

    client = OpenAI(
        api_key=grader_config.api_key.get_secret_value(),
        base_url=grader_config.base_url,
    )
    response = client.chat.completions.create(
        model=grader_config.model,
        messages=[{"role": "user", "content": content}],  # type: ignore[list-item, misc]
        temperature=0.0,
    )
    raw = str(response.choices[0].message.content).strip()

    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        return {
            k.strip(): v.strip().upper()
            for k, v in data.items()
            if isinstance(v, str) and v.strip().upper() in _ANSWER_LETTERS
        }
    except (json.JSONDecodeError, AttributeError):
        return {}


def _resolve_skip_pages(source_stem: str) -> set[int]:
    """Resolve QP skip-pages from paper_page_config.json using a filename stem.

    Falls back to the JSON's own "default" entry when the stem doesn't match
    the expected "<subject>_<season><year>_qp_<component>" pattern.
    """
    from core.config_store import get_paper_page_config

    parsed = _parse_paper_filename(source_stem)
    subject_id, component = (parsed[0], parsed[3]) if parsed else ("", "")
    return get_paper_page_config(subject_id, component).qp_skip_pages


def _build_page_batches(
    n_pages: int,
    skip_pages: set[int],
) -> list[list[int]]:
    """Return one batch per non-skipped page.

    MCQ questions are small self-contained boxes; VL detects multiple answers
    from one page image, so page-level batching is both sufficient and simpler
    than question-level segmentation.
    """
    return [[i] for i in range(n_pages) if i not in skip_pages]


# ── Public: mark scheme parsing ────────────────────────────────────────────

def parse_mcq_mark_scheme(pdf_path: str | Path) -> PaperConfig:
    """Parse an MCQ mark scheme PDF and return a ``PaperConfig``.

    Uses PyMuPDF block text extraction to read the answer table.
    Each question maps to a ``QuestionConfig`` with ``max_marks=1``
    and ``mark_scheme`` set to the correct answer letter (A/B/C/D).

    Raises:
        ValueError: If no answers could be extracted from the PDF.
    """
    path = Path(pdf_path)
    questions: dict[str, QuestionConfig] = {}

    # pdfminer.six text extraction (pure Python, iOS-safe — no pdfplumber).
    text = extract_text(io.BytesIO(to_pdf_bytes(path))) or ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    i = 0
    while i < len(lines) - 1:
        if (
            re.fullmatch(r"\d+", lines[i])
            and lines[i + 1] in _ANSWER_LETTERS
        ):
            qid = f"Q{lines[i]}"
            questions[qid] = QuestionConfig(
                max_marks=1, mark_scheme=lines[i + 1]
            )
            i += 2
        else:
            i += 1

    if not questions:
        raise ValueError(
            f"No MCQ answers found in {path.name}. "
            "Ensure this is a CIE MCQ mark scheme PDF."
        )

    sorted_questions = dict(
        sorted(questions.items(), key=lambda kv: int(kv[0][1:]))
    )
    return PaperConfig(
        paper_id=_extract_paper_id(path),
        total_marks=len(sorted_questions),
        questions=sorted_questions,
    )


# ── Public: student answer detection ───────────────────────────────────────

def detect_student_answers(
    qp_pdf_path: str | Path,
    answer_key: PaperConfig,
    grader_config: GraderConfig,
    renderer: NativeRenderer,
    dpi: int = 200,
    on_progress: Callable[[int, int], None] | None = None,
    source_filename: str | Path | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Detect the student's selected answers from an annotated MCQ QP PDF.

    Renders the QP page-by-page (grouping cross-page questions onto one call),
    sends each image batch to the VL model, and returns detected answers.

    Args:
        qp_pdf_path: Annotated question paper PDF (student's GoodNotes export).
            This is often a temp-file path with a random name, so pass
            ``source_filename`` when the original filename is known.
        answer_key: PaperConfig from ``parse_mcq_mark_scheme``.
        grader_config: VL API credentials.
        dpi: Render resolution.
        on_progress: Callback ``(current_batch, total_batches)``.
        source_filename: Original filename (e.g. "9702_s25_qp_11.pdf") used to
            look up per-subject skip-pages in paper_page_config.json. Falls
            back to ``qp_pdf_path``'s own name when not given.

    Returns:
        ``(detected, undetected)`` where ``detected`` maps question IDs to the
        student's selected letter, and ``undetected`` lists question IDs the VL
        could not find or was uncertain about.
    """
    path = Path(qp_pdf_path)
    stem = Path(source_filename).stem if source_filename is not None else path.stem
    skip = _resolve_skip_pages(stem)
    q_ids = list(answer_key.questions.keys())

    pdf_bytes = to_pdf_bytes(path)
    page_batches = _build_page_batches(page_count(pdf_bytes), skip)

    raw_detected: dict[str, str] = {}  # "1" → "C"
    total = len(page_batches)

    for idx, page_idxs in enumerate(page_batches):
        if on_progress:
            on_progress(idx + 1, total)
        images = renderer.render_pages(pdf_bytes, [p + 1 for p in page_idxs], dpi=dpi)
        batch_result = _call_vl(grader_config, images)
        raw_detected.update(batch_result)

    # Normalise to Q-prefixed IDs and filter to known questions
    detected: dict[str, str] = {}
    for q_num_str, letter in raw_detected.items():
        qid = f"Q{q_num_str}"
        if qid in answer_key.questions:
            detected[qid] = letter

    undetected = [qid for qid in q_ids if qid not in detected]
    return detected, undetected


# ── Public: manual override validation ─────────────────────────────────────

def is_valid_manual_answer(value: str) -> bool:
    """True if ``value`` is a single valid MCQ answer letter (A-D).

    Uses set membership rather than ``value in "ABCD"``, whose substring
    semantics would incorrectly accept an empty string.
    """
    return value in _ANSWER_LETTERS


# ── Public: scoring ────────────────────────────────────────────────────────

def score_mcq_answers(
    paper_config: PaperConfig,
    student_answers: dict[str, str],
) -> tuple[int, int, dict[str, bool]]:
    """Compare student answers against the MCQ answer key.

    Args:
        paper_config: PaperConfig from ``parse_mcq_mark_scheme``.
        student_answers: Maps question ID (e.g. "Q1") to chosen letter.

    Returns:
        ``(score, total, per_question_correct)`` where per_question_correct
        maps each qid to True/False.
    """
    results: dict[str, bool] = {}
    for qid, qcfg in paper_config.questions.items():
        student = student_answers.get(qid, "").strip().upper()
        correct = qcfg.mark_scheme.strip().upper()
        results[qid] = student == correct

    score = sum(1 for v in results.values() if v)
    total = len(paper_config.questions)
    return score, total, results
