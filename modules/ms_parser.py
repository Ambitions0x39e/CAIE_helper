# modules/ms_parser.py
"""Parse CIE mark scheme PDFs into structured question configs.

Dispatches to a paper-type-specific parser. Only MATH is implemented now.
Ported from D:\\repos\\grader\\ms2yaml.py (PyMuPDF backend).
"""
from __future__ import annotations

import base64
import json
import re
from collections import OrderedDict
from pathlib import Path

import fitz
from pydantic import BaseModel

from core.models import PaperType

GARBLED_CHARS = re.compile(r"[§·ª º¨¸«»¬¼©¹\x0e\x0b\x0c\x10]")
MULTI_SPACE = re.compile(r"  +")
QUESTION_ID_RE = re.compile(r"^(\d+)(?:\(([a-z])\))?$")

SHIFTED_CHAR_MAP = {
    "\x03": " ", "\x11": ".", "\x13": "0",
    "\xb5": "'", "\xb6": "'",
    "\\": "Y", "$": "A", "(": "E", "7": "T",
}

SHIFTED_RUN_RE = re.compile(
    r"(?:[\x03\x11\x13\xb5\xb6$\\(7]|[A-Z]){4,}"
)


class QuestionConfig(BaseModel):
    max_marks: int
    mark_scheme: str


class PaperConfig(BaseModel):
    paper_id: str
    total_marks: int
    questions: dict[str, QuestionConfig]


def _decode_shifted_char(c: str) -> str:
    if c in SHIFTED_CHAR_MAP:
        return SHIFTED_CHAR_MAP[c]
    if c.isalpha():
        base = ord("A") if c.isupper() else ord("a")
        return chr((ord(c) - base - 3) % 26 + base)
    return c


def _decode_shifted_run(m: re.Match[str]) -> str:
    run = m.group(0)
    decoded = "".join(_decode_shifted_char(c) for c in run)
    if sum(1 for c in decoded if c.isalpha()) >= 3:
        return decoded
    return run


def decode_shifted_text(text: str) -> str:
    return SHIFTED_RUN_RE.sub(_decode_shifted_run, text)


def clean_text(text: str) -> str:
    text = decode_shifted_text(text)
    text = GARBLED_CHARS.sub(" ", text)
    text = MULTI_SPACE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def normalize_question_id(raw: str) -> str:
    raw = raw.strip()
    m = QUESTION_ID_RE.match(raw)
    if m:
        qid = f"Q{m.group(1)}"
        if m.group(2):
            qid += m.group(2)
        return qid
    return f"Q{raw}"


def _extract_paper_info(doc: fitz.Document) -> tuple[str, int]:
    text = doc[0].get_text()
    paper_id = ""
    total_marks = 0

    m = re.search(r"(\d{4}/\d{2})", text)
    if m:
        paper_id = m.group(1)

    session = ""
    if "October/November" in text:
        session = "O/N"
    elif "May/June" in text:
        session = "M/J"
    elif "February/March" in text:
        session = "F/M"

    year_m = re.search(r"(20\d{2})", text)
    year = year_m.group(1)[-2:] if year_m else ""
    if paper_id and session and year:
        paper_id = f"{paper_id}/{session}/{year}"

    m = re.search(r"Maximum Mark:\s*(\d+)", text)
    if m:
        total_marks = int(m.group(1))

    return paper_id, total_marks


def _is_max_marks_row(entry: dict[str, str]) -> int | None:
    marks = entry["marks"]
    if not marks:
        return None
    if marks.isdigit() and not entry["answer"]:
        return int(marks)
    return None


def _parse_table_rows(table: object) -> list[dict[str, str]]:
    rows = table.extract()  # type: ignore[attr-defined]
    entries: list[dict[str, str]] = []
    for row in rows:
        def cell(i: int, r: list[str | None] = row) -> str:  # noqa: B006
            val = r[i] if i < len(r) and r[i] else ""
            return (val or "").strip()
        question = cell(0)
        answer = cell(3)
        marks = cell(6)
        guidance = cell(9)
        if not question and not answer and not marks and not guidance:
            continue
        if marks in ("Marks",) and guidance in ("Guidance",):
            continue
        entries.append({
            "question": question,
            "answer": answer,
            "marks": marks,
            "guidance": guidance,
        })
    return entries


class _QEntry:
    __slots__ = ("mark_lines", "max_marks")

    def __init__(self) -> None:
        self.mark_lines: list[str] = []
        self.max_marks: int = 0


def _group_questions(
    all_entries: list[dict[str, str]],
) -> OrderedDict[str, _QEntry]:
    questions: OrderedDict[str, _QEntry] = OrderedDict()
    current_qid = None

    for entry in all_entries:
        if entry["question"] and QUESTION_ID_RE.match(entry["question"]):
            current_qid = normalize_question_id(entry["question"])
            if current_qid not in questions:
                questions[current_qid] = _QEntry()

        if current_qid is None:
            continue

        q = questions[current_qid]

        max_m = _is_max_marks_row(entry)
        if max_m is not None:
            q.max_marks = max_m
            if entry.get("guidance", "").strip():
                q.mark_lines.append(f"Note: {clean_text(entry['guidance'])}")
            continue

        marks_str = entry["marks"].strip()
        answer_str = clean_text(entry["answer"])
        guidance_str = clean_text(entry["guidance"])

        if not marks_str and not answer_str:
            continue

        line_parts: list[str] = []
        if marks_str:
            line_parts.append(f"{marks_str}:")
        if answer_str:
            line_parts.append(answer_str)
        if guidance_str:
            line_parts.append(f"[{guidance_str}]")

        if line_parts:
            q.mark_lines.append(" ".join(line_parts))

    return questions


