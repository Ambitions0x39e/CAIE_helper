# modules/page_segmenter.py
"""Auto-detect question boundaries in CIE answer papers using PDF text positions.

CIE PDFs use custom font encoding (text is garbled), but span coordinates are
precise.  Question numbers appear at fixed X positions:
  - Main question numbers (1, 2, …) at x ≈ 72.4 with len == 2
  - Sub-question labels (a), (b), … at x ≈ 93.7 starting with byte 0xa8
  - Roman-numeral sub-sub-parts (i), (ii), … at x ≈ 112 (readable text only —
    garbled-font decoding isn't implemented for this tier)

This module detects those positions and maps them to the ordered question IDs
from the parsed mark scheme, producing clip rectangles for cropped rendering.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import (
    LAParams,
    LTChar,
    LTContainer,
    LTCurve,
    LTLine,
    LTRect,
    LTTextLine,
)
from pydantic import BaseModel

# ── Neutral page model (pdfminer.six-backed) ──────────────────────


@dataclass(frozen=True)
class _SegWord:
    """One word with pdfplumber-compatible geometry.

    text may contain garbled ``(cid:N)`` glyphs — passed to
    :func:`_parse_codepoints` unchanged. Coordinates are in points:
    ``x0`` from the page left, ``top`` from the page top.
    """

    text: str
    x0: float
    top: float


@dataclass(frozen=True)
class _SegPage:
    """One PDF page reduced to just what the segmenter needs."""

    width: float
    height: float
    words: list[_SegWord]
    has_curves: bool


def _line_to_words(line: LTTextLine, page_height: float) -> list[_SegWord]:
    """Group a pdfminer text line's chars into words on whitespace.

    x0 = min char left edge; top = page_height - max char top edge
    (pdfminer is bottom-left origin; pdfplumber ``top`` is from the top).
    """
    words: list[_SegWord] = []
    current: list[LTChar] = []

    def flush() -> None:
        if current:
            words.append(
                _SegWord(
                    text="".join(c.get_text() for c in current),
                    x0=min(c.x0 for c in current),
                    top=page_height - max(c.y1 for c in current),
                )
            )
            current.clear()

    for obj in line:
        if isinstance(obj, LTChar) and not obj.get_text().isspace():
            current.append(obj)
        else:  # LTAnno or whitespace LTChar → word boundary
            flush()
    flush()
    return words


def _collect(
    container: LTContainer,  # type: ignore[type-arg]
    page_height: float,
    words: list[_SegWord],
    curve_flag: list[bool],
) -> None:
    """Recursively gather words and detect bezier-curve content."""
    for element in container:
        if isinstance(element, LTTextLine):
            words.extend(_line_to_words(element, page_height))
        elif isinstance(element, LTCurve) and not isinstance(
            element, LTLine | LTRect
        ):
            curve_flag[0] = True
        elif isinstance(element, LTContainer):
            _collect(element, page_height, words, curve_flag)


def _load_pages(source: str | bytes) -> list[_SegPage]:
    """Load a PDF (path or raw bytes) into neutral pages via pdfminer.six."""
    laparams = LAParams()
    if isinstance(source, bytes):
        layouts = list(extract_pages(io.BytesIO(source), laparams=laparams))
    else:
        with open(source, "rb") as fh:
            layouts = list(extract_pages(fh, laparams=laparams))

    pages: list[_SegPage] = []
    for layout in layouts:
        height = float(layout.height)
        words: list[_SegWord] = []
        curve_flag = [False]
        _collect(layout, height, words, curve_flag)
        pages.append(
            _SegPage(
                width=float(layout.width),
                height=height,
                words=words,
                has_curves=curve_flag[0],
            )
        )
    return pages


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


class SegmentationReport(BaseModel):
    """Why segmentation matched what it did.

    Detection failures used to be invisible: a question whose boundaries
    collapsed to a zero-height span still produced a ``QuestionRegion``
    (with no clips) and still counted as "matched", so the UI reported
    full success while nothing was actually croppable. This report makes
    the shortfall explicit so callers can tell the user which questions
    need manual page numbers.
    """
    matched: list[str] = []
    unmatched: list[str] = []
    # question_id → why it produced no usable region
    reasons: dict[str, str] = {}
    # Detection diagnostics, for debugging a paper that segments badly.
    main_count: int = 0
    sub_count: int = 0
    subsub_count: int = 0
    bracket_pair_found: bool = False
    char_map_size: int = 0


# Reasons recorded in SegmentationReport.reasons
_REASON_DEGENERATE = "degenerate"      # boundaries collapsed to ~zero height
_REASON_OUT_OF_ORDER = "out_of_order"  # next boundary sits above this one


# ── Internal types ────────────────────────────────────────────────

class _BoundaryKind(StrEnum):
    MAIN = "main"
    SUB = "sub"
    SUBSUB = "subsub"


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
        "subsub_q_x": 112.0,
        "footer_y": 740.0,
        "top_margin": 45.0,
    },
    "a4": {
        "left_margin_x": 70.0,
        "sub_q_x": 91.0,
        "subsub_q_x": 109.3,
        "footer_y": 790.0,
        "top_margin": 45.0,
    },
}

_X_TOLERANCE = 3.0
# Roman-numeral sub-sub-part markers ("(ii)", "(iii)", …) are indented
# further than letter markers but their exact x0 varies more (~±6pt)
# due to kerning/rounding noise — use a wider tolerance for this tier.
_SUBSUB_X_TOLERANCE = 6.0
_ROMAN_NUMERALS = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
}

_CID_RE = re.compile(r"\(cid:(\d+)\)")


def _parse_codepoints(text: str) -> list[int]:
    """Extract integer code points from word text.

    pdfplumber renders garbled CID fonts as ``(cid:N)`` strings.
    fitz returned raw bytes whose ``ord()`` gave the code point directly.
    This helper unifies both representations into a list of ints so all
    downstream length / value checks work identically.
    """
    cids = _CID_RE.findall(text)
    if cids:
        return [int(c) for c in cids]
    return [ord(c) for c in text]


def _detect_format(page: _SegPage) -> str:
    w = page.width
    if abs(w - 595) < 10:
        return "a4"
    return "letter"


# ── Bracket-pair auto-detection ──────────────────────────────────

def _detect_bracket_pair(
    per_page: list[tuple[int, list[dict[str, Any]], dict[float, list[dict[str, Any]]]]],
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
                    cps = c.get("cps") or _parse_codepoints(c["text"])
                    pair_counts[(cps[0], cps[2])] += 1

    if not pair_counts:
        return None

    best_pair, count = pair_counts.most_common(1)[0]
    if count >= 2:
        return best_pair
    return None


# ── Character mapping (garbled font decoding) ────────────────────

def _build_char_mapping(
    pages: list[_SegPage],
) -> dict[int, str] | None:
    """Build byte→digit mapping from page number spans.

    CIE garbled PDFs use the same 'AllAndNone' font for page numbers and
    question numbers.  Since we know each page's printed number (pg N in
    the PDF shows page N+1), we can reverse-engineer the byte→digit table
    and reuse it to decode question numbers.

    Returns None if the PDF uses readable text (no mapping needed).
    """
    pw = pages[0].width
    center_x = pw / 2

    page_num_spans: list[tuple[int, list[int]]] = []
    for pg_idx, page in enumerate(pages):
        for w in page.words:
            text = w.text.strip()
            if not text:
                continue
            if w.top < 50 and abs(w.x0 - center_x) < 100:
                if _is_ascii_digit_str(text):
                    return None
                cps = _parse_codepoints(text)
                page_num_spans.append((pg_idx, cps))

    if not page_num_spans:
        return None

    page_num_spans.sort()
    mapping: dict[int, str] = {}
    for pg_idx, cps in page_num_spans:
        expected = str(pg_idx + 1)
        if len(cps) != len(expected):
            continue
        for cp, digit in zip(cps, expected, strict=True):
            if cp in mapping and mapping[cp] != digit:
                continue
            mapping[cp] = digit

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

    cps = _parse_codepoints(text)
    if not cps or cps[0] not in mapping:
        return None
    result = mapping[cps[0]]

    if len(cps) >= 2 and cps[1] in mapping:
        result += mapping[cps[1]]

    return int(result) if result.isdigit() else None


# ── Boundary detection ────────────────────────────────────────────

def _extract_boundaries(
    pages: list[_SegPage],
    *,
    skip_pages: set[int] | None = None,
) -> list[_Boundary]:
    """Scan every page and return ordered question-start boundaries."""
    if not pages:
        return []

    fmt = _detect_format(pages[0])
    params = _FORMAT_PARAMS[fmt]
    lx = params["left_margin_x"]
    sqx = params["sub_q_x"]
    ssqx = params["subsub_q_x"]
    footer_y = params["footer_y"]
    skip = skip_pages or set()

    char_map = _build_char_mapping(pages)

    _WordDict = dict[str, Any]

    # First pass: collect word data from all pages
    per_page: list[
        tuple[
            int, list[_WordDict], list[_WordDict], list[_WordDict],
            dict[float, list[_WordDict]],
        ]
    ] = []

    for pg_idx, page in enumerate(pages):
        if pg_idx in skip:
            continue

        spans_at_y: dict[float, list[dict[str, Any]]] = {}
        left_spans: list[dict[str, Any]] = []
        sub_q_spans: list[dict[str, Any]] = []
        subsub_q_spans: list[dict[str, Any]] = []

        for w in page.words:
            text = w.text.strip()
            if not text:
                continue
            x0 = w.x0
            y0 = round(w.top, 1)
            cps = _parse_codepoints(text)
            cp_len = len(cps)

            entry = {
                "x0": x0, "y0": y0, "text": text,
                "len": cp_len, "cps": cps,
            }

            if y0 not in spans_at_y:
                spans_at_y[y0] = []
            spans_at_y[y0].append(entry)

            if y0 < footer_y:
                if abs(x0 - lx) < _X_TOLERANCE and cp_len <= 2:
                    left_spans.append(entry)
                if abs(x0 - sqx) < _X_TOLERANCE and cp_len >= 3:
                    sub_q_spans.append(entry)
                if abs(x0 - ssqx) < _SUBSUB_X_TOLERANCE and 3 <= cp_len <= 6:
                    subsub_q_spans.append(entry)

        per_page.append(
            (pg_idx, left_spans, sub_q_spans, subsub_q_spans, spans_at_y)
        )

    # Auto-detect the bracket encoding for this paper (garbled format)
    garbled_page_data = [
        (pg_idx, ls, sy) for pg_idx, ls, _, _, sy in per_page
    ]
    bracket_pair = _detect_bracket_pair(garbled_page_data, sqx)

    # Second pass: classify boundaries
    boundaries: list[_Boundary] = []

    for pg_idx, left_spans, sub_q_spans, subsub_q_spans, spans_at_y in per_page:
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
                # 2-char span: always a MAIN boundary (positional fallback works
                # even when qnum cannot be decoded from the char map).
                qnum = _decode_question_num(text, char_map)
                boundaries.append(_Boundary(
                    kind=_BoundaryKind.MAIN, page_idx=pg_idx, y=y0,
                    question_num=qnum,
                ))
            elif span["len"] == 1:
                # 1-char span: either a SUB marker (paired with a bracket-pair
                # companion at sub_q_x) or a single-digit garbled MAIN question
                # number (Q1-Q9). Check SUB first — a companion match is a
                # structural signal, whereas a char-map decode can coincidentally
                # collide with an unrelated page-number byte and give a false
                # positive MAIN classification.
                matched_sub = False
                if bracket_pair is not None:
                    companions = spans_at_y.get(y0, [])
                    for c in companions:
                        if abs(c["x0"] - sqx) < _X_TOLERANCE and c["len"] >= 3:
                            c_cps = c.get("cps") or _parse_codepoints(c["text"])
                            if (c_cps[0], c_cps[2]) == bracket_pair:
                                boundaries.append(_Boundary(
                                    kind=_BoundaryKind.SUB, page_idx=pg_idx, y=y0,
                                ))
                                matched_sub = True
                                break
                if not matched_sub:
                    qnum = _decode_question_num(text, char_map)
                    if qnum is not None:
                        boundaries.append(_Boundary(
                            kind=_BoundaryKind.MAIN, page_idx=pg_idx, y=y0,
                            question_num=qnum,
                        ))

        # --- Readable SUB detection: "(a)", "(b)" directly at x≈sub_q_x ---
        for span in sub_q_spans:
            cps = span.get("cps") or _parse_codepoints(span["text"])
            if (
                len(cps) >= 3
                and cps[0] == ord("(")
                and cps[2] == ord(")")
                and chr(cps[1]).isalpha()
            ):
                boundaries.append(_Boundary(
                    kind=_BoundaryKind.SUB, page_idx=pg_idx, y=span["y0"],
                ))

        # --- Readable SUBSUB detection: "(i)", "(ii)", … at x≈subsub_q_x ---
        # Garbled-font papers aren't supported here (no bracket-pair-style
        # decoding exists for this tier yet) — only readable text is matched.
        for span in subsub_q_spans:
            text = span["text"]
            if (
                len(text) >= 3
                and text[0] == "("
                and text[-1] == ")"
                and text[1:-1] in _ROMAN_NUMERALS
            ):
                boundaries.append(_Boundary(
                    kind=_BoundaryKind.SUBSUB, page_idx=pg_idx, y=span["y0"],
                ))

    boundaries.sort(key=lambda b: (b.page_idx, b.y))
    return boundaries


# ── Match boundaries to question IDs ──────────────────────────────

def _has_sub_letter(qid: str) -> bool:
    """Check if a question ID has a sub-part letter (e.g. 1a, 1(a), 6(a)(ii))."""
    return bool(re.search(r"[a-z]|[ivx]+\)", qid))


def _extract_sub_letter(qid: str) -> str | None:
    """Extract the first sub-part letter from a question ID.

    "1a" → "a", "Q6(a)(ii)" → "a", "1(b)" → "b", "1" → None
    """
    m = re.search(r"(\d)\(?([a-z])\)?", qid)
    return m.group(2) if m else None


_ROMAN_SUFFIX_RE = re.compile(r"\(([ivx]+)\)\s*$")


def _extract_sub_roman(qid: str) -> str | None:
    """Extract the trailing roman-numeral sub-sub-part from a question ID.

    "Q6(a)(ii)" → "ii", "1a" → None, "1(b)" → None
    """
    m = _ROMAN_SUFFIX_RE.search(qid)
    return m.group(1) if m and m.group(1) in _ROMAN_NUMERALS else None


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


_SubGroup = tuple[_Boundary, list[_Boundary]]


def _group_boundaries(
    boundaries: list[_Boundary],
) -> list[tuple[_Boundary, list[_SubGroup]]]:
    """Group boundaries into (MAIN, [(SUB, [SUBSUBs]), ...]) tuples."""
    groups: list[tuple[_Boundary, list[_SubGroup]]] = []
    for b in boundaries:
        if b.kind == _BoundaryKind.MAIN:
            groups.append((b, []))
        elif b.kind == _BoundaryKind.SUB and groups:
            groups[-1][1].append((b, []))
        elif (
            b.kind == _BoundaryKind.SUBSUB
            and groups
            and groups[-1][1]
        ):
            groups[-1][1][-1][1].append(b)
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

    b_by_num: dict[int, tuple[_Boundary, list[_SubGroup]]] | None = None
    if has_nums:
        b_by_num = {}
        for main_b, sub_groups in b_groups:
            if main_b.question_num is not None:
                b_by_num[main_b.question_num] = (main_b, sub_groups)

    matches: list[tuple[str, int, float]] = []

    for g_idx, qids in enumerate(q_groups):
        main_num = int(_extract_main_num(qids[0]))

        if b_by_num is not None:
            group = b_by_num.get(main_num)
        else:
            group = b_groups[g_idx] if g_idx < len(b_groups) else None

        if group is None:
            continue

        main_b, sub_groups = group

        if not sub_groups or not _has_sub_letter(qids[0]):
            matches.append((qids[0], main_b.page_idx, main_b.y))
            continue

        unique_letters: list[str] = []
        for qid in qids:
            letter = _extract_sub_letter(qid)
            if letter and letter not in unique_letters:
                unique_letters.append(letter)

        letter_group: dict[str, _SubGroup] = {
            letter: sg
            for letter, sg in zip(unique_letters, sub_groups, strict=False)
        }

        # Precompute each letter's ordered roman-suffixed qids so nested
        # sub-sub-parts ("(a)(i)", "(a)(ii)", …) can be positionally
        # matched to their detected SUBSUB boundaries.
        romans_by_letter: dict[str, list[str]] = {}
        for qid in qids:
            letter = _extract_sub_letter(qid)
            if letter and _extract_sub_roman(qid):
                romans_by_letter.setdefault(letter, []).append(qid)

        group_start = len(matches)

        for qid in qids:
            letter = _extract_sub_letter(qid)
            if not letter or letter not in letter_group:
                matches.append((qid, main_b.page_idx, main_b.y))
                continue

            sub_b, subsub_bs = letter_group[letter]
            roman = _extract_sub_roman(qid)
            romans = romans_by_letter.get(letter, [])

            if not roman or not subsub_bs or qid not in romans:
                matches.append((qid, sub_b.page_idx, sub_b.y))
                continue

            # The first roman sub-part is often inline with its letter
            # marker ("(a) (i) ...") and shares its x-position, so it
            # rarely gets detected as its own SUBSUB boundary. If exactly
            # one fewer SUBSUB was detected than there are romans, assume
            # the missing one is the first and anchor it to the letter's
            # own boundary instead.
            positions = subsub_bs
            if len(subsub_bs) == len(romans) - 1:
                positions = [sub_b, *subsub_bs]

            idx = romans.index(qid)
            if idx < len(positions):
                ssb = positions[idx]
                matches.append((qid, ssb.page_idx, ssb.y))
            else:
                matches.append((qid, sub_b.page_idx, sub_b.y))

        # The question stem (intro text, diagrams) sits between the MAIN
        # marker and the first sub-part's own (a)/(i) marker. Regions end
        # where the next one starts, so anchoring the group's first
        # sub-part at its own marker would push the stem into the
        # PREVIOUS question's crop and lose it from this one. Pull the
        # first match back to the MAIN boundary instead.
        if len(matches) > group_start:
            first_qid = matches[group_start][0]
            matches[group_start] = (first_qid, main_b.page_idx, main_b.y)

    return matches


# ── Convert matches to regions ────────────────────────────────────

def _find_last_content_page(pages: list[_SegPage], after: int = 0) -> int:
    """Find the last page with actual content (curves in drawings).

    Pages after all questions (e.g. "Additional page") contain only
    dotted lines (straight-line drawings, 0 curves).  Scan backwards
    from the end of the document to find the last page that still has
    bezier curve content.
    """
    for i in range(len(pages) - 1, after - 1, -1):
        if pages[i].has_curves:
            return i
    return after


_MIN_CLIP_HEIGHT = 20.0


def _build_regions(
    matches: list[tuple[str, int, float]],
    page_count: int,
    footer_y: float,
    top_margin: float,
    *,
    last_content_page: int | None = None,
    reasons: dict[str, str] | None = None,
) -> list[QuestionRegion]:
    """Convert (qid, page, y) tuples into QuestionRegion with PageClips.

    Never returns a region with no clips: a question whose span collapses
    is dropped and the reason recorded in ``reasons`` (when provided), so
    callers report it as unmatched instead of silently croppable-but-empty.
    """
    if not matches:
        return []

    max_page = last_content_page if last_content_page is not None else page_count - 1
    regions: list[QuestionRegion] = []

    for idx, (qid, start_page, start_y) in enumerate(matches):
        # Determine end point
        if idx + 1 < len(matches):
            end_page, end_y = matches[idx + 1][1], matches[idx + 1][2]
        else:
            end_page = max_page
            end_y = footer_y

        clips: list[PageClip] = []

        if start_page == end_page:
            # Two consecutive boundaries can land on (near) the same Y
            # coordinate (e.g. a mis-detected duplicate boundary, or a
            # sub-question with no content of its own). Skip degenerate
            # clips rather than emitting a zero/negative-height crop.
            delta = end_y - start_y
            if delta >= _MIN_CLIP_HEIGHT:
                clips.append(PageClip(
                    page_idx=start_page,
                    y_top=start_y,
                    y_bottom=end_y,
                ))
            elif reasons is not None:
                reasons[qid] = (
                    _REASON_OUT_OF_ORDER if delta < 0 else _REASON_DEGENERATE
                )
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
            # Last page: top_margin → end_y (skip if too small)
            if end_y - top_margin >= _MIN_CLIP_HEIGHT:
                clips.append(PageClip(
                    page_idx=end_page,
                    y_top=top_margin,
                    y_bottom=end_y,
                ))

        # A clip-less region is indistinguishable from "not found" for every
        # consumer, so don't manufacture one — drop it and let the caller
        # report the question as unmatched.
        if clips:
            regions.append(QuestionRegion(question_id=qid, clips=clips))
        elif reasons is not None:
            reasons.setdefault(qid, _REASON_DEGENERATE)

    return regions


# ── Public API ────────────────────────────────────────────────────

def segment_questions(
    source: str | bytes,
    question_ids: list[str],
    *,
    skip_pages: set[int] | None = None,
) -> list[QuestionRegion]:
    """Detect question boundaries and return cropping regions.

    Args:
        source: Path to, or raw bytes of, the PDF (question paper or
            GoodNotes export). Parsed with pdfminer.six (iOS-safe).
        question_ids: Ordered list from PaperConfig.questions.keys().
        skip_pages: 0-indexed pages to skip (e.g. cover page).
                    Defaults to {0} (skip first page).

    Returns:
        List of QuestionRegion, one per matched question.
        May be shorter than question_ids if detection is partial.
    """
    regions, _report = segment_questions_report(
        source, question_ids, skip_pages=skip_pages,
    )
    return regions


def segment_questions_report(
    source: str | bytes,
    question_ids: list[str],
    *,
    skip_pages: set[int] | None = None,
) -> tuple[list[QuestionRegion], SegmentationReport]:
    """Same as :func:`segment_questions`, plus a report on what failed.

    Use this when the caller needs to tell the user which questions could
    not be located — ``segment_questions`` alone cannot distinguish "not
    detected" from "detected but unusable".
    """
    if skip_pages is None:
        skip_pages = {0}

    pages = _load_pages(source)
    report = SegmentationReport(unmatched=list(question_ids))

    boundaries = _extract_boundaries(pages, skip_pages=skip_pages)
    report.main_count = sum(
        1 for b in boundaries if b.kind == _BoundaryKind.MAIN
    )
    report.sub_count = sum(
        1 for b in boundaries if b.kind == _BoundaryKind.SUB
    )
    report.subsub_count = sum(
        1 for b in boundaries if b.kind == _BoundaryKind.SUBSUB
    )
    char_map = _build_char_mapping(pages)
    report.char_map_size = len(char_map) if char_map else 0
    if not boundaries:
        return [], report

    fmt = _detect_format(pages[0])
    params = _FORMAT_PARAMS[fmt]

    last_boundary_page = max(b.page_idx for b in boundaries)
    last_content = _find_last_content_page(pages, after=last_boundary_page)

    matches = _match_boundaries(boundaries, question_ids)
    reasons: dict[str, str] = {}
    regions = _build_regions(
        matches, len(pages), params["footer_y"], params["top_margin"],
        last_content_page=last_content,
        reasons=reasons,
    )

    matched, unmatched = validate_regions(regions, question_ids)
    report.matched = matched
    report.unmatched = unmatched
    report.reasons = reasons
    return regions, report


def validate_regions(
    regions: list[QuestionRegion],
    question_ids: list[str],
) -> tuple[list[str], list[str]]:
    """Check which questions were matched.

    A region with no clips is NOT a match: nothing can be cropped or sent
    to the grader for it, so counting it as matched only hides the failure.

    Returns:
        (matched_ids, unmatched_ids)
    """
    matched = {r.question_id for r in regions if r.clips}
    matched_list = [q for q in question_ids if q in matched]
    unmatched_list = [q for q in question_ids if q not in matched]
    return matched_list, unmatched_list
