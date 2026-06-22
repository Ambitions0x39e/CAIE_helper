# modules/page_segmenter.py
"""Auto-detect question boundaries in CIE answer papers using PDF text positions.

CIE PDFs use custom font encoding (text is garbled), but span coordinates are
precise.  Question numbers appear at fixed X positions:
  - Main question numbers (1, 2, …) at x ≈ 72.4 with len == 2
  - Sub-question labels (a), (b), … at x ≈ 93.7 starting with byte 0xa8

This module detects those positions and maps them to the ordered question IDs
from the parsed mark scheme, producing clip rectangles for cropped rendering.
"""
from __future__ import annotations

import re
from enum import Enum

import fitz
from pydantic import BaseModel


# ── Models ────────────────────────────────────────────────────────

class PageClip(BaseModel):
    """A clipping rectangle on a single PDF page (coordinates in points)."""
    page_idx: int
    y_top: float
    y_bottom: float


class QuestionRegion(BaseModel):
    """The rectangular region(s) for one question, possibly spanning pages."""
    question_id: str
    clips: list[PageClip]


# ── Internal types ────────────────────────────────────────────────

class _BoundaryKind(str, Enum):
    MAIN = "main"
    SUB = "sub"


class _Boundary(BaseModel):
    kind: _BoundaryKind
    page_idx: int
    y: float
    question_num: int | None = None


# ── Page-format constants ─────────────────────────────────────────

_FORMAT_PARAMS: dict[str, dict[str, float]] = {
    "letter": {
        "left_margin_x": 72.4,
        "sub_q_x": 93.7,
        "footer_y": 740.0,
        "top_margin": 45.0,
    },
    "a4": {
        "left_margin_x": 70.0,
        "sub_q_x": 91.0,
        "footer_y": 790.0,
        "top_margin": 45.0,
    },
}

_X_TOLERANCE = 3.0


def _detect_format(page: fitz.Page) -> str:
    w = page.rect.width
    if abs(w - 595) < 10:
        return "a4"
    return "letter"


# ── Bracket-pair auto-detection ──────────────────────────────────

def _detect_bracket_pair(
    per_page: list[tuple[int, list[dict], dict[float, list[dict]]]],
    sqx: float,
) -> tuple[int, int] | None:
    """Auto-detect which (byte0, byte2) pair represents garbled '(' and ')'.

    CIE PDFs use custom font encoding — the bytes for parentheses vary
    between papers.  Sub-question labels like (a), (b) always share the
    same (open_paren, close_paren) pair at positions 0 and 2, so the
    most frequent pair is the bracket encoding.
    """
    from collections import Counter
    pair_counts: Counter[tuple[int, int]] = Counter()

    for _, all_left_spans, spans_at_y in per_page:
        for span in all_left_spans:
            if span["len"] != 1:
                continue
            y0 = span["y0"]
            for c in spans_at_y.get(y0, []):
                if abs(c["x0"] - sqx) < _X_TOLERANCE and c["len"] >= 3:
                    raw = c["text"]
                    pair_counts[(ord(raw[0]), ord(raw[2]))] += 1

    if not pair_counts:
        return None

    best_pair, count = pair_counts.most_common(1)[0]
    if count >= 2:
        return best_pair
    return None


# ── Character mapping (garbled font decoding) ────────────────────

def _build_char_mapping(
    doc: fitz.Document,
) -> dict[int, str] | None:
    """Build byte→digit mapping from page number spans.

    CIE garbled PDFs use the same 'AllAndNone' font for page numbers and
    question numbers.  Since we know each page's printed number (pg N in
    the PDF shows page N+1), we can reverse-engineer the byte→digit table
    and reuse it to decode question numbers.

    Returns None if the PDF uses readable text (no mapping needed).
    """
    pw = doc[0].rect.width
    center_x = pw / 2

    page_num_spans: list[tuple[int, str]] = []
    for pg_idx in range(len(doc)):
        page = doc[pg_idx]
        td = page.get_text("dict")
        for block in td.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if not text:
                        continue
                    bbox = span["bbox"]
                    if bbox[1] < 40 and abs(bbox[0] - center_x) < 100:
                        if _is_ascii_digit_str(text):
                            return None
                        page_num_spans.append((pg_idx, text))

    if not page_num_spans:
        return None

    page_num_spans.sort()
    mapping: dict[int, str] = {}
    for pg_idx, text in page_num_spans:
        expected = str(pg_idx + 1)
        if len(text) != len(expected):
            continue
        for ch, digit in zip(text, expected):
            b = ord(ch)
            if b in mapping and mapping[b] != digit:
                continue
            mapping[b] = digit

    return mapping if len(mapping) >= 3 else None


_ASCII_DIGITS = set("0123456789")


def _is_ascii_digit_str(s: str) -> bool:
    return bool(s) and all(c in _ASCII_DIGITS for c in s)


