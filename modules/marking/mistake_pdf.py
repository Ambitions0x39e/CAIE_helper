"""Export mistakes as a PDF cut out of the original question papers.

The 错题本's CSV export answers "which topics do I lose marks on". This one
answers "let me redo those questions": each page carries one whole question,
cropped out of the QP it came from.

**Vector, not raster.** The regions are placed by stamping the source page
with its CropBox set to the band, which is what makes ``pypdf``'s merge emit
a clip rectangle around it. Nothing is rasterised, so the text stays real
text and the file stays small — and none of it needs the native pdfrx
renderer, so it works (and is testable) outside the packaged app.

Nothing here may import ``flet`` or ``app_flet``: the layout is arithmetic
and the composition is a file operation, both worth testing without a page.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import median
from typing import TYPE_CHECKING

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from core.models import MistakeRecord
    from modules.marking.page_segmenter import PageClip

#: Breathing room at the top and bottom of an output page.
_MARGIN = 24.0
#: Between two bands of the same question.
_GAP = 12.0

_MAIN_ID_RE = re.compile(r"^(Q?\d+)")


def main_question_id(question_id: str) -> str:
    """``"Q4b"`` → ``"Q4"``; the id itself when it has no number to split on.

    Sub-questions are cropped as part of their parent: a sub-question lifted
    out on its own usually loses the stem it depends on, and one page per
    whole question is what makes the export re-doable.
    """
    match = _MAIN_ID_RE.match(question_id.strip())
    return match.group(1) if match else question_id.strip()


def main_questions_by_paper(
    records: Iterable[MistakeRecord],
) -> dict[str, list[str]]:
    """paper_id → its main question ids, each once, in first-seen order."""
    grouped: dict[str, list[str]] = {}
    for record in records:
        ids = grouped.setdefault(record.paper_id, [])
        main = main_question_id(record.question_id)
        if main not in ids:
            ids.append(main)
    return grouped


@dataclass(frozen=True)
class Band:
    """One horizontal slice of a source page, in the segmenter's top-down
    coordinates (y grows downward from the page top).

    ``x_left``/``x_right`` narrow it to the writing column. Cropping the full
    page width drags in what CIE prints down the sides — the margin bar and
    the little registration marks — which is what made the crops look like
    scraps rather than questions.
    """

    page_idx: int
    y_top: float
    y_bottom: float
    x_left: float | None = None
    x_right: float | None = None

    @property
    def height(self) -> float:
        return self.y_bottom - self.y_top

    def with_column(self, left: float, right: float) -> Band:
        return Band(self.page_idx, self.y_top, self.y_bottom, left, right)

    def from_top(self, y_top: float) -> Band:
        return Band(
            self.page_idx, y_top, self.y_bottom, self.x_left, self.x_right
        )


@dataclass(frozen=True)
class Placement:
    """Where one band goes on an output page — ``y_top`` is top-down too."""

    band: Band
    y_top: float


@dataclass
class QuestionCrop:
    """One question to export, and where to find it."""

    paper_id: str
    question_id: str
    qp_path: str
    bands: list[Band] = field(default_factory=list)
    #: False when the answer space could not be found and the whole question
    #: region is being exported instead — see :func:`crops_for_paper`.
    trimmed: bool = True


def plan_pages(
    bands: Sequence[Band],
    page_height: float,
    *,
    margin: float = _MARGIN,
    gap: float = _GAP,
) -> list[list[Placement]]:
    """Stack the bands down the page, wrapping onto a new one when full.

    Wrapping rather than scaling: a shrunk question paper is harder to work
    on than one that runs over, and the caller asked for the original size.
    A band taller than a whole page still gets its own page — it is placed at
    the top and simply runs past the bottom margin, which beats dropping it.
    """
    pages: list[list[Placement]] = []
    current: list[Placement] = []
    cursor = margin
    usable = page_height - margin

    for band in bands:
        if current and cursor + band.height > usable:
            pages.append(current)
            current = []
            cursor = margin
        current.append(Placement(band=band, y_top=cursor))
        cursor += band.height + gap

    if current:
        pages.append(current)
    return pages


def crops_for_paper(
    paper_id: str, qp_path: str, wanted: Sequence[str]
) -> tuple[list[QuestionCrop], list[str]]:
    """Locate *wanted* main questions in a QP. Returns (crops, not found).

    Segments against **every** question the paper has, not just the wanted
    ones, then picks. Segmenting against a subset looks like it works and
    silently produces the wrong answer: a question's region runs to the next
    id it was told about, so asking for Q2 and Q4 out of a six-question paper
    hands back a "Q2" that swallows Q3 — measured on a real paper, nine pages
    of it.
    """
    from modules.marking.page_segmenter import match_scanned, scan_document

    doc = scan_document(qp_path)
    # The ids the *paper* has, read off the boundaries the scan found — not
    # 1..main_count, which is only the same thing while every number decodes.
    # When one doesn't, asking for 1..N both misses the numbers past the gap
    # and hands back a region that swallows the undetected question's pages.
    numbers = sorted({
        boundary.question_num
        for boundary in doc.boundaries
        if boundary.question_num is not None
    })
    every = [f"Q{n}" for n in numbers] or [
        f"Q{n}" for n in range(1, doc.main_count + 1)
    ]
    regions, _ = match_scanned(doc, every)
    by_id = {region.question_id: region for region in regions}
    column = document_column(qp_path)

    crops: list[QuestionCrop] = []
    missing: list[str] = []
    for question_id in wanted:
        region = by_id.get(_as_q(question_id))
        if region is None:
            missing.append(question_id)
            continue
        whole = clips_to_bands(region.clips)
        trimmed = content_bands(
            qp_path, whole, column, top_margin=doc.top_margin
        )
        kept = sum(b.height for b in trimmed)
        total = sum(b.height for b in whole)
        # Some papers embed their fonts with no ToUnicode map: pdfminer then
        # reports every glyph as "(cid:155)" and cannot even group them into
        # lines, so the rulings are indistinguishable from the question
        # (measured on 9709 s25 — 10k cid tokens, zero readable words). When
        # trimming changes nothing, say so and export the whole region rather
        # than pretend.
        if not trimmed or (total and kept / total > _TRIM_THRESHOLD):
            crops.append(QuestionCrop(
                paper_id, question_id, qp_path, whole, trimmed=False,
            ))
        else:
            crops.append(QuestionCrop(
                paper_id, question_id, qp_path, trimmed,
            ))
    return crops, missing


def _as_q(question_id: str) -> str:
    """``"4"`` and ``"Q4"`` are the same question; the segmenter says "Q4"."""
    stripped = question_id.strip()
    return stripped if stripped.startswith("Q") else f"Q{stripped}"


def clips_to_bands(clips: Iterable[PageClip]) -> list[Band]:
    """Segmenter clips → bands, in reading order."""
    return [
        Band(page_idx=c.page_idx, y_top=c.y_top, y_bottom=c.y_bottom)
        for c in sorted(clips, key=lambda c: (c.page_idx, c.y_top))
    ]


# ── Dropping the answer space ─────────────────────────────────────
#
# A question's region runs from its number to the next question's, which on a
# CIE paper is mostly blank ruled space to write in. Exporting that gives
# pages of dots; what is wanted is the question itself, stitched together.
#
# The ruling is *text*: rows of full stops (measured on a real paper — the
# tables and diagrams beside them are LTLine/LTCurve, which is why graphics
# count as content and these do not).

#: A line that is only dots/spaces, long enough not to be an ellipsis in
#: prose.
_DOT_LEADER_RE = re.compile(r"^[.·…\s]{8,}$")
#: How many identical glyphs make a line a ruling rather than words.
_REPEAT_RUN = 8
#: …and how much of the line they have to be.
_REPEAT_SHARE = 0.8
#: Graphics taller than this share of the page are furniture — the margin bar
#: CIE draws down the side of every page is 99% of it. A real diagram never
#: comes close.
_FURNITURE_RATIO = 0.7
#: Two ruling rows further apart than this are not the same block of answer
#: space, so the gap between them is not used to estimate the row pitch.
_MAX_PITCH = 60.0
#: Pitch to assume when a band holds a single ruling row and there is no
#: spacing to measure. Both papers measured here rule at 24.5pt.
_DEFAULT_PITCH = 24.5
#: Breathing room around a block, so glyphs are not flush with the crop edge.
_PAD = 3.0
#: An element grazing the edge of a region belongs to its neighbour. Without
#: this the page number, whose box ends a point below the region's top edge,
#: became a five-point band of its own on every page of pure answer space.
_INSIDE_RATIO = 0.6
#: Anything shorter than this holds nothing worth a crop.
_MIN_BAND = 6.0
#: Keep this much of the region and the trim achieved nothing worth claiming.
_TRIM_THRESHOLD = 0.9
#: A line that came out as an actual word rather than a run of glyph codes.
#: One of these on a page is enough to trust its text layer — the papers that
#: fail this produce *zero* across the whole document, not a few.
_READABLE_RE = re.compile(r"[A-Za-z]{3,}")
#: Breathing room on the right of the writing column.
_COLUMN_PAD = 6.0
#: A ruling position used by fewer than this share of a paper's rulings is
#: an oddity (the cover page's name line), not part of the template.
_EDGE_SHARE = 0.1
#: Column to fall back on when a paper rules nothing at all — a plain inset,
#: as a share of the page width.
_COLUMN_INSET = 0.1
#: Where a page's content starts, below the running head — both CIE formats
#: put it here, and it is what :class:`ScannedDocument` reports.
_TOP_MARGIN = 45.0
#: A question's first line, however tall the maths on it, is not taller than
#: this. Measured over 52 papers: a region top slices through something on
#: most of them, by at most 17pt — except three physics papers where a
#: full-page figure straddles it, at 68–85pt. Growing the crop that far
#: would drag in the end of the previous question, so past this the top is
#: left where the segmenter put it.
_MAX_LIFT = 36.0
#: Boxes that merely touch at an edge are not overlapping.
_TOUCH = 0.1
#: Text below this size is page furniture, not question content: the barcode
#: strips CIE prints at the top and bottom of every page come out at 4.7 and
#: 7.5pt against a 10.8pt body. Sizing it out beats guessing a header height
#: — the top barcode sits at y51-56 and the first question at y60, which is
#: too fine a margin to cut on.
_MIN_TEXT_SIZE = 8.0


def _is_filler(line: object) -> bool:
    """Is this text line answer-space ruling rather than something to read?

    Checked on the *glyphs*, not the decoded string. Half the papers embed
    their fonts without a ToUnicode map, so pdfminer reports every character
    as ``(cid:155)`` — on those, matching literal full stops finds nothing
    and the whole page reads as content (measured: 9709 s25 P3 came out at
    676pt of "content" per page, i.e. untrimmed). What a ruling really is,
    in any encoding, is one glyph repeated across the line.
    """
    from pdfminer.layout import LTChar

    text = line.get_text().strip()  # type: ignore[attr-defined]
    if not text:
        return True
    if _DOT_LEADER_RE.match(text):
        return True

    glyphs = [
        char.get_text()
        for char in line  # type: ignore[attr-defined]
        if isinstance(char, LTChar) and char.get_text().strip()
    ]
    if len(glyphs) < _REPEAT_RUN:
        return False
    # Dominant rather than sole: a ruling often opens with a different glyph
    # (a leader's first stop is drawn from another slot), and one stray
    # character must not make a line of two hundred dots read as prose.
    most_common = max(Counter(glyphs).values())
    return most_common >= _REPEAT_RUN and (
        most_common / len(glyphs) >= _REPEAT_SHARE
    )


def _content_spans(
    layout: object, y_top: float, y_bottom: float, page_height: float
) -> tuple[list[_Span], list[_Span], int]:
    """(content, filler, readable) — spans top-down, plus a legibility count.

    The filler spans are kept, not discarded: where a ruling *was* is the
    honest place to break one block from the next. Judging it by distance
    alone mistakes a paper's own paragraph spacing for answer space.

    ``readable`` counts lines that came out as actual words. It is what says
    whether this page's text layer can be trusted to say where a question
    ends: on a paper embedded without a ToUnicode map it is zero, and then
    the gaps between rulings have to be kept whole.
    """
    from pdfminer.layout import (
        LTCurve,
        LTFigure,
        LTImage,
        LTLine,
        LTRect,
        LTTextContainer,
        LTTextLine,
    )

    content: list[_Span] = []
    filler: list[_Span] = []
    readable = 0

    def _add(element: object, into: list[_Span]) -> None:
        top = page_height - element.y1  # type: ignore[attr-defined]
        bottom = page_height - element.y0  # type: ignore[attr-defined]
        if bottom - top <= 0.5:
            # A rule has no height of its own — it is in or it is out.
            if not y_top <= top <= y_bottom:
                return
        else:
            overlap = min(bottom, y_bottom) - max(top, y_top)
            if overlap < _INSIDE_RATIO * (bottom - top):
                return
        into.append(_Span(
            top=max(top, y_top),
            bottom=min(bottom, y_bottom),
            x0=element.x0,  # type: ignore[attr-defined]
            x1=element.x1,  # type: ignore[attr-defined]
        ))

    for element in layout:  # type: ignore[attr-defined]
        if isinstance(element, LTTextContainer):
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                if _is_filler(line):
                    _add(line, filler)
                    continue
                if _text_size(line) < _MIN_TEXT_SIZE:
                    continue  # barcode / running head, not question content
                _add(line, content)
                if _READABLE_RE.search(line.get_text()):
                    readable += 1
        elif isinstance(
            element, (LTLine, LTRect, LTCurve, LTFigure, LTImage)
        ) and element.height <= _FURNITURE_RATIO * page_height:
            # Taller than that and it is the margin bar CIE draws down every
            # page, not part of any question.
            _add(element, content)
    return content, filler, readable


@dataclass(frozen=True)
class _Span:
    """One element's footprint inside a band, top-down."""

    top: float
    bottom: float
    x0: float
    x1: float


