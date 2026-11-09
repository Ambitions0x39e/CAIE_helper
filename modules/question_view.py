"""One question of a paper beside its mark scheme, as pictures of the PDFs.

The question comes from :func:`modules.question_pdf.crops_for_paper`. The mark
scheme is located here, from the labels in the first column of its table
(``"3(b)(ii)"``), and needs no model and no parse.

**Image pages are why this is not just "label to next label".** Most recent
mark schemes carry some pages as a full-page image with no text layer, and a
label on one cannot be read. Whatever a question might have on such a page is
shown, in every question it could belong to: a slice too many is visible at a
glance, a part of the answer gone missing is not. 9231_s25_14 is the case to
remember — 4(a) on an image page, so the first readable label says 4(b).

Nothing here may import ``app_web``.
"""
from __future__ import annotations

import base64
import io
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTContainer, LTCurve, LTImage
from pydantic import BaseModel, ValidationError

from core.gt_parser import _decode
from core.settings import app_settings
from modules.marking.page_segmenter import PageClip
from modules.marking.renderer import LocalRenderer
from modules.question_pdf import crops_for_paper

_log = logging.getLogger("cie_helper.question_view")

#: Raise when the located slices change, so what is cached is worked out again.
_CACHE_VERSION = 2
#: Stays sharp at the viewer's top zoom and still crosses the bridge one question
#: at a time: the heaviest question measured is about 2 MB and a second to render.
_RENDER_DPI = 300
#: How far in from a page's leftmost text to look for the "Question" header.
_HEADER_ZONE = 60.0
#: Past the header word, how far a label may start. The column's width varies by
#: template: 9231's Answer text starts 55pt in from the table's edge, 9702's 65pt.
_LABEL_OVERHANG = 8.0
#: A header row's top edge is this far at most above its text, with other rules
#: in between (a shaded band starts 6pt below the edge on 9231).
_HEADER_RISE = 12.0
#: Fewer characters than this beside an image is a page that is the image.
_MIN_PAGE_CHARS = 20
#: Narrower than the Question column, so a table drawn cell by cell still reaches
#: its left edge. A fraction bar this long sits inside the table it belongs to.
_MIN_RULE = 30.0
#: Glyphs this close vertically are on one row of the Question column.
_ROW_TOLERANCE = 3.0
#: A slice thinner than this is a table's edge rather than a row of it.
_MIN_SLICE = 8.0
#: Clear of the rule a slice ends on, and of the footer's text.
_PAD = 2.0
#: How dark a pixel has to be to count as ink, out of 255. Above zero because a
#: scanned page's white is not quite white.
_INK = 16
_INK_MARGIN_PX = 6

_LABEL_RE = re.compile(r"^(\d{1,2})(?!\d)(.*)$")
_FIRST_PART_RE = re.compile(r"^\(?a?\)?\(?i?\)?$")


@dataclass(frozen=True)
class MsLabel:
    """A question number read off the first column."""

    number: int
    page: int
    #: Top of the row it opens — or of the table's header row, when it opens a
    #: table, so the question before does not end on a stray header.
    y: float
    #: The question's first row, rather than a later part like ``"(b)"``.
    first_part: bool


@dataclass(frozen=True)
class PageArea:
    """Where a page's table sits, top-down, and whether the page is an image."""

    top: float
    bottom: float
    left: float
    right: float
    is_image: bool


@dataclass(frozen=True)
class MsLayout:
    candidates: list[MsLabel]
    areas: list[PageArea]
    #: The earliest page that can hold an answer: see :func:`_first_answer_page`.
    first_page: int


class QuestionClips(BaseModel):
    question: list[PageClip]
    mark_scheme: list[PageClip]


class _CachedMap(BaseModel):
    version: int
    questions: dict[str, QuestionClips]


class QuestionList(BaseModel):
    success: bool
    error: str | None = None
    questions: list[str] = []
    has_ms: bool = False


class QuestionImages(BaseModel):
    success: bool
    error: str | None = None
    #: PNG data URLs, top to bottom.
    question: list[str] = []
    mark_scheme: list[str] = []


def is_first_part(rest: str) -> bool:
    """Is what follows the number the opening of a question?"""
    return _FIRST_PART_RE.match(rest) is not None