def _decode_question_num(
    text: str,
    mapping: dict[int, str] | None,
) -> int | None:
    """Decode a question number from MAIN boundary text."""
    if mapping is None:
        cleaned = text.strip()
        return int(cleaned) if _is_ascii_digit_str(cleaned) else None

    first = ord(text[0])
    if first not in mapping:
        return None
    result = mapping[first]

    if len(text) >= 2:
        second = ord(text[1])
        if second in mapping:
            result += mapping[second]

    return int(result) if result.isdigit() else None


# ── Boundary detection ────────────────────────────────────────────

def _extract_boundaries(
    doc: fitz.Document,
    *,
    skip_pages: set[int] | None = None,
) -> list[_Boundary]:
    """Scan every page and return ordered question-start boundaries."""
    if not len(doc):
        return []

    fmt = _detect_format(doc[0])
    params = _FORMAT_PARAMS[fmt]
    lx = params["left_margin_x"]
    sqx = params["sub_q_x"]
    footer_y = params["footer_y"]
    skip = skip_pages or set()

    char_map = _build_char_mapping(doc)

    # First pass: collect span data from all pages
    per_page: list[tuple[int, list[dict], dict[float, list[dict]]]] = []

    for pg_idx in range(len(doc)):
        if pg_idx in skip:
            continue

        page = doc[pg_idx]
        d = page.get_text("dict")

        spans_at_y: dict[float, list[dict]] = {}
        left_spans: list[dict] = []
        sub_q_spans: list[dict] = []

        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if not text:
                        continue
                    bbox = span["bbox"]
                    x0 = bbox[0]
                    y0 = round(bbox[1], 1)

                    entry = {"x0": x0, "y0": y0, "text": text, "len": len(text)}

                    if y0 not in spans_at_y:
                        spans_at_y[y0] = []
                    spans_at_y[y0].append(entry)

                    if y0 < footer_y:
                        if abs(x0 - lx) < _X_TOLERANCE and len(text) <= 2:
                            left_spans.append(entry)
                        if abs(x0 - sqx) < _X_TOLERANCE and len(text) >= 3:
                            sub_q_spans.append(entry)

        per_page.append((pg_idx, left_spans, sub_q_spans, spans_at_y))

    # Auto-detect the bracket encoding for this paper (garbled format)
    garbled_page_data = [
        (pg_idx, ls, sy) for pg_idx, ls, _, sy in per_page
    ]
    bracket_pair = _detect_bracket_pair(garbled_page_data, sqx)

    # Second pass: classify boundaries
    boundaries: list[_Boundary] = []

    for pg_idx, left_spans, sub_q_spans, spans_at_y in per_page:
        # --- MAIN detection ---
        for span in left_spans:
            y0 = span["y0"]
            text = span["text"]
            if _is_ascii_digit_str(text):
                boundaries.append(_Boundary(
                    kind=_BoundaryKind.MAIN, page_idx=pg_idx, y=y0,
                    question_num=int(text),
                ))
            elif span["len"] == 2:
                qnum = _decode_question_num(text, char_map)
                boundaries.append(_Boundary(
                    kind=_BoundaryKind.MAIN, page_idx=pg_idx, y=y0,
                    question_num=qnum,
                ))
            elif span["len"] == 1 and bracket_pair is not None:
                companions = spans_at_y.get(y0, [])
                for c in companions:
                    if abs(c["x0"] - sqx) < _X_TOLERANCE and c["len"] >= 3:
                        raw = c["text"]
                        if (ord(raw[0]), ord(raw[2])) == bracket_pair:
                            boundaries.append(_Boundary(
                                kind=_BoundaryKind.SUB, page_idx=pg_idx, y=y0,
                            ))
                            break

        # --- Readable SUB detection: "(a)", "(b)" directly at x≈sub_q_x ---
        for span in sub_q_spans:
            raw = span["text"]
            if raw[0] == "(" and raw[2] == ")" and raw[1].isalpha():
                boundaries.append(_Boundary(
                    kind=_BoundaryKind.SUB, page_idx=pg_idx, y=span["y0"],
                ))

    boundaries.sort(key=lambda b: (b.page_idx, b.y))
    return boundaries


# ── Match boundaries to question IDs ──────────────────────────────

def _has_sub_letter(qid: str) -> bool:
    """Check if a question ID ends with a lowercase letter (e.g. Q1a)."""
    return bool(re.search(r"[a-z]$", qid))


def _extract_main_num(qid: str) -> str:
    """Extract main question number from a question ID.

    "1a" → "1", "10b" → "10", "Q1a" → "1", "1" → "1"
    """
    m = re.search(r"(\d+)", qid)
    return m.group(1) if m else qid


def _group_qids(question_ids: list[str]) -> list[list[str]]:
    """Group question IDs by main question number, preserving order."""
    groups: list[list[str]] = []
    prev_num = None
    for qid in question_ids:
        num = _extract_main_num(qid)
        if num != prev_num:
            groups.append([])
            prev_num = num
        groups[-1].append(qid)
    return groups


def _group_boundaries(
    boundaries: list[_Boundary],
) -> list[tuple[_Boundary, list[_Boundary]]]:
    """Group boundaries into (MAIN, [SUBs]) tuples."""
    groups: list[tuple[_Boundary, list[_Boundary]]] = []
    for b in boundaries:
        if b.kind == _BoundaryKind.MAIN:
            groups.append((b, []))
        elif b.kind == _BoundaryKind.SUB:
            if groups:
                groups[-1][1].append(b)
    return groups