def _text_size(line: object) -> float:
    """The largest glyph on the line — 0 when it has none."""
    from pdfminer.layout import LTChar

    sizes = [
        char.size
        for char in line  # type: ignore[attr-defined]
        if isinstance(char, LTChar) and char.get_text().strip()
    ]
    return max(sizes) if sizes else 0.0


def _writing_column(
    filler: Sequence[_Span], page_width: float
) -> tuple[float, float]:
    """The x range worth cropping to: number gutter on the left, ruling on
    the right.

    The two edges are found differently on purpose. The left one is the
    question-number column, and it is a fixed property of the CIE template
    that :mod:`page_segmenter` already matches boundaries against — so it is
    taken from there rather than measured. Every attempt to infer it from
    the page put it in the wrong place: derived from the ruling it landed at
    x79 on 16 of 52 papers and x100 on two more, both right of the number
    (x72.4), which is how the export kept dropping question numbers.

    The right edge is measured, because nothing fixes it: content may
    overhang the ruling a little (a wide table) and the paper's own
    registration marks sit further right still.
    """
    from modules.marking.page_segmenter import question_number_x

    left = max(0.0, question_number_x(page_width) - _PAD)
    ruled = [span for span in filler if span.x1 - span.x0 > page_width * 0.3]
    if not ruled:
        return left, page_width * (1 - _COLUMN_INSET)
    return left, _right_edge(span.x1 for span in ruled) + _COLUMN_PAD


