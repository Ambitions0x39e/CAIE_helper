# modules/ms_parser.py
"""Parse CIE mark scheme PDFs into structured question configs.

Dispatches to a paper-type-specific parser. Only MATH is implemented now.
Ported from D:\\repos\\grader\\ms2yaml.py (PyMuPDF backend).
"""
from __future__ import annotations

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


def _decode_shifted_run(m: re.Match) -> str:
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
    lines = [l for l in lines if l]
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


def _is_max_marks_row(entry: dict) -> int | None:
    marks = entry["marks"]
    if not marks:
        return None
    if marks.isdigit() and not entry["answer"]:
        return int(marks)
    return None


def _parse_table_rows(table) -> list[dict]:
    rows = table.extract()
    entries = []
    for row in rows:
        cell = lambda i: (row[i] if i < len(row) and row[i] else "").strip()
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


def _group_questions(all_entries: list[dict]) -> OrderedDict:
    questions: OrderedDict = OrderedDict()
    current_qid = None

    for entry in all_entries:
        if entry["question"] and QUESTION_ID_RE.match(entry["question"]):
            current_qid = normalize_question_id(entry["question"])
            if current_qid not in questions:
                questions[current_qid] = {"mark_lines": [], "max_marks": 0}

        if current_qid is None:
            continue

        q = questions[current_qid]

        max_m = _is_max_marks_row(entry)
        if max_m is not None:
            q["max_marks"] = max_m
            if entry.get("guidance", "").strip():
                q["mark_lines"].append(f"Note: {clean_text(entry['guidance'])}")
            continue

        marks_str = entry["marks"].strip()
        answer_str = clean_text(entry["answer"])
        guidance_str = clean_text(entry["guidance"])

        if not marks_str and not answer_str:
            continue

        line_parts = []
        if marks_str:
            line_parts.append(f"{marks_str}:")
        if answer_str:
            line_parts.append(answer_str)
        if guidance_str:
            line_parts.append(f"[{guidance_str}]")

        if line_parts:
            q["mark_lines"].append(" ".join(line_parts))

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

    questions = {}
    for qid, qdata in raw_questions.items():
        mark_scheme = "\n".join(qdata["mark_lines"])
        questions[qid] = QuestionConfig(
            max_marks=qdata["max_marks"],
            mark_scheme=mark_scheme if mark_scheme else "# No mark scheme extracted",
        )

    return PaperConfig(
        paper_id=paper_id,
        total_marks=total_marks,
        questions=questions,
    )


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