def _parse_math_ms(
    pdf_path: str | Path,
    start_page: int = 6,
) -> PaperConfig:
    """Math-specific MS parser using PyMuPDF table extraction."""
    doc = fitz.open(str(pdf_path))
    paper_id, total_marks = _extract_paper_info(doc)

    all_entries = []
    for pg_idx in range(start_page - 1, len(doc)):
        page = doc[pg_idx]
        tables = page.find_tables()
        if not tables.tables:
            continue
        for table in tables.tables:
            entries = _parse_table_rows(table)
            all_entries.extend(entries)

    raw_questions = _group_questions(all_entries)
    doc.close()

    questions: dict[str, QuestionConfig] = {}
    for qid, qdata in raw_questions.items():
        mark_scheme = "\n".join(qdata.mark_lines)
        questions[qid] = QuestionConfig(
            max_marks=qdata.max_marks,
            mark_scheme=mark_scheme if mark_scheme else "# No mark scheme extracted",
        )

    return PaperConfig(
        paper_id=paper_id,
        total_marks=total_marks,
        questions=questions,
    )


def detect_image_pages(
    pdf_path: str | Path,
    start_page: int = 6,
) -> list[int]:
    """Find mark scheme pages that are image-only (no extractable tables).

    Returns 1-indexed page numbers of pages that contain an embedded
    image but no table data and no meaningful text.
    """
    doc = fitz.open(str(pdf_path))
    image_pages: list[int] = []
    try:
        for pg_idx in range(start_page - 1, len(doc)):
            page = doc[pg_idx]
            tables = page.find_tables()
            text = page.get_text().strip()
            images = page.get_images()
            if not tables.tables and not text and images:
                image_pages.append(pg_idx + 1)
    finally:
        doc.close()
    return image_pages


_IMAGE_MS_PROMPT = """\
You are reading page(s) from a CIE (Cambridge International) \
A-Level mark scheme PDF. These pages were embedded as images.

Extract ALL questions and sub-parts visible in these images.

Output ONLY valid JSON — no markdown fences, no commentary:
{
  "questions": [
    {
      "id": "1",
      "max_marks": 5,
      "mark_scheme": "B1: criterion ...\\nM1: method ...\\nA1: accuracy ..."
    }
  ]
}

Rules:
- "id" uses the printed format: "1" for a standalone question, \
"6(a)" for sub-parts.
- "max_marks" is the total marks for that question/sub-part \
(the bold number usually at the bottom of its row).
- "mark_scheme" lists every marking point on separate lines \
(\\n-separated).  Keep the mark codes (B1, M1, A1, etc.) and \
their criteria.  Include guidance/notes if present.
- If a question spans multiple images, combine them into one entry.
- Do NOT invent marks — only report what is visible."""


def extract_ms_from_images(
    grader_config: object,
    pdf_path: str | Path,
    image_pages: list[int],
    dpi: int = 200,
) -> dict[str, QuestionConfig]:
    """Use a VL model to extract mark scheme from image-only pages.

    Args:
        grader_config: A ``GraderConfig`` instance (typed as object
            to avoid a hard import cycle — only ``api_key``,
            ``base_url``, ``model`` are accessed).
        pdf_path: Path to the mark scheme PDF.
        image_pages: 1-indexed page numbers to process.
        dpi: Render resolution for page images.

    Returns:
        Dict mapping normalised question IDs to ``QuestionConfig``.
    """
    if not image_pages:
        return {}

    from openai import OpenAI

    doc = fitz.open(str(pdf_path))
    try:
        png_list: list[bytes] = []
        for pg_num in image_pages:
            page = doc[pg_num - 1]
            pix = page.get_pixmap(dpi=dpi)
            png_list.append(pix.tobytes("png"))
    finally:
        doc.close()

    content: list[dict[str, object]] = []
    for png in png_list:
        b64 = base64.b64encode(png).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
            },
        })
    content.append({"type": "text", "text": _IMAGE_MS_PROMPT})

    api_key = grader_config.api_key  # type: ignore[attr-defined]
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()

    client = OpenAI(
        api_key=api_key,
        base_url=grader_config.base_url,  # type: ignore[attr-defined]
    )
    response = client.chat.completions.create(
        model=grader_config.model,  # type: ignore[attr-defined]
        messages=[{"role": "user", "content": content}],  # type: ignore[list-item]
        temperature=0.1,
    )
    raw = str(response.choices[0].message.content)
    return _parse_image_ms_response(raw)


def _parse_image_ms_response(
    raw: str,
) -> dict[str, QuestionConfig]:
    """Parse the VL model JSON response into QuestionConfig entries."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    questions: dict[str, QuestionConfig] = {}

    for entry in data.get("questions", []):
        raw_id = str(entry.get("id", ""))
        qid = normalize_question_id(raw_id)
        max_marks = int(entry.get("max_marks", 0))
        ms_text = str(entry.get("mark_scheme", ""))

        if not ms_text:
            ms_text = "# No mark scheme extracted"

        questions[qid] = QuestionConfig(
            max_marks=max_marks,
            mark_scheme=ms_text,
        )

    return questions


def parse_mark_scheme(
    pdf_path: str | Path,
    paper_type: PaperType,
    start_page: int = 6,
) -> PaperConfig:
    """Dispatch to the correct parser based on paper type.

    Args:
        pdf_path: Path to the MS PDF file.
        paper_type: Determines which parsing strategy to use.
        start_page: First page with actual mark scheme content (1-indexed).

    Raises:
        NotImplementedError: If paper_type has no parser yet.
    """
    if paper_type == PaperType.MATH:
        return _parse_math_ms(pdf_path, start_page)
    raise NotImplementedError(f"No mark scheme parser for {paper_type.value}")