def _right_edge(values: Iterable[float]) -> float:
    """The rightmost ruling edge that the paper uses *often*.

    Not the extreme: the corner registration marks and the odd over-long
    rule pull it out to x551, past the printed writing area. Rare positions
    are dropped first, then the outermost of what is left.
    """
    counts = Counter(round(value) for value in values)
    total = sum(counts.values())
    common = [
        value for value, count in counts.items()
        if count >= total * _EDGE_SHARE
    ] or list(counts)
    return float(max(common))


def _page_extents(
    layout: object, page_height: float
) -> list[tuple[float, float]]:
    """Every mark on the page a crop edge could cut through, top-down.

    Unlike :func:`_content_spans` this keeps small text. The exponent in
    "2x²" is a 7.5pt glyph — the same size as the barcode strip the size
    filter exists to remove — so filtering by size left the top of every
    superscript outside the crop (measured on 9231 s25 P1 Q7: 2.5pt of it).
    Size cannot tell those two apart, but overlap can, and overlap is all
    this feeds: a superscript overlaps the line it belongs to, while the
    barcode sits alone above everything and so is never grown into.
    """
    from pdfminer.layout import (
        LTCurve,
        LTFigure,
        LTImage,
        LTLine,
        LTRect,
        LTTextContainer,
        LTTextLine,
    )

    out: list[tuple[float, float]] = []
    for element in layout:  # type: ignore[attr-defined]
        if isinstance(element, LTTextContainer):
            for line in element:
                if isinstance(line, LTTextLine) and not _is_filler(line):
                    out.append((page_height - line.y1, page_height - line.y0))
        elif isinstance(
            element, (LTLine, LTRect, LTCurve, LTFigure, LTImage)
        ) and element.height <= _FURNITURE_RATIO * page_height:
            out.append((page_height - element.y1, page_height - element.y0))
    return out


