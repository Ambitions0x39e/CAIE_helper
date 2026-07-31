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


# Boundaries on the same line must sort outermost-first: an inline
# "1 (a) (i)" row has to parent as MAIN → SUB → SUBSUB. This used to be an
# accident of the order the classification loops appended in; making it
# explicit keeps grouping correct no matter which loop emits what.
_KIND_RANK: dict[_BoundaryKind, int] = {
    _BoundaryKind.MAIN: 0,
    _BoundaryKind.SUB: 1,
    _BoundaryKind.SUBSUB: 2,
}


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


# A paper is either CID-encoded throughout or readable throughout; measured
# ratios cluster at the extremes (9701 92.8%, 9702 72.6-100%, 9231 100% vs
# 9700 2.3%, 9618 0.2%, 9231/s23 0%), so any mid-range cut works.
_CID_RATIO_THRESHOLD = 0.5


def _is_cid_encoded(pages: list[_SegPage], skip: set[int]) -> bool:
    """Whether the paper's text is in a custom CID font rather than readable.

    This is what decides whether the garbled-marker detection path applies at
    all, so it is measured over the pages the segmenter actually scans — a
    readable cover page in front of a garbled body must not sway the verdict.
    """
    total = 0
    cid = 0
    for pg_idx, page in enumerate(pages):
        if pg_idx in skip:
            continue
        for w in page.words:
            if not w.text.strip():
                continue
            total += 1
            if _CID_RE.search(w.text):
                cid += 1
    return total > 0 and cid / total >= _CID_RATIO_THRESHOLD


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


def _accepted_garbled_subs(
    per_page: list[
        tuple[int, list[dict[str, Any]], list[dict[str, Any]],
              list[dict[str, Any]], dict[float, list[dict[str, Any]]]]
    ],
    bracket_pair: tuple[int, int] | None,
    lx: float,
) -> dict[int, list[tuple[float, int]]]:
    """Find garbled sub-part markers "(a)/(b)/(c)" at the sub-question column.

    Independent of the left margin: a span already collected into
    ``sub_q_spans`` (x ≈ sub_q_x) is accepted as a SUB when

    1. it is bracket-shaped in the paper's own encoding — ``cps[0]`` is the
       open glyph and ``cps[2]`` is the close glyph. The label often has a
       trailing space/text glued on (measured on 9702: ``(a)`` is
       ``[240, 35, 241, 5]``), so the marker is identified by the closing
       bracket at index 2, not by the token length; and
    2. nothing but the main-question number sits to its left on that line.
       The first sub-part of each question shares its line with the number
       (``2 (a)``) at the left-margin column ``lx``; that companion is
       expected and ignored. Body text indented to this column with a real
       word to its left is rejected; and
    3. its middle codepoint (the letter glyph) occurs >= 2 times across the
       document. A real "(a)/(b)/(c)" repeats once per question; a
       coincidental bracket shape in body text does not.

    Returns ``{page_idx: [(y0, middle_cp), ...]}`` ordered by (page, y).
    Empty when the paper is readable-text (``bracket_pair is None``) —
    the readable path handles those.
    """
    if bracket_pair is None:
        return {}

    open_cp, close_cp = bracket_pair

    candidates: list[tuple[int, float, int]] = []  # (page, y, middle_cp)
    for pg_idx, _left_spans, sub_q_spans, _ss, spans_at_y in per_page:
        for span in sub_q_spans:
            cps = span.get("cps") or _parse_codepoints(span["text"])
            if len(cps) < 3 or cps[0] != open_cp or cps[2] != close_cp:
                continue
            # Reject only if a genuine word (not the left-margin question
            # number) sits to the marker's left on the same line.
            y0 = span["y0"]
            preempted = any(
                o["x0"] < span["x0"] - _X_TOLERANCE
                and abs(o["x0"] - lx) > _X_TOLERANCE
                for o in spans_at_y.get(y0, [])
            )
            if preempted:
                continue
            candidates.append((pg_idx, y0, cps[1]))

    # Keep only middle glyphs seen >= 2 times — real letters recur once per
    # question, a coincidental bracket shape in body text does not.
    from collections import Counter, defaultdict
    glyph_freq = Counter(mid for _p, _y, mid in candidates)
    trusted = {g for g, n in glyph_freq.items() if n >= 2}

    result: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for pg_idx, y0, mid in candidates:
        if mid in trusted:
            result[pg_idx].append((y0, mid))
    for pg_idx in result:
        result[pg_idx].sort()
    return dict(result)