def _match_boundaries(
    boundaries: list[_Boundary],
    question_ids: list[str],
) -> list[tuple[str, int, float]]:
    """Match detected boundaries to ordered question IDs by question number.

    Each MAIN boundary carries a decoded ``question_num``.  Question IDs
    are grouped by their numeric prefix and looked up by number, so the
    matching is independent of detection order or false positives.

    Falls back to positional matching when no MAIN has a decoded number
    (e.g. synthetic test PDFs without page numbers).

    Returns list of (question_id, page_idx, y_start) tuples.
    """
    if not boundaries or not question_ids:
        return []

    b_groups = _group_boundaries(boundaries)
    q_groups = _group_qids(question_ids)

    has_nums = any(main_b.question_num is not None for main_b, _ in b_groups)

    if has_nums:
        b_by_num: dict[int, tuple[_Boundary, list[_Boundary]]] = {}
        for main_b, sub_bs in b_groups:
            if main_b.question_num is not None:
                b_by_num[main_b.question_num] = (main_b, sub_bs)
    else:
        b_by_num = None

    matches: list[tuple[str, int, float]] = []

    for g_idx, qids in enumerate(q_groups):
        main_num = int(_extract_main_num(qids[0]))

        if b_by_num is not None:
            group = b_by_num.get(main_num)
        else:
            group = b_groups[g_idx] if g_idx < len(b_groups) else None

        if group is None:
            continue

        main_b, sub_bs = group

        if not sub_bs or not _has_sub_letter(qids[0]):
            matches.append((qids[0], main_b.page_idx, main_b.y))
        else:
            for s_idx, qid in enumerate(qids):
                if s_idx == 0:
                    matches.append((qid, main_b.page_idx, main_b.y))
                elif s_idx < len(sub_bs):
                    sb = sub_bs[s_idx]
                    matches.append((qid, sb.page_idx, sb.y))

    return matches


# ── Convert matches to regions ────────────────────────────────────

def _build_regions(
    matches: list[tuple[str, int, float]],
    doc: fitz.Document,
    footer_y: float,
    top_margin: float,
) -> list[QuestionRegion]:
    """Convert (qid, page, y) tuples into QuestionRegion with PageClips."""
    if not matches:
        return []

    total_pages = len(doc)
    regions: list[QuestionRegion] = []

    for idx, (qid, start_page, start_y) in enumerate(matches):
        # Determine end point
        if idx + 1 < len(matches):
            end_page, end_y = matches[idx + 1][1], matches[idx + 1][2]
        else:
            # Last question — extend to footer of last content page
            end_page = total_pages - 1
            end_y = footer_y

        clips: list[PageClip] = []

        if start_page == end_page:
            clips.append(PageClip(
                page_idx=start_page,
                y_top=start_y,
                y_bottom=end_y,
            ))
        else:
            # First page: start_y → footer
            clips.append(PageClip(
                page_idx=start_page,
                y_top=start_y,
                y_bottom=footer_y,
            ))
            # Intermediate full pages
            for pg in range(start_page + 1, end_page):
                clips.append(PageClip(
                    page_idx=pg,
                    y_top=top_margin,
                    y_bottom=footer_y,
                ))
            # Last page: top_margin → end_y
            clips.append(PageClip(
                page_idx=end_page,
                y_top=top_margin,
                y_bottom=end_y,
            ))

        regions.append(QuestionRegion(question_id=qid, clips=clips))

    return regions


# ── Public API ────────────────────────────────────────────────────

def segment_questions(
    doc: fitz.Document,
    question_ids: list[str],
    *,
    skip_pages: set[int] | None = None,
) -> list[QuestionRegion]:
    """Detect question boundaries and return cropping regions.

    Args:
        doc: Opened PyMuPDF document (question paper or GoodNotes export).
        question_ids: Ordered list from PaperConfig.questions.keys().
        skip_pages: 0-indexed pages to skip (e.g. cover page).
                    Defaults to {0} (skip first page).

    Returns:
        List of QuestionRegion, one per matched question.
        May be shorter than question_ids if detection is partial.
    """
    if skip_pages is None:
        skip_pages = {0}

    boundaries = _extract_boundaries(doc, skip_pages=skip_pages)
    if not boundaries:
        return []

    fmt = _detect_format(doc[0])
    params = _FORMAT_PARAMS[fmt]

    matches = _match_boundaries(boundaries, question_ids)
    return _build_regions(matches, doc, params["footer_y"], params["top_margin"])


def validate_regions(
    regions: list[QuestionRegion],
    question_ids: list[str],
) -> tuple[list[str], list[str]]:
    """Check which questions were matched.

    Returns:
        (matched_ids, unmatched_ids)
    """
    matched = {r.question_id for r in regions}
    matched_list = [q for q in question_ids if q in matched]
    unmatched_list = [q for q in question_ids if q not in matched]
    return matched_list, unmatched_list