def _uncut_top(
    extents: Sequence[tuple[float, float]], y_top: float, floor: float
) -> float:
    """Pull *y_top* up until it stops slicing through something.

    A question's region begins at the top of its number's glyph box, which
    is where the *line* begins but not where everything on that line begins:
    displayed maths rises above the digits beside it. Measured on 9231 s25
    P1 Q7 — the fraction's numerator tops out 8pt above the "7", so cropping
    at the "7" cut the numerator in half, which is exactly what the export
    was doing.

    Grown transitively, because a fraction is a stack of boxes and stopping
    at the first still cuts, and self-limiting: it halts at the first clear
    horizontal gap, which above a question is its predecessor's answer
    space. *floor* is the page's top margin — a question that starts at the
    top of a page has nothing above it to keep, so it must not reach up into
    the running head.
    """
    cursor = y_top
    for _ in range(len(extents) + 1):
        above = [
            top for top, bottom in extents
            if top < cursor - _TOUCH and bottom > cursor + _TOUCH
        ]
        if not above:
            break
        highest = min(above)
        if highest < floor or y_top - highest > _MAX_LIFT:
            break  # as far as it is safe to grow
        cursor = highest
    return cursor


def _ruling_blocks(
    rows: Sequence[_Span],
) -> list[tuple[float, float]]:
    """Rows of ruling → the solid blocks of answer space they make up.

    Each row is stretched down to the next one, because the blank *under* a
    ruling is as much answer space as the ruling itself; consecutive rows
    then merge into one block. The stretch is the measured row pitch, not a
    constant — papers rule at their own spacing (24.5pt on the two measured
    here) and a wrong guess either leaves slivers between rows or eats into
    the question below.
    """
    if not rows:
        return []
    ordered = sorted(rows, key=lambda span: span.top)
    tops = [span.top for span in ordered]
    gaps = [
        b - a for a, b in zip(tops, tops[1:], strict=False)
        if 0 < b - a < _MAX_PITCH
    ]
    pitch = median(gaps) if gaps else _DEFAULT_PITCH

    blocks: list[list[float]] = []
    for span in ordered:
        stretched = max(span.bottom, span.top + pitch)
        if blocks and span.top - blocks[-1][1] <= pitch * 0.6:
            blocks[-1][1] = max(blocks[-1][1], stretched)
        else:
            blocks.append([span.top, stretched])
    return [(top, bottom) for top, bottom in blocks]