def accept_labels(
    candidates: Iterable[MsLabel],
    wanted: Sequence[int],
    areas: Sequence[PageArea],
) -> list[MsLabel]:
    """The candidates that read as the paper's questions, in order.

    A number further on than the next one expected is only believed when an
    image page since the last label could have held the ones in between.
    """
    pending = list(wanted)
    accepted: list[MsLabel] = []
    for candidate in candidates:
        if candidate.number not in pending:
            continue
        if candidate.number != pending[0]:
            since = accepted[-1].page if accepted else 0
            if not any(area.is_image for area in areas[since:candidate.page]):
                continue
        pending = pending[pending.index(candidate.number) + 1:]
        accepted.append(candidate)
    return accepted


def mark_scheme_clips(
    wanted: Sequence[int],
    labels: Sequence[MsLabel],
    areas: Sequence[PageArea],
    first_page: int,
) -> dict[int, list[PageClip]]:
    """Question number → the slices that show its mark scheme."""
    by_number = {label.number: label for label in labels}
    out: dict[int, list[PageClip]] = {}
    last = len(areas) - 1

    for index, number in enumerate(wanted):
        before = next(
            (by_number[n] for n in reversed(wanted[:index]) if n in by_number), None,
        )
        after = next(
            (by_number[n] for n in wanted[index + 1:] if n in by_number), None,
        )
        end_page = after.page if after else last
        end_y = after.y if after else None

        label = by_number.get(number)
        start_y: float | None
        if label is not None:
            start_page, start_y = label.page, label.y
            if not label.first_part:
                while start_page - 1 >= first_page and areas[start_page - 1].is_image:
                    start_page, start_y = start_page - 1, None
        else:
            search_from = before.page + 1 if before else first_page
            image = next(
                (p for p in range(search_from, end_page + 1) if areas[p].is_image),
                None,
            )
            if image is not None:
                start_page, start_y = image, None
            elif before is not None:
                start_page, start_y = before.page, before.y
            else:
                start_page, start_y = first_page, None

        out[number] = _slices(areas, start_page, start_y, end_page, end_y)
    return out


def _slices(
    areas: Sequence[PageArea],
    start_page: int,
    start_y: float | None,
    end_page: int,
    end_y: float | None,
) -> list[PageClip]:
    clips: list[PageClip] = []
    for page in range(start_page, end_page + 1):
        area = areas[page]
        top = start_y if page == start_page and start_y is not None else area.top
        bottom = end_y if page == end_page and end_y is not None else area.bottom
        if bottom - top < _MIN_SLICE:
            continue
        clips.append(PageClip(
            page_idx=page, y_top=top, y_bottom=bottom,
            x_left=area.left, x_right=area.right,
        ))
    return clips


def _flatten(node: object) -> Iterable[object]:
    if isinstance(node, LTContainer):
        for child in node:
            yield from _flatten(child)
    else:
        yield node


def _column_rows(chars: Iterable[LTChar]) -> list[tuple[float, str]]:
    """The Question column's rows, top-down, as (top, text with no spaces)."""
    rows: list[list[LTChar]] = []
    for char in sorted(chars, key=lambda c: -c.y1):
        if rows and rows[-1][0].y1 - char.y1 <= _ROW_TOLERANCE:
            rows[-1].append(char)
        else:
            rows.append([char])
    return [
        (
            max(c.y1 for c in row),
            _decode("".join(c.get_text() for c in sorted(row, key=lambda c: c.x0)))
            .replace(" ", ""),
        )
        for row in rows
    ]


def _header_top(text_top: float, rule_tops: Iterable[float]) -> float:
    """The top edge of the header row whose text starts at *text_top*."""
    return min(
        (t for t in rule_tops if text_top - _HEADER_RISE <= t <= text_top + 1.0),
        default=text_top - _ROW_TOLERANCE,
    )


def _first_answer_page(
    first_table: int | None, images: set[int], prose: set[int],
) -> int:
    """The earliest page that can hold an answer.

    Front matter can be part images: 9231_s25_11 has its annotations on image
    pages, then its abbreviations as text, then question 1 on an image page. A
    page of text before the first question table is still front matter, so nothing
    before it is an answer. An image page with no such page after it may be one.
    """
    if first_table is None:
        return min((i for i in images if i >= 1), default=0)
    return max((i + 1 for i in prose if i < first_table), default=min(first_table, 1))


