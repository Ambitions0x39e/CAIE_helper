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
import json
import re
from collections.abc import Callable
from pathlib import Path

import fitz

from core.settings import GraderConfig
from modules.ms_parser import PaperConfig, QuestionConfig

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

def _extract_paper_id(pdf_path: Path) -> str:
    """Derive a human-readable paper_id from the PDF filename stem."""
    stem = pdf_path.stem  # e.g. "9702_s25_ms_11"
    m = re.match(
        r"(\d{4})_([a-z])(\d{2})_(?:ms|qp)_(\d+)", stem, re.IGNORECASE
    )
    if not m:
        return stem
    syllabus, season_letter, year, variant = m.groups()
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


def _build_page_batches(
    doc: fitz.Document,
    skip_pages: set[int],
) -> list[list[int]]:
    """Return one batch per non-skipped page.

    MCQ questions are small self-contained boxes; VL detects multiple answers
    from one page image, so page-level batching is both sufficient and simpler
    than question-level segmentation.
    """
    return [[i] for i in range(len(doc)) if i not in skip_pages]


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
    doc = fitz.open(str(path))
    questions: dict[str, QuestionConfig] = {}

    try:
        for page in doc:
            for block in page.get_text("blocks"):
                text: str = block[4]
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
    finally:
        doc.close()

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
    skip_pages: set[int] | None = None,
    dpi: int = 200,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Detect the student's selected answers from an annotated MCQ QP PDF.

    Renders the QP page-by-page (grouping cross-page questions onto one call),
    sends each image batch to the VL model, and returns detected answers.

    Args:
        qp_pdf_path: Annotated question paper PDF (student's GoodNotes export).
        answer_key: PaperConfig from ``parse_mcq_mark_scheme``.
        grader_config: VL API credentials.
        skip_pages: 0-indexed pages to skip (defaults to {0, 1}: cover + data).
        dpi: Render resolution.
        on_progress: Callback ``(current_batch, total_batches)``.

    Returns:
        ``(detected, undetected)`` where ``detected`` maps question IDs to the
        student's selected letter, and ``undetected`` lists question IDs the VL
        could not find or was uncertain about.
    """
    from modules.pdf_renderer import render_pdf_pages

    path = Path(qp_pdf_path)
    if skip_pages is None:
        # Derive skip set from paper_page_config.json using the QP filename.
        # Filename format: "<subject>_<season><year>_qp_<component>.pdf"
        m = re.match(r"(\d{4})_[a-z]\d{2}_qp_(\d+)", path.stem, re.IGNORECASE)
        if m:
            from core.config_store import get_paper_page_config
            cfg = get_paper_page_config(m.group(1), m.group(2))
            skip = cfg.qp_skip_pages
        else:
            skip = {0, 1}
    else:
        skip = skip_pages
    q_ids = list(answer_key.questions.keys())
    doc = fitz.open(str(path))
    try:
        page_batches = _build_page_batches(doc, skip)

        raw_detected: dict[str, str] = {}  # "1" → "C"
        total = len(page_batches)

        for idx, page_idxs in enumerate(page_batches):
            if on_progress:
                on_progress(idx + 1, total)
            # render_pdf_pages is 1-indexed
            images = render_pdf_pages(doc, [p + 1 for p in page_idxs], dpi=dpi)
            batch_result = _call_vl(grader_config, images)
            raw_detected.update(batch_result)
    finally:
        doc.close()

    # Normalise to Q-prefixed IDs and filter to known questions
    detected: dict[str, str] = {}
    for q_num_str, letter in raw_detected.items():
        qid = f"Q{q_num_str}"
        if qid in answer_key.questions:
            detected[qid] = letter

    undetected = [qid for qid in q_ids if qid not in detected]
    return detected, undetected


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