def _column_from(
    pages: Mapping[int, object],
    heights: Mapping[int, float],
    page_width: float,
) -> tuple[float, float]:
    spans: list[_Span] = []
    for index, layout in pages.items():
        _, page_filler, _ = _content_spans(
            layout, 0.0, heights[index], heights[index]
        )
        spans.extend(page_filler)
    return _writing_column(spans, page_width)


def document_column(qp_path: str) -> tuple[float, float]:
    """The paper's writing column, measured over the whole document.

    Measured once, over everything: per question it wobbles, because a
    question whose answer space is entirely indented (all of it under a
    sub-part) reports a left edge 21pt further right, and the question
    number then falls outside the crop — that is how six of ten questions
    lost their number. Sampling only the opening pages is no better; on one
    of the two papers here they are the indented ones. The column is a
    property of the paper's template, so the leftmost ruling in the whole
    document is what defines it.
    """
    from pdfminer.high_level import extract_pages

    pages: dict[int, object] = {}
    heights: dict[int, float] = {}
    width = 0.0
    for index, layout in enumerate(extract_pages(qp_path)):
        pages[index] = layout
        heights[index] = layout.height
        width = max(width, layout.width)
    return _column_from(pages, heights, width or 612.0)


def content_bands(
    qp_path: str,
    bands: Sequence[Band],
    column: tuple[float, float] | None = None,
    *,
    top_margin: float = _TOP_MARGIN,
) -> list[Band]:
    """Cut the answer space out of each band, keeping everything else.

    Cutting out the ruling rather than hunting for the question is what makes
    this work on both kinds of paper. Detecting ruling is reliable — it is
    one glyph repeated across a line, whatever the font encoding says that
    glyph is. Detecting *content* is not: on the 2025 papers the text layer
    holds almost nothing but the ruling (page 3 of 9709 s25 P3: 4 305 ruling
    glyphs, 385 others, none forming a sentence), so "keep what looks like
    content" kept nothing and the trim silently did nothing.

    A gap between rulings is kept whole rather than shrunk to the text in it:
    on a paper whose question text isn't in the text layer, shrinking would
    cut away the question itself.

    Bands with nothing but ruling disappear, which is the point — a page of
    pure answer space contributes no pages to the export.
    """
    from pdfminer.high_level import extract_pages

    wanted = {band.page_idx for band in bands}
    if not wanted:
        return []

    pages: dict[int, object] = {}
    heights: dict[int, float] = {}
    widths: dict[int, float] = {}
    for index, layout in enumerate(extract_pages(qp_path)):
        if index in wanted:
            pages[index] = layout
            heights[index] = layout.height
            widths[index] = layout.width
        if len(pages) == len(wanted):
            break

    if column is None:
        column = _column_from(pages, heights, max(widths.values()))

    out: list[Band] = []
    extents: dict[int, list[tuple[float, float]]] = {}
    for region_band in bands:
        page_layout = pages.get(region_band.page_idx)
        if page_layout is None:
            continue
        height = heights[region_band.page_idx]
        # Grow the top *before* narrowing to it. An element the region's
        # edge slices through is at most half inside it, so _content_spans
        # has already thrown it away by the time the band is measured — the
        # question's own first line included.
        if region_band.page_idx not in extents:
            extents[region_band.page_idx] = _page_extents(page_layout, height)
        band = region_band.from_top(_uncut_top(
            extents[region_band.page_idx], region_band.y_top, top_margin
        ))
        content, filler, readable = _content_spans(
            page_layout, band.y_top, band.y_bottom, height
        )
        cursor = band.y_top
        for ruled_top, ruled_bottom in _ruling_blocks(filler):
            _keep(
                out, band, cursor, min(ruled_top, band.y_bottom),
                content, readable, column,
            )
            cursor = max(cursor, ruled_bottom)
        _keep(out, band, cursor, band.y_bottom, content, readable, column)
    return out