def read_ms_layout(ms_path: str) -> MsLayout:
    """Every candidate label, and each page's table area, from one read of the PDF."""
    candidates: list[MsLabel] = []
    #: Per page: None for an image page or one without a table, filled in below.
    tables: list[tuple[float, float, float, float] | None] = []
    images: set[int] = set()
    #: Pages of text with no question table. A blank page is not one of them.
    prose: set[int] = set()
    sizes: list[tuple[float, float]] = []
    footers: list[float] = []
    first_table: int | None = None

    for index, layout in enumerate(extract_pages(ms_path)):
        height = float(layout.height)
        sizes.append((float(layout.width), height))
        items = list(_flatten(layout))
        chars = [
            i for i in items if isinstance(i, LTChar) and i.get_text().strip()
        ]
        if len(chars) < _MIN_PAGE_CHARS and any(isinstance(i, LTImage) for i in items):
            images.add(index)
            tables.append(None)
            continue

        left = min((c.x0 for c in chars), default=0.0)
        zone = [c for c in chars if c.x0 < left + _HEADER_ZONE]
        headers = [y1 for y1, row in _column_rows(zone) if row == "Question"]
        rules = [
            i for i in items
            if isinstance(i, LTCurve) and i.x1 - i.x0 >= _MIN_RULE
            and i.y1 - i.y0 < height / 2
            and i.x0 >= 0 and i.x1 <= layout.width
        ]
        if not headers or not rules:
            tables.append(None)
            if len(chars) >= _MIN_PAGE_CHARS:
                prose.add(index)
            continue

        table_top = _header_top(
            height - headers[0], [height - r.y1 for r in rules],
        )
        rules = [r for r in rules if height - r.y1 >= table_top - 1.0]
        table_bottom = height - min(r.y0 for r in rules)
        tables.append((
            table_top,
            table_bottom,
            min(r.x0 for r in rules),
            max(r.x1 for r in rules),
        ))
        below = [c for c in chars if height - c.y1 > table_bottom]
        if below:
            footers.append(height - max(c.y1 for c in below))
        if first_table is None:
            first_table = index

        column_right = _LABEL_OVERHANG + max(
            c.x1 for c in zone if abs(c.y1 - headers[0]) <= _ROW_TOLERANCE
        )
        column = [
            c for c in chars
            if c.x0 < column_right and height - c.y1 >= table_top - _PAD
        ]
        rule_tops = sorted(height - r.y1 for r in rules)
        header: float | None = None
        for y1, row in _column_rows(column):
            top = height - y1
            if row == "Question":
                header = _header_top(top, rule_tops)
                continue
            match = _LABEL_RE.match(row)
            if match:
                above = [t for t in rule_tops if t <= top + 1.0]
                candidates.append(MsLabel(
                    number=int(match.group(1)),
                    page=index,
                    y=header if header is not None else (
                        above[-1] if above else top - _ROW_TOLERANCE
                    ),
                    first_part=is_first_part(match.group(2)),
                ))
            header = None

    return MsLayout(
        candidates=candidates,
        areas=_page_areas(tables, images, sizes, footers),
        first_page=_first_answer_page(first_table, images, prose),
    )


def _page_areas(
    tables: Sequence[tuple[float, float, float, float] | None],
    images: set[int],
    sizes: Sequence[tuple[float, float]],
    footers: Sequence[float],
) -> list[PageArea]:
    """A page with no table of its own falls back on the document's template."""
    known = [t for t in tables if t is not None]
    areas: list[PageArea] = []
    for index, table in enumerate(tables):
        width, height = sizes[index]
        if table is not None:
            top, bottom, left, right = table
        elif known:
            top = median(t[0] for t in known)
            bottom = median(footers) - _PAD if footers else height
            left = median(t[2] for t in known)
            right = median(t[3] for t in known)
        else:
            top, bottom, left, right = 0.0, height, 0.0, width
        areas.append(PageArea(
            top=top - _PAD if table is not None else top,
            bottom=bottom + _PAD if table is not None else bottom,
            left=left - _PAD,
            right=right + _PAD,
            is_image=index in images,
        ))
    return areas