def _accepted_garbled_subsubs(
    per_page: list[
        tuple[int, list[dict[str, Any]], list[dict[str, Any]],
              list[dict[str, Any]], dict[float, list[dict[str, Any]]]]
    ],
    bracket_pair: tuple[int, int] | None,
) -> dict[int, list[float]]:
    """Find garbled roman sub-sub markers "(i)/(ii)/(iii)" at subsub_q_x.

    Roman numerals in a CID font are built by repeating one glyph: on 9702
    "(i)" is ``[240, 38, 241, 5]`` and "(ii)"/"(iii)" repeat glyph 38.
    A marker is accepted when

    1. it opens and closes with the paper's bracket pair, and
    2. every interior codepoint belongs to the roman-glyph set — the few
       most frequent interior glyphs of the bare 3-codepoint "(x)" tokens.
       Body text indented to this column (e.g. a wrapped line) has interior
       glyphs outside that tiny set and is rejected.

    The numeral value is never decoded: _match_boundaries pairs romans to
    their sub-sub IDs positionally, so only the ordered y-positions matter.
    Returns ``{page_idx: [y0, ...]}``; empty for readable papers.
    """
    if bracket_pair is None:
        return {}

    open_cp, close_cp = bracket_pair

    # Pass 1: collect bracket-shaped candidates at the sub-sub column.
    # Like the sub markers, a trailing space/text glyph is often glued on
    # ("(i)" is [240, 38, 241, 5]), so the closing bracket is found by
    # value, not at the last index; interior is between the two brackets.
    raw: list[tuple[int, float, list[int]]] = []  # (page, y, interior cps)
    for pg_idx, _ls, _sq, subsub_spans, _sat in per_page:
        for span in subsub_spans:
            cps = span.get("cps") or _parse_codepoints(span["text"])
            if len(cps) < 3 or cps[0] != open_cp or close_cp not in cps[1:]:
                continue
            close_i = cps.index(close_cp, 1)
            interior = cps[1:close_i]
            if interior:
                raw.append((pg_idx, span["y0"], interior))

    # Pass 2: learn the roman alphabet. Roman numerals in the range CIE uses
    # are spelled from at most three glyphs — i, v, x — so the alphabet is
    # tiny, and a glyph earns its place two ways:
    #
    #   * it IS a whole single-glyph interior — that is the "i" glyph, named
    #     unambiguously by the bare "(i)" marker; or
    #   * it recurs across markers — "v" only ever shows up inside "(iv)" /
    #     "(vi)", never alone, so it cannot be learned from singles (on 9701
    #     that lost every "(iv)" in the paper). Requiring recurrence still
    #     rejects one-off body-text glyphs, which do not repeat.
    from collections import Counter, defaultdict
    singles = Counter(
        interior[0] for _p, _y, interior in raw if len(interior) == 1
    )
    glyph_freq = Counter(g for _p, _y, interior in raw for g in interior)
    candidates = set(singles) | {g for g, n in glyph_freq.items() if n >= 2}
    roman_glyphs = set(
        sorted(candidates, key=lambda g: -glyph_freq[g])[:3]
    )
    if not roman_glyphs:
        return {}

    result: dict[int, list[float]] = defaultdict(list)
    for pg_idx, y0, interior in raw:
        if interior and all(cp in roman_glyphs for cp in interior):
            result[pg_idx].append(y0)
    for pg_idx in result:
        result[pg_idx].sort()
    return dict(result)


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

    # Auto-detect the bracket encoding. On a READABLE paper the real
    # parens are ASCII 40/41 and _detect_bracket_pair instead latches onto
    # a noise pair of ordinary letter codepoints (measured on 9700:
    # (70,103) = 'F','g'), which then injects phantom SUBs that displace
    # the genuine readable-text ones. So the pair must be gated — but on
    # whether the PAPER is garbled, not on the pair's codepoint values: a
    # custom encoding is free to place its bracket glyphs in low bytes, and
    # 9701 chemistry does exactly that ((113,114)). Gating on magnitude threw
    # the real pair away and with it every sub-part boundary on the paper.
    garbled_page_data = [
        (pg_idx, ls, sy) for pg_idx, ls, _, _, sy in per_page
    ]
    bracket_pair = _detect_bracket_pair(garbled_page_data, sqx)
    if bracket_pair is not None and not _is_cid_encoded(pages, skip):
        bracket_pair = None

    # Garbled sub-part markers, detected independently of the left margin.
    # The original garbled path only ran for rows that also carried a
    # 1-codepoint left-margin span, which in a real paper is only the row
    # holding the main question number — so "(b)"/"(c)" were never seen.
    accepted_subs = _accepted_garbled_subs(per_page, bracket_pair, lx)
    # Roman sub-sub markers "(i)/(ii)/(iii)" in the garbled font — the
    # readable-text SUBSUB path below can't decode them (raw text is
    # "(cid:..)" not "(i)").
    accepted_subsubs = _accepted_garbled_subsubs(per_page, bracket_pair)

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

        # --- Garbled SUB detection: bracket-shaped markers at x≈sub_q_x ---
        for y0, _cp in accepted_subs.get(pg_idx, []):
            boundaries.append(_Boundary(
                kind=_BoundaryKind.SUB, page_idx=pg_idx, y=y0,
            ))

        # --- Garbled SUBSUB detection: "(i)/(ii)/(iii)" at x≈subsub_q_x ---
        for y0 in accepted_subsubs.get(pg_idx, []):
            boundaries.append(_Boundary(
                kind=_BoundaryKind.SUBSUB, page_idx=pg_idx, y=y0,
            ))

        # --- Readable SUBSUB detection: "(i)", "(ii)", … at x≈subsub_q_x ---
        # Only fires on readable-text papers; the garbled path above covers
        # CID-encoded ones.
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

    boundaries.sort(key=lambda b: (b.page_idx, b.y, _KIND_RANK[b.kind]))
    boundaries = _dedupe_boundaries(boundaries)
    return _reconcile_main_numbers(boundaries)


