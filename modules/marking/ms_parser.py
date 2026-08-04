# modules/ms_parser.py
"""Parse CIE mark scheme PDFs into structured question configs via VL model.

Renders all mark-scheme pages to images, sends them in batches to a
vision-language model, and parses the structured JSON response into
``PaperConfig``.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI
from pdfminer.high_level import extract_text
from pydantic import BaseModel

from core.models import PaperType
from core.settings import GraderConfig
from modules.marking.renderer import page_count, to_pdf_bytes

if TYPE_CHECKING:
    from modules.marking.renderer import NativeRenderer

QUESTION_ID_RE = re.compile(r"^(\d+)(?:\(([a-z])\))?$")

_MAIN_NUM_RE = re.compile(r"\d+")
_SUB_LETTER_RE = re.compile(r"[a-z]")
_ROMAN_SUFFIX_RE = re.compile(r"\(([ivx]+)\)\s*$")
_ROMAN_VALUES = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}


def _question_sort_key(qid: str) -> tuple[int, str, int]:
    """Sort key that orders question IDs numerically, not lexicographically.

    Question IDs come in mixed notation from VL extraction — normalised
    ("Q2a") and raw nested ("Q2(b)(i)") — so a plain string compare puts
    "(" (ASCII 40) before letters, sorting "Q2(b)(i)" before "Q2a". This
    extracts (main_number, sub_letter, sub_roman_index) so ordering is
    numeric/alphabetic regardless of notation style.
    """
    body = qid[1:] if qid.startswith("Q") else qid
    num_m = _MAIN_NUM_RE.search(body)
    main_num = int(num_m.group()) if num_m else 0

    rest = body[num_m.end():] if num_m else body
    letter_m = _SUB_LETTER_RE.search(rest)
    letter = letter_m.group() if letter_m else ""

    roman_m = _ROMAN_SUFFIX_RE.search(body)
    roman = _ROMAN_VALUES.get(roman_m.group(1), 0) if roman_m else 0

    return (main_num, letter, roman)


class QuestionConfig(BaseModel):
    max_marks: int
    mark_scheme: str


class PaperConfig(BaseModel):
    paper_id: str
    total_marks: int
    questions: dict[str, QuestionConfig]


# ── Helpers ──────────────────────────────────────────────────────


def normalize_question_id(raw: str) -> str:
    raw = raw.strip()
    m = QUESTION_ID_RE.match(raw)
    if m:
        qid = f"Q{m.group(1)}"
        if m.group(2):
            qid += m.group(2)
        return qid
    return f"Q{raw}"


# ── Start-page detection ─────────────────────────────────────────

# Every text-based mark-scheme content page repeats this table header;
# the cover page and generic-marking-principles pages never carry all
# three tokens together.
_MS_TABLE_HEADER = ("Question", "Answer", "Marks")
_MS_START_PAGE_FALLBACK = 6
_MS_START_SCAN_PAGES = 14


def detect_ms_start_page(pdf_path: str | bytes | Path) -> int | None:
    """Find the first page carrying question content (1-indexed).

    Mark schemes open with a cover page and generic marking principles
    before the questions start, but how many such pages there are varies
    by syllabus and series — 9618 has been seen starting on page 3, 9231
    on page 6, 9702 Paper 2 on page 8 — so it is detected, not assumed.

    Two signals mark a content page, and we take the EARLIER of them:

    * the repeated "Question / Answer / Marks" table header (text-based
      content pages), and
    * the first page with no text layer after the cover — mark schemes
      whose answers are scanned images render as empty text, and the
      opening question(s) often sit on those imaged pages BEFORE the
      first page that still carries the header (e.g. 9618/w25/13 images
      Q1 on pages 3-4, header first appears on page 5).

    Preferring the earlier signal keeps detection biased toward starting
    too early rather than too late: an extra front-matter page rendered
    to the VL model just yields no questions, whereas starting late drops
    real questions. Returns None only when neither signal fires within
    the first ``_MS_START_SCAN_PAGES`` pages; callers fall back to
    ``_MS_START_PAGE_FALLBACK`` (see :func:`resolve_ms_start_page`).
    """
    data = to_pdf_bytes(pdf_path)
    limit = min(page_count(data), _MS_START_SCAN_PAGES)
    header_pg: int | None = None
    imaged_pg: int | None = None
    for pg in range(limit):
        text = extract_text(io.BytesIO(data), page_numbers=[pg]) or ""
        if header_pg is None and all(t in text for t in _MS_TABLE_HEADER):
            header_pg = pg + 1
        # An empty text layer past the cover = image-rendered content.
        if imaged_pg is None and pg >= 1 and not text.strip():
            imaged_pg = pg + 1
        if header_pg is not None and imaged_pg is not None:
            break

    candidates = [p for p in (header_pg, imaged_pg) if p is not None]
    return min(candidates) if candidates else None


def resolve_ms_start_page(
    pdf_path: str | bytes | Path,
    start_page: int | None,
) -> int:
    """Resolve an explicit start page, or detect one, or fall back."""
    if start_page is not None:
        return start_page
    return detect_ms_start_page(pdf_path) or _MS_START_PAGE_FALLBACK


def _paper_info_from_text(text: str) -> tuple[str, int]:
    """Pull paper_id and total_marks out of cover-page text.

    Mark schemes in a custom CID font extract one glyph per line, with the
    glyphs pdfminer cannot map dropped entirely (on 9701 chemistry every
    "i" is missing), so "Maximum Mark: 60" arrives as a column of characters
    spelling "MaxmumMark:60". Matching against the text as-extracted found
    nothing and the paper reported an empty id and 0 total marks.

    Collapsing all whitespace puts a shredded cover back into a matchable
    shape, but it also destroys the line break that separates "Maximum Mark:
    75" from the syllabus code beneath it (9618 read as 759618). So each
    field is looked up in the text as-extracted FIRST and only falls back to
    the collapsed form — a readable cover never reaches the fallback, and a
    shredded one has no boundaries left to lose.
    """
    squashed = re.sub(r"\s+", "", text)

    def find(pattern: str) -> str | None:
        m = re.search(pattern, text) or re.search(pattern, squashed)
        return m.group(1) if m else None

    def present(token: str) -> bool:
        return token in text or token in squashed

    paper_id = find(r"(\d{4}/\d{2})") or ""

    session = ""
    if present("October/November"):
        session = "O/N"
    elif present("May/June"):
        session = "M/J"
    elif present("February/March"):
        session = "F/M"

    year = (find(r"(20\d{2})") or "")[-2:]
    if paper_id and session and year:
        paper_id = f"{paper_id}/{session}/{year}"

    # \w{0,6} absorbs the glyphs dropped from "Maximum" (9701 yields "Maxmum").
    raw_marks = find(r"Max\w{0,6}\s*Mark\s*:?\s*(\d+)")
    total_marks = int(raw_marks) if raw_marks else 0

    return paper_id, total_marks


def _extract_paper_info(pdf_path: str | Path) -> tuple[str, int]:
    """Extract paper_id and total_marks from the cover page via text.

    Uses pdfminer.six (pure Python, iOS-safe) on the first page only.
    """
    text = extract_text(io.BytesIO(to_pdf_bytes(pdf_path)), page_numbers=[0]) or ""
    return _paper_info_from_text(text)


# ── VL extraction ────────────────────────────────────────────────

_IMAGE_MS_PROMPT = """\
You are reading page(s) from a CIE (Cambridge International) \
A-Level mark scheme PDF.