def _load_map(qp_path: str, ms_path: str) -> dict[str, QuestionClips]:
    """Question id → its slices of the QP and MS, worked out once per paper.

    A paper with no MS yet is not cached: it would keep its empty side after
    the MS arrived.
    """
    cache = app_settings.question_cache_dir / f"{Path(qp_path).stem}.json"
    has_ms = bool(ms_path) and Path(ms_path).is_file()
    if has_ms and cache.is_file():
        try:
            cached = _CachedMap.model_validate_json(cache.read_text("utf-8"))
        except (ValidationError, OSError):
            cached = None
        if cached is not None and cached.version == _CACHE_VERSION:
            return cached.questions

    if not Path(qp_path).is_file():
        raise FileNotFoundError(f"找不到 QP 文件：{qp_path}")

    crops, _ = crops_for_paper(Path(qp_path).stem, qp_path, None, trim=True)
    shown = [crop for crop in crops if crop.bands]
    numbers = [int(crop.question_id.lstrip("Q")) for crop in shown]

    ms_clips: dict[int, list[PageClip]] = {}
    if has_ms:
        layout = read_ms_layout(ms_path)
        ms_clips = mark_scheme_clips(
            numbers,
            accept_labels(layout.candidates, numbers, layout.areas),
            layout.areas,
            layout.first_page,
        )

    questions = {
        crop.question_id: QuestionClips(
            question=[
                PageClip(
                    page_idx=band.page_idx, y_top=band.y_top, y_bottom=band.y_bottom,
                    x_left=band.x_left, x_right=band.x_right,
                )
                for band in crop.bands
            ],
            mark_scheme=ms_clips.get(number, []),
        )
        for crop, number in zip(shown, numbers, strict=True)
    }
    if has_ms:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            _CachedMap(version=_CACHE_VERSION, questions=questions).model_dump_json(),
            "utf-8",
        )
    return questions


def _inked(png: bytes) -> bytes | None:
    """The slice without the blank above and below it; None when it is all blank.

    A slice is cut by page furniture, not by where its ink stops: a table on a
    page ends well above the footer, and an image page's height is a guess.
    """
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(png)).convert("RGB")
    ink = ImageOps.invert(image.convert("L")).point(lambda v: 255 if v > _INK else 0)
    box = ink.getbbox()
    if box is None:
        return None
    tight = image.crop((
        0,
        max(0, box[1] - _INK_MARGIN_PX),
        image.width,
        min(image.height, box[3] + _INK_MARGIN_PX),
    ))
    buffer = io.BytesIO()
    tight.save(buffer, format="PNG")
    return buffer.getvalue()


def _data_urls(source: str, clips: list[PageClip]) -> list[str]:
    urls: list[str] = []
    for png in LocalRenderer().render_regions(source, clips, dpi=_RENDER_DPI):
        inked = _inked(png)
        if inked is not None:
            urls.append(f"data:image/png;base64,{base64.b64encode(inked).decode()}")
    return urls


def list_questions(qp_path: str, ms_path: str) -> QuestionList:
    """The paper's main questions, or why they cannot be listed."""
    from core.models import PaperType
    from modules.marking.syllabus_parser import resolve_grading_type

    if resolve_grading_type(Path(qp_path).stem) is PaperType.MCQ:
        return QuestionList(success=False, error="选择题卷不能按题查看")
    try:
        questions = _load_map(qp_path, ms_path)
    except Exception as exc:  # noqa: BLE001 — a bad PDF is a message, not a crash
        _log.exception("list_questions failed for %s", qp_path)
        return QuestionList(success=False, error=str(exc))
    if not questions:
        return QuestionList(success=False, error="这份卷子切不出题目")
    return QuestionList(
        success=True,
        questions=list(questions),
        has_ms=bool(ms_path) and Path(ms_path).is_file(),
    )


def question_images(qp_path: str, ms_path: str, question_id: str) -> QuestionImages:
    """One question and its mark scheme, as pictures."""
    try:
        clips = _load_map(qp_path, ms_path).get(question_id)
        if clips is None:
            return QuestionImages(success=False, error=f"找不到 {question_id}")
        return QuestionImages(
            success=True,
            question=_data_urls(qp_path, clips.question),
            mark_scheme=_data_urls(ms_path, clips.mark_scheme) if ms_path else [],
        )
    except Exception as exc:  # noqa: BLE001 — a bad PDF is a message, not a crash
        _log.exception("question_images failed for %s %s", qp_path, question_id)
        return QuestionImages(success=False, error=str(exc))
