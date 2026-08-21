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
from dataclasses import dataclass, field
from statistics import median
from typing import TYPE_CHECKING

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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
    coordinates (y grows downward from the page top)."""

    page_idx: int
    y_top: float
    y_bottom: float

    @property
    def height(self) -> float:
        return self.y_bottom - self.y_top


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
    every = [f"Q{n}" for n in range(1, doc.main_count + 1)]
    regions, _ = match_scanned(doc, every)
    by_id = {region.question_id: region for region in regions}

    crops: list[QuestionCrop] = []
    missing: list[str] = []
    for question_id in wanted:
        region = by_id.get(_as_q(question_id))
        if region is None:
            missing.append(question_id)
            continue
        whole = clips_to_bands(region.clips)
        trimmed = content_bands(qp_path, whole)
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
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], int]:
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

    content: list[tuple[float, float]] = []
    filler: list[tuple[float, float]] = []
    readable = 0

    def _add(element: object, into: list[tuple[float, float]]) -> None:
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
        into.append((max(top, y_top), min(bottom, y_bottom)))

    for element in layout:  # type: ignore[attr-defined]
        if isinstance(element, LTTextContainer):
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                if _is_filler(line):
                    _add(line, filler)
                    continue
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


def _ruling_blocks(
    rows: Sequence[tuple[float, float]],
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
    ordered = sorted(rows)
    tops = [top for top, _ in ordered]
    gaps = [
        b - a for a, b in zip(tops, tops[1:], strict=False)
        if 0 < b - a < _MAX_PITCH
    ]
    pitch = median(gaps) if gaps else _DEFAULT_PITCH

    blocks: list[list[float]] = []
    for top, bottom in ordered:
        stretched = max(bottom, top + pitch)
        if blocks and top - blocks[-1][1] <= pitch * 0.6:
            blocks[-1][1] = max(blocks[-1][1], stretched)
        else:
            blocks.append([top, stretched])
    return [(top, bottom) for top, bottom in blocks]


def content_bands(qp_path: str, bands: Sequence[Band]) -> list[Band]:
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
    for index, layout in enumerate(extract_pages(qp_path)):
        if index in wanted:
            pages[index] = layout
            heights[index] = layout.height
        if len(pages) == len(wanted):
            break

    out: list[Band] = []
    for band in bands:
        page_layout = pages.get(band.page_idx)
        if page_layout is None:
            continue
        height = heights[band.page_idx]
        content, filler, readable = _content_spans(
            page_layout, band.y_top, band.y_bottom, height
        )
        cursor = band.y_top
        for ruled_top, ruled_bottom in _ruling_blocks(filler):
            _keep(
                out, band, cursor, min(ruled_top, band.y_bottom),
                content, readable,
            )
            cursor = max(cursor, ruled_bottom)
        _keep(out, band, cursor, band.y_bottom, content, readable)
    return out


def _keep(
    out: list[Band],
    band: Band,
    top: float,
    bottom: float,
    content: Sequence[tuple[float, float]],
    readable: int,
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
        (c_top, c_bottom) for c_top, c_bottom in content
        if top <= (c_top + c_bottom) / 2 <= bottom
    ]
    if not inside:
        return
    if readable:
        top = max(top, min(t for t, _ in inside) - _PAD)
        bottom = min(bottom, max(b for _, b in inside) + _PAD)
        if bottom - top < _MIN_BAND:
            return
    out.append(Band(
        page_idx=band.page_idx,
        y_top=max(band.y_top, top),
        y_bottom=min(band.y_bottom, bottom),
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
                band_copy = scratch.add_page(source)
                # The CropBox is the whole trick: pypdf's merge reads it and
                # emits `re W n` around the stamped content, so everything
                # outside the band is clipped instead of overprinting the
                # band above it.
                band_copy.cropbox = RectangleObject((
                    0,
                    src_height - placement.band.y_bottom,
                    float(source.mediabox.width),
                    src_height - placement.band.y_top,
                ))
                # Both systems measured from their own page top, so the shift
                # is the difference of the two tops.
                dy = (
                    (height - placement.y_top)
                    - (src_height - placement.band.y_top)
                )
                out_page.merge_transformed_page(
                    band_copy, Transformation().translate(0, dy)
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