Some questions may have started on previous pages and continue here. \
Extract what you see, including partial questions that began earlier.

Extract ALL questions and sub-parts visible in these images.

CRITICAL — for each marking point you MUST transcribe the ACTUAL \
mathematical expressions, formulas, and working shown in the image. \
Do NOT write generic descriptions like "method ..." or \
"criterion ...". Copy the real content.

Output ONLY valid JSON — no markdown fences, no extra text:
{
  "questions": [
    {
      "id": "1(a)",
      "max_marks": 3,
      "mark_scheme": "B1: y = x^3 + 1\\nM1: expand\\nA1: y^3 - 6y^2 + 20y - 16 = 0"
    }
  ]
}

Rules:
- "id": use the printed format — "1" or "6(a)" etc.
- "max_marks": the total marks for that question/sub-part.
- "mark_scheme": one line per marking point (\\n-separated). \
Each line starts with the mark code (B1, M1, A1, DM1 …) then a colon, \
then the ACTUAL mathematical content / condition / expression \
as printed in the image.
- Transcribe all algebra, equations, and working — do not summarise.
- If a question spans multiple images, combine into one entry.
- Do NOT invent marks — only report what is visible.

MARK CODES — the trailing digit is the POINT'S VALUE, not an index:
- A code is a letter part plus a digit: B1, B2, M1, A1, DM1, DB1 …
- The letters are the mark TYPE (B independent, M method, A accuracy, \
DM/DA dependent) and the DIGIT IS HOW MANY MARKS THAT ONE POINT IS WORTH. \
"B2" is a single marking point worth 2 marks; "M1" is worth 1.
- So "max_marks" is the SUM of those digits, NOT the number of lines. \
A part printed as "B2, M1, A1" has max_marks 4 over 3 lines.
- Keep the digit exactly as printed — never rewrite "B2" as "B1".