def _dedupe_boundaries(boundaries: list[_Boundary]) -> list[_Boundary]:
    """Collapse boundaries of the same kind at the same (page, ~y).

    The garbled companion path and the new sub-column path can both emit a
    SUB for the same marker; a MAIN and SUB at one coordinate must stay
    distinct. Keys on kind + page + rounded y, keeping the first (already
    sorted by kind rank).
    """
    seen: set[tuple[int, int, float]] = set()
    out: list[_Boundary] = []
    for b in boundaries:
        key = (_KIND_RANK[b.kind], b.page_idx, round(b.y, 1))
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def _reconcile_main_numbers(
    boundaries: list[_Boundary],
) -> list[_Boundary]:
    """Resolve MAIN boundaries whose question number could not be decoded.

    A 2-codepoint left-margin span is emitted as MAIN even when the char
    map cannot decode it. Keeping it with ``question_num=None`` is worse
    than dropping it: ``_match_boundaries`` can never look it up by number,
    yet ``_group_boundaries`` still lets it adopt the SUB boundaries that
    follow — stealing them from the real question. (Measured on 9702_s25:
    one such phantom sat between Q1 and Q2 and took one of Q1's subs.)

    Decoded numbers form a sparse increasing sequence, so an undecoded MAIN
    is promoted only when it is the lone candidate in a gap of exactly one;
    otherwise it is dropped rather than left to corrupt grouping.
    """
    mains = [
        (i, b) for i, b in enumerate(boundaries)
        if b.kind == _BoundaryKind.MAIN
    ]
    if not any(b.question_num is None for _, b in mains):
        return boundaries
    if not any(b.question_num is not None for _, b in mains):
        # Nothing decoded at all (readable-text papers with no page-number
        # char map, synthetic test PDFs). There is no sequence to reconcile
        # against, and _match_boundaries falls back to positional matching
        # in exactly this case — leave the boundaries alone.
        return boundaries

    def prev_decoded(pos: int) -> int:
        for p in range(pos - 1, -1, -1):
            num = mains[p][1].question_num
            if num is not None:
                return num
        return 0

    def next_decoded(pos: int) -> int | None:
        for n in range(pos + 1, len(mains)):
            num = mains[n][1].question_num
            if num is not None:
                return num
        return None

    drop: set[int] = set()
    for pos, (idx, b) in enumerate(mains):
        if b.question_num is not None:
            continue

        prev_num = prev_decoded(pos)
        next_num = next_decoded(pos)
        # Undecoded MAINs sharing this pair of decoded anchors.
        run = sum(
            1 for p, (_, ob) in enumerate(mains)
            if ob.question_num is None and prev_decoded(p) == prev_num
        )
        gap = (next_num - prev_num - 1) if next_num is not None else 1

        if run == 1 and gap == 1:
            b.question_num = prev_num + 1
        else:
            drop.add(idx)

    return [b for i, b in enumerate(boundaries) if i not in drop]


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

            # More SUBSUBs than the mark scheme has romans for this letter
            # means the detector over-fired. Blind positional indexing would
            # then shift every roman crop by one — a wrong crop, worse than a
            # coarse one. Distrust the tier for this letter and fall back to
            # the letter's own boundary.
            if len(subsub_bs) > len(romans):
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
            # The letter carries its own stem between its (b) marker and its
            # first roman — the same relationship a MAIN has with its first
            # sub-part (see the pull-back below). Anchoring the first roman
            # at its own marker would push that stem into the PREVIOUS
            # question's crop, so anchor it at the letter's marker instead.
            # (When the prepend above fired, positions[0] is already sub_b.)
            if idx == 0:
                matches.append((qid, sub_b.page_idx, sub_b.y))
            elif idx < len(positions):
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