def _keep(
    out: list[Band],
    band: Band,
    top: float,
    bottom: float,
    content: Sequence[_Span],
    readable: int,
    column: tuple[float, float],
) -> None:
    """Add the gap between two rulings, if it holds anything at all.

    An empty gap is dropped — on a page of pure answer space the strip above
    the first ruling is blank, and it would otherwise come through as a
    sliver.

    A gap is then closed up around its content, but **only when the page's
    text layer is legible**. Where it isn't, the text positions say nothing
    about where the question really is, and tightening the band on them
    would crop away the very thing being exported.
    """
    if bottom - top < _MIN_BAND:
        return
    inside = [
        span for span in content
        if top <= (span.top + span.bottom) / 2 <= bottom
    ]
    if not inside:
        return
    if readable:
        top = max(top, min(span.top for span in inside) - _PAD)
        bottom = min(bottom, max(span.bottom for span in inside) + _PAD)
        if bottom - top < _MIN_BAND:
            return
    out.append(Band(
        page_idx=band.page_idx,
        y_top=max(band.y_top, top),
        y_bottom=min(band.y_bottom, bottom),
        x_left=column[0],
        x_right=column[1],
    ))


def compose_pdf(crops: Sequence[QuestionCrop]) -> bytes:
    """Render the crops into one PDF, a new page per question.

    Raises:
        ValueError: no crop had any band to place — an empty PDF is not a
            useful thing to hand back as a file.
    """
    readers: dict[str, PdfReader] = {}
    writer = PdfWriter()
    scratch = PdfWriter()
    placed = 0

    for crop in crops:
        if not crop.bands:
            continue
        reader = readers.get(crop.qp_path)
        if reader is None:
            reader = PdfReader(crop.qp_path)
            readers[crop.qp_path] = reader

        first = reader.pages[crop.bands[0].page_idx]
        width = float(first.mediabox.width)
        height = float(first.mediabox.height)

        for page_plan in plan_pages(crop.bands, height):
            out_page = writer.add_blank_page(width=width, height=height)
            for placement in page_plan:
                source = reader.pages[placement.band.page_idx]
                src_height = float(source.mediabox.height)
                src_width = float(source.mediabox.width)
                left = placement.band.x_left or 0.0
                right = placement.band.x_right or src_width
                band_copy = scratch.add_page(source)
                # The CropBox is the whole trick: pypdf's merge reads it and
                # emits `re W n` around the stamped content, so everything
                # outside the band is clipped instead of overprinting the
                # band above it — and, with the x bounds, so are the margin
                # bar and registration marks down the sides.
                band_copy.cropbox = RectangleObject((
                    left,
                    src_height - placement.band.y_bottom,
                    right,
                    src_height - placement.band.y_top,
                ))
                # Both systems measured from their own page top, so the shift
                # is the difference of the two tops. Horizontally the column
                # is centred, which keeps the page looking like a page.
                dy = (
                    (height - placement.y_top)
                    - (src_height - placement.band.y_top)
                )
                dx = (width - (right - left)) / 2 - left
                out_page.merge_transformed_page(
                    band_copy, Transformation().translate(dx, dy)
                )
                placed += 1

    if not placed:
        raise ValueError("没有可导出的题目区域")

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_export(
    records: Iterable[MistakeRecord], qp_path_of: Mapping[str, str]
) -> tuple[bytes, list[str]]:
    """The whole export: records → cropped PDF, plus what couldn't be found.

    Returns the PDF bytes and a list of human-readable warnings (a paper with
    no QP on disk, a question the segmenter couldn't locate). Warnings are
    returned rather than raised: exporting nine of ten questions is worth
    doing, as long as the tenth is named.

    Raises:
        ValueError: nothing at all could be exported.
    """
    from pathlib import Path

    items = list(records)
    warnings: list[str] = []
    crops: list[QuestionCrop] = []

    for paper_id, question_ids in main_questions_by_paper(items).items():
        path = qp_path_of.get(paper_id, "")
        if not path or not Path(path).is_file():
            warnings.append(f"{paper_id}: 找不到 QP 文件，已跳过")
            continue
        found, missing = crops_for_paper(paper_id, path, question_ids)
        crops.extend(found)
        if missing:
            warnings.append(
                f"{paper_id}: QP 里定位不到 {', '.join(missing)}"
            )
        if found and not any(crop.trimmed for crop in found):
            warnings.append(
                f"{paper_id}: 这份 PDF 的文字层是乱码（字体没有 ToUnicode），"
                "认不出答题横线，已按整题区域导出"
            )

    return compose_pdf(crops), warnings


def qp_paths_by_paper(
    records: Iterable[MistakeRecord],
    qp_path_of: Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Split the papers into those whose QP is on disk and those that aren't.

    A missing QP is reported rather than skipped silently — "half your
    selection is in the file" is exactly the kind of thing that should be
    said out loud.
    """
    found: dict[str, str] = {}
    missing: list[str] = []
    for paper_id in main_questions_by_paper(records):
        path = qp_path_of.get(paper_id, "")
        if path:
            found[paper_id] = path
        else:
            missing.append(paper_id)
    return found, missing