GUIDANCE COLUMN — transcribe it, attached to its marking point:
- CIE mark schemes print a "Guidance" column beside the Answer and Marks \
columns. It holds the detailed rules for awarding a point: what to accept \
or reject, "oe" / "ft" / "cao" / "isw" notes, allowed alternative methods, \
and common wrong answers to refuse.
- Put that text at the END of the line for the marking point it governs, \
in square brackets:
  "M1: attempt to expand (x+2)^3 [Guidance: allow one sign slip; \
must see at least 3 terms]"
- If a note applies to the whole question rather than one point, give it \
its own line: "[Guidance: accept decimals to 3sf throughout]"
- This column is what makes later grading accurate — do NOT omit it, and \
do not merge it into the answer text as if it were part of the answer."""


def _call_vl(
    grader_config: GraderConfig,
    png_list: list[bytes],
    prompt: str,
) -> str:
    """Send page images + prompt to VL API and return raw response text."""
    content: list[dict[str, object]] = []
    for png in png_list:
        b64 = base64.b64encode(png).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    content.append({"type": "text", "text": prompt})

    client = OpenAI(
        api_key=grader_config.api_key.get_secret_value(),
        base_url=grader_config.base_url,
    )
    response = client.chat.completions.create(
        model=grader_config.model,
        messages=[{"role": "user", "content": content}],  # type: ignore[list-item, misc]
        temperature=0.1,
    )
    return str(response.choices[0].message.content)


def _coerce_marks(value: object) -> int:
    """Best-effort int for a VL ``max_marks`` field.

    The model sometimes returns ``"N/A"``, ``""`` or a float for a row
    without a clean integer mark (a header, a "no marks" note, or a part it
    couldn't score). Fall back to 0 rather than crashing — one odd row must
    not throw away every question in the batch (this is what made the whole
    9701 chemistry mark scheme fail to parse).
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    match = re.match(r"\d+", str(value).strip())
    return int(match.group()) if match else 0


def _parse_image_ms_response(
    raw: str,
) -> dict[str, QuestionConfig]:
    """Parse the VL model JSON response into QuestionConfig entries."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(cleaned[start : end + 1])
        else:
            raise

    questions: dict[str, QuestionConfig] = {}
    for entry in data.get("questions", []):
        raw_id = str(entry.get("id", ""))
        qid = normalize_question_id(raw_id)
        max_marks = _coerce_marks(entry.get("max_marks", 0))
        ms_text = str(entry.get("mark_scheme", ""))
        if not ms_text:
            ms_text = "# No mark scheme extracted"
        questions[qid] = QuestionConfig(
            max_marks=max_marks,
            mark_scheme=ms_text,
        )
    return questions


def _merge_questions(
    base: dict[str, QuestionConfig],
    new: dict[str, QuestionConfig],
) -> dict[str, QuestionConfig]:
    """Merge two question dicts, combining entries for duplicate IDs."""
    merged = dict(base)
    for qid, qcfg in new.items():
        if qid in merged:
            existing = merged[qid]
            merged[qid] = QuestionConfig(
                max_marks=max(existing.max_marks, qcfg.max_marks),
                mark_scheme=existing.mark_scheme + "\n" + qcfg.mark_scheme,
            )
        else:
            merged[qid] = qcfg
    return merged


def _parse_all_vl(
    pdf_path: str | Path,
    grader_config: GraderConfig,
    renderer: NativeRenderer,
    start_page: int = 6,
    batch_size: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, QuestionConfig]:
    """Extract all questions from a mark scheme PDF using VL model.

    Renders all pages from *start_page* onward, batches them, and
    sends each batch to the VL model for structured extraction.

    Args:
        pdf_path: Path to the mark scheme PDF.
        grader_config: API credentials for VL model.
        start_page: First MS content page (1-indexed).
        batch_size: Max pages per API call.
        on_progress: Optional callback ``(current_batch, total_batches)``.

    Returns:
        Dict mapping normalised question IDs to ``QuestionConfig``.

    Raises:
        RuntimeError: If extraction fails or returns no questions.
    """
    pdf_bytes = to_pdf_bytes(pdf_path)
    pages = list(range(start_page, page_count(pdf_bytes) + 1))
    all_pngs = renderer.render_pages(pdf_bytes, pages, dpi=grader_config.dpi)
    if not all_pngs:
        raise RuntimeError(
            f"No pages to render from page {start_page} onward"
        )

    batches = [
        all_pngs[i : i + batch_size]
        for i in range(0, len(all_pngs), batch_size)
    ]

    all_questions: dict[str, QuestionConfig] = {}
    for batch_idx, batch in enumerate(batches):
        if on_progress is not None:
            on_progress(batch_idx + 1, len(batches))

        raw = _call_vl(grader_config, batch, _IMAGE_MS_PROMPT)
        batch_questions = _parse_image_ms_response(raw)
        all_questions = _merge_questions(all_questions, batch_questions)

    if not all_questions:
        raise RuntimeError("VL model returned no questions from any batch")

    sorted_questions = dict(
        sorted(
            all_questions.items(),
            key=lambda kv: _question_sort_key(kv[0]),
        )
    )
    return sorted_questions


# ── Public API ───────────────────────────────────────────────────


def _cache_path_for(pdf_path: Path, start_page: int | None = None) -> Path:
    """Return the JSON cache path for a mark scheme PDF.

    VL-parsed (MATH) caches embed the resolved start page in the key —
    the same PDF parsed from a different start page covers a different
    set of questions, so the results must not shadow each other. MCQ
    caches pass None and keep the plain filename key.
    """
    from core.settings import app_settings

    suffix = f".sp{start_page}" if start_page is not None else ""
    return app_settings.ms_cache_dir / f"{pdf_path.stem}{suffix}.json"


def _load_cached(
    pdf_path: Path, start_page: int | None = None
) -> PaperConfig | None:
    """Load a previously cached PaperConfig, or None on miss."""
    cp = _cache_path_for(pdf_path, start_page)
    if not cp.exists():
        return None
    try:
        return PaperConfig.model_validate_json(cp.read_text("utf-8"))
    except Exception:
        return None


def _save_cache(
    pdf_path: Path, config: PaperConfig, start_page: int | None = None
) -> None:
    """Persist a PaperConfig to the cache directory."""
    cp = _cache_path_for(pdf_path, start_page)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(config.model_dump_json(indent=2), "utf-8")


def _repair_cover_info(
    pdf_path: Path, config: PaperConfig, start_page: int | None
) -> PaperConfig:
    """Backfill paper_id / total_marks on a cache entry that lacks them.

    Papers parsed before ``_paper_info_from_text`` learned to read shredded
    cover pages cached an empty id and 0 total marks. Those two fields come
    from local text extraction, not the VL model, so a stale entry can be
    repaired for free — invalidating the cache instead would force a paid
    re-parse of every question just to fix two display fields.
    """
    if config.paper_id and config.total_marks:
        return config
    try:
        paper_id, total_marks = _extract_paper_info(pdf_path)
    except Exception:
        return config
    if not paper_id and not total_marks:
        return config

    repaired = config.model_copy(update={
        "paper_id": config.paper_id or paper_id,
        "total_marks": config.total_marks or total_marks,
    })
    # An unwritable cache must not fail the parse.
    with contextlib.suppress(Exception):
        _save_cache(pdf_path, repaired, start_page)
    return repaired


def ms_cache_exists(
    pdf_path: str | Path,
    paper_type: PaperType,
    start_page: int | None = None,
) -> bool:
    """Check whether ``parse_mark_scheme`` would hit its cache.

    Lets the UI show a "result came from cache" hint and offer a forced
    re-parse. For MATH the start page is resolved the same way
    ``parse_mark_scheme`` resolves it, so the answer matches what a
    subsequent call would actually do.
    """
    path = Path(pdf_path)
    if paper_type == PaperType.MCQ:
        return _cache_path_for(path).exists()
    resolved = resolve_ms_start_page(path, start_page)
    return _cache_path_for(path, resolved).exists()


def parse_mark_scheme(
    pdf_path: str | Path,
    paper_type: PaperType,
    grader_config: GraderConfig | None = None,
    start_page: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    renderer: NativeRenderer | None = None,
    force: bool = False,
) -> PaperConfig:
    """Parse a mark scheme PDF into structured question configs.

    Returns a cached result when available, otherwise dispatches to
    the appropriate parser and caches the result for future calls.

    Args:
        pdf_path: Path to the MS PDF file.
        paper_type: Determines which parsing strategy to use.
        grader_config: API credentials for VL model (required for MATH).
        start_page: First page with actual mark scheme content (1-indexed).
            None auto-detects it — pass a number only to override.
        on_progress: Optional callback ``(current_batch, total_batches)``.
        force: Skip the cache and re-parse (the result is re-cached).

    Raises:
        NotImplementedError: If paper_type has no parser yet.
        ValueError: If grader_config is None for a VL-based paper type.
    """
    path = Path(pdf_path)

    if paper_type == PaperType.MCQ:
        cached = None if force else _load_cached(path)
        if cached is not None:
            return cached
        from modules.marking.mcq_parser import parse_mcq_mark_scheme
        config = parse_mcq_mark_scheme(pdf_path)
        _save_cache(path, config)
        return config

    if paper_type != PaperType.MATH:
        raise NotImplementedError(
            f"No mark scheme parser for {paper_type.value}"
        )

    # Resolve the start page BEFORE the cache lookup: the cache key
    # embeds it, so parses from different start pages never shadow each
    # other (a manual override after an auto-detect re-parses cleanly).
    resolved_start = resolve_ms_start_page(pdf_path, start_page)
    cached = None if force else _load_cached(path, resolved_start)
    if cached is not None:
        return _repair_cover_info(path, cached, resolved_start)

    if grader_config is None:
        raise ValueError(
            "grader_config is required for MATH mark scheme parsing"
        )
    if renderer is None:
        raise ValueError(
            "renderer is required for MATH mark scheme parsing"
        )

    paper_id, total_marks = _extract_paper_info(pdf_path)

    questions = _parse_all_vl(
        pdf_path,
        grader_config,
        renderer,
        start_page=resolved_start,
        on_progress=on_progress,
    )

    config = PaperConfig(
        paper_id=paper_id,
        total_marks=total_marks,
        questions=questions,
    )
    _save_cache(path, config, resolved_start)
    return config
