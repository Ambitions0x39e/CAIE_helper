"""Parse a CIE syllabus PDF into a topic list + a paper→topics mapping.

The Mark tab uses the result to tell the VL grader which topics a paper can
possibly be about, so every graded question can be tagged with one. Input is
always a local file the user picked — nothing here fetches anything.

Two subject families lay out their "Content overview" section differently
(see docs/superpowers/specs/2026-08-20-mistake-notebook-design.md):

* **Math family** (9709 / 9231) — an explicit three-column table
  ``Content section | Assessment component | Topics included``. Each content
  section maps 1:1 to one paper, and the table already lists topics at
  ``N.M`` granularity, so that is the granularity kept.
* **Science family** (9701 / 9702 / 9700 / 9696) — two flat numbered lists
  ("AS Level subject content" 1–22, "A Level subject content" 23–N) under
  subject-specific category headings. Topics are kept at ``N`` granularity:
  ``N.M`` there is finer than a VL model can usefully classify against.
  The paper→topic-range link comes from the anchor sentence that opens the
  "Subject content" chapter ("Candidates for Cambridge International AS Level
  should study topics 1–22.") combined with each paper's own "based on the
  AS/A Level syllabus content" statement.

The parser does **not** force one granularity on both — each family keeps the
depth its own syllabus presents.

Everything comes from ``pdfminer`` — no VL call, no rendering: syllabus PDFs
extract cleanly, unlike the CID-garbled mark-scheme cover pages.

**The math table is read from geometry, not from flowed text**, the same way
``core/gt_parser.py`` reads grade-threshold tables. Verified against the real
9231 document: its three columns sit at fixed x offsets and each row's three
cells share a baseline, but the extracted *text* interleaves them, drops a
row's component next to the wrong section, and lets the last topic's name run
on into the page's closing prose. Reading columns by x and rows by y makes all
three go away. ``parse_syllabus_text`` keeps the text-based reading for the
science family (a flat list, where text order is the real order) and as a
fallback for math.
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import NamedTuple

from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTTextContainer, LTTextLine
from pydantic import BaseModel

from core.settings import app_settings


class SyllabusParseError(ValueError):
    """Raised when a PDF matches neither known syllabus layout.

    Callers catch this and grade without topics — a missing or unreadable
    syllabus must never fail a grading run.
    """


class SyllabusTopic(BaseModel):
    topic_id: str
    name: str
    category: str | None = None


class SyllabusInfo(BaseModel):
    subject_id: str
    topics: dict[str, SyllabusTopic]
    component_topics: dict[str, list[str]]


# ── Patterns ──────────────────────────────────────────────────────

# Syllabus PDFs write ranges with an en dash; a hyphen shows up in some
# reflowed extractions, so accept either.
_DASH = r"[-‐-―]"

_CONTENT_OVERVIEW_RE = re.compile(r"Content overview", re.IGNORECASE)
# "Subject content" must be anchored to its own line: the science content
# overview's own headings ("AS Level subject content") contain the phrase,
# and an unanchored match would cut the region off before its first topic.
_REGION_END_RE = re.compile(
    r"Assessment overview|Details of the assessment"
    r"|^\s*\d*\s*Subject content\b",
    re.IGNORECASE | re.MULTILINE,
)
# How far a "Content overview" region may run when nothing ends it.
_REGION_MAX_CHARS = 12_000

_MATH_MARKER_RE = re.compile(r"Assessment\s+component", re.IGNORECASE)
_SCIENCE_MARKER_RE = re.compile(
    r"\bAS?\s+Level\s+subject\s+content", re.IGNORECASE
)

# "1.3 Coordinate geometry" — a dotted topic id anywhere in the table.
_TOPIC_ID_RE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2})(?![\d.])")
# "1 Pure Mathematics 1   Paper 1" — one row head of the math table. Every
# separator is horizontal-only whitespace and the whole thing is anchored to
# a line: a plain ``\s+`` spans the blank line between two column blocks and
# invents rows out of a column-major extraction ("…Mathematics 2" + "Assessment
# component" + "Paper 1" reads as section 2 → paper 1).
_MATH_ROW_RE = re.compile(
    r"^[^\S\n]*(\d{1,2})[^\S\n]+([A-Z][A-Za-z0-9 &'’/\-]{2,60}?)"
    r"[^\S\n]+Paper[^\S\n]+(\d{1,2})\b",
    re.MULTILINE,
)
_PAPER_MARKER_RE = re.compile(r"\bPaper\s+(\d{1,2})\b")
# Trailing junk swept up into the last topic name of a row: the next row's
# head ("… 2 Pure Mathematics 2") or its component cell ("… Paper 2").
_ROW_HEAD_TAIL_RE = re.compile(r"\s+\d{1,2}\s+[A-Z]")
_PAPER_TAIL_RE = re.compile(r"\s+Paper\s+\d")

# "3 Chemical bonding" — one entry of a science flat list.
_SCIENCE_TOPIC_LINE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z][^\n]{2,90})$")
_LEVEL_HEADING_RE = re.compile(
    r"^AS?\s+Level\s+subject\s+content\b", re.IGNORECASE
)
_CATEGORY_RE = re.compile(r"^[A-Za-z][A-Za-z &'’/\-]*$")
# Running headers/footers that would otherwise read as category headings.
_FOOTER_HINTS = (
    "www.",
    "Back to contents",
    "Cambridge International",
    "syllabus for",
    "Contents",
)

_AS_ANCHOR_RE = re.compile(
    rf"\bAS\s+Level\s+should\s+study\s+topics\s+(\d{{1,2}})\s*{_DASH}\s*(\d{{1,2}})",
    re.IGNORECASE,
)
_A_ANCHOR_ALL_RE = re.compile(
    r"\bA\s+Level\s+should\s+study\s+all\s+topics", re.IGNORECASE
)
_A_ANCHOR_RANGE_RE = re.compile(
    rf"\bA\s+Level\s+should\s+study\s+topics\s+(\d{{1,2}})\s*{_DASH}\s*(\d{{1,2}})",
    re.IGNORECASE,
)
# Which syllabus content a paper examines. "AS Level syllabus content" is not
# a substring of "A Level syllabus content", so plain containment is enough.
_AS_CONTENT_PHRASE = "AS Level syllabus content"
_A_CONTENT_PHRASE = "A Level syllabus content"
# A paper's description block is capped rather than run to the next heading:
# the assessment-overview table lists every paper back to back.
_PAPER_WINDOW_CHARS = 1_500


# ── Helpers ───────────────────────────────────────────────────────


def _topic_sort_key(topic_id: str) -> tuple[int, ...]:
    """Order "10" after "9" and "1.10" after "1.9" — string order would not."""
    return tuple(int(part) for part in topic_id.split(".") if part.isdigit())


def _clean_topic_name(raw: str) -> str:
    """Trim a topic name harvested from the gap between two topic ids."""
    name = " ".join(raw.split())
    name = _ROW_HEAD_TAIL_RE.split(name)[0]
    name = _PAPER_TAIL_RE.split(name)[0]
    return name.strip(" ,;.–—-")


def _content_overview_regions(text: str) -> list[str]:
    """Every "Content overview" slice, in document order.

    The table of contents mentions the heading too, so the caller tries each
    slice and keeps the first that actually looks like a content overview.
    """
    regions: list[str] = []
    for match in _CONTENT_OVERVIEW_RE.finditer(text):
        start = match.end()
        end_match = _REGION_END_RE.search(text, start)
        end = end_match.start() if end_match else len(text)
        regions.append(text[start : min(end, start + _REGION_MAX_CHARS)])
    return regions


# ── Math family ───────────────────────────────────────────────────


def _collect_dotted_topics(region: str) -> dict[str, SyllabusTopic]:
    """Read "N.M Name" entries out of the math table's Topics column."""
    matches = list(_TOPIC_ID_RE.finditer(region))
    topics: dict[str, SyllabusTopic] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(region)
        name = _clean_topic_name(region[match.end() : end])
        if not name:
            continue
        topics.setdefault(
            match.group(1),
            SyllabusTopic(topic_id=match.group(1), name=name, category=None),
        )
    return topics


def _parse_math(
    region: str,
) -> tuple[dict[str, SyllabusTopic], dict[str, list[str]]]:
    topics = _collect_dotted_topics(region)
    if not topics:
        raise SyllabusParseError("math-style content overview had no topics")

    sections: list[str] = []
    for topic_id in topics:
        section = topic_id.split(".")[0]
        if section not in sections:
            sections.append(section)

    section_to_paper: dict[str, str] = {}
    for match in _MATH_ROW_RE.finditer(region):
        section_to_paper.setdefault(match.group(1), match.group(3))

    if not section_to_paper:
        # Column-major extraction: the whole "Assessment component" column
        # lands before the whole "Topics included" column, so a row head
        # never forms. Sections and papers still appear in the same order,
        # and the table maps them 1:1 — pair them positionally.
        papers = [m.group(1) for m in _PAPER_MARKER_RE.finditer(region)]
        if len(papers) != len(sections):
            raise SyllabusParseError(
                "math-style content overview: cannot map sections to papers"
            )
        section_to_paper = dict(zip(sections, papers, strict=True))

    component_topics: dict[str, list[str]] = {}
    for section, paper in section_to_paper.items():
        ids = sorted(
            (t for t in topics if t.split(".")[0] == section),
            key=_topic_sort_key,
        )
        if ids:
            component_topics.setdefault(paper, []).extend(ids)
    return topics, component_topics


# ── Science family ────────────────────────────────────────────────


def _looks_like_category(line: str) -> bool:
    if any(hint in line for hint in _FOOTER_HINTS):
        return False
    if not 3 <= len(line) <= 60:
        return False
    return bool(_CATEGORY_RE.fullmatch(line))


def _collect_flat_topics(region: str) -> dict[str, SyllabusTopic]:
    """Read the two flat "N Name" lists, remembering the category heading."""
    topics: dict[str, SyllabusTopic] = {}
    category: str | None = None
    for raw_line in region.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _LEVEL_HEADING_RE.match(line):
            # A level heading opens a new list; its categories follow.
            category = None
            continue
        match = _SCIENCE_TOPIC_LINE_RE.match(line)
        if match:
            name = match.group(2).strip(" .,")
            topics.setdefault(
                match.group(1),
                SyllabusTopic(
                    topic_id=match.group(1), name=name, category=category
                ),
            )
        elif _looks_like_category(line):
            category = line
    return topics


def _ids_in_range(
    topics: dict[str, SyllabusTopic], low: int, high: int
) -> list[str]:
    return sorted(
        (t for t in topics if low <= int(t) <= high), key=_topic_sort_key
    )


def _parse_science(
    region: str, text: str
) -> tuple[dict[str, SyllabusTopic], dict[str, list[str]]]:
    topics = _collect_flat_topics(region)
    if not topics:
        raise SyllabusParseError("science-style content overview had no topics")

    as_anchor = _AS_ANCHOR_RE.search(text)
    if as_anchor is None:
        raise SyllabusParseError(
            "science-style syllabus without an AS Level 'should study topics' "
            "anchor sentence"
        )
    as_ids = _ids_in_range(
        topics, int(as_anchor.group(1)), int(as_anchor.group(2))
    )

    a_range = _A_ANCHOR_RANGE_RE.search(text)
    if a_range is not None:
        a_ids = _ids_in_range(topics, int(a_range.group(1)), int(a_range.group(2)))
    elif _A_ANCHOR_ALL_RE.search(text):
        a_ids = sorted(topics, key=_topic_sort_key)
    else:
        a_ids = []

    component_topics: dict[str, list[str]] = {}
    markers = list(_PAPER_MARKER_RE.finditer(text))
    for i, match in enumerate(markers):
        paper = match.group(1)
        if paper in component_topics:
            continue
        # Stop at the next paper heading: the assessment-overview table lists
        # every paper back to back, so an unbounded window would read the
        # next paper's content statement as this one's.
        limit = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        window = text[match.end() : min(limit, match.end() + _PAPER_WINDOW_CHARS)]
        if _A_CONTENT_PHRASE in window and a_ids:
            component_topics[paper] = a_ids
        elif _AS_CONTENT_PHRASE in window and as_ids:
            component_topics[paper] = as_ids
    return topics, component_topics


# ── Math family, read from the page geometry ──────────────────────
#
# Why not the text above: pdfminer flows a three-column table into one
# stream, and on the real 9231 document that stream is wrong in three
# separate ways (all verified against the page's line boxes) —
#
#   * a row's three cells arrive as three separate lines, so no "section /
#     component / topics" row ever forms for a regex to read;
#   * the closing prose ("Paper 1 and Paper 4", "Paper 1, 2, 3 and 4")
#     contributes five more "Paper N" mentions than the table has rows;
#   * the last topic in the table has no following topic to bound its name,
#     so it swallows the rest of the page.
#
# In the geometry none of that is ambiguous: columns are fixed x offsets and
# a row's cells share a baseline.

#: A line belongs to a column if it starts at or right of that column's
#: anchor. The slack absorbs the sub-point x jitter between a cell's first
#: line and its wrapped continuations.
_X_TOL = 6.0
#: How far a name fragment may sit from the topic id it belongs to. Real
#: gap seen: 2.6pt, where a superscript (χ²) raised the fragment's box above
#: the id's. One text line is ~15.8pt, so this stays well inside one row.
_Y_TOL_NAME = 8.0
#: Slack when deciding which paper's band a topic falls in. A topic on the
#: same baseline as its "Paper N" cell must land in that band, not the one
#: above.
_Y_TOL_ROW = 4.0
#: How far below a cell a wrapped continuation of it may sit — a bit over one
#: 15.8pt line. Without a bound, the page number in the footer (same column,
#: 280pt lower) reads as more of the last topic's name.
_Y_TOL_WRAP = 20.0

_COMPONENT_HEADER_RE = re.compile(r"^Assessment\b", re.IGNORECASE)
_TOPICS_HEADER_RE = re.compile(r"^Topics\s+included\b", re.IGNORECASE)
#: "Paper 3" alone in its cell. Anchored on both ends on purpose: it is what
#: separates a real component cell from prose like "Paper 1 and Paper 4".
_PAPER_CELL_RE = re.compile(r"^Paper\s+(\d{1,2})$", re.IGNORECASE)
#: "1.4  Matrices", or just "1.4" when the name landed in its own fragment.
_TOPIC_LINE_RE = re.compile(r"^(\d{1,2}\.\d{1,2})\s*(.*)$", re.DOTALL)


class _Line(NamedTuple):
    """One extracted text line, with the geometry the table needs."""

    x0: float
    top: float
    text: str


def _page_lines(layout: object) -> list[_Line]:
    lines: list[_Line] = []
    for element in layout:  # type: ignore[attr-defined]
        if not isinstance(element, LTTextContainer):
            continue
        for line in element:
            if not isinstance(line, LTTextLine):
                continue
            text = line.get_text().strip()
            if text:
                lines.append(_Line(x0=line.x0, top=line.y1, text=text))
    return lines


def _column_anchors(lines: list[_Line]) -> tuple[float, float] | None:
    """The x offsets of the "Assessment component" and "Topics included"
    columns, read off the table's own header row."""
    component = next(
        (ln.x0 for ln in lines if _COMPONENT_HEADER_RE.match(ln.text)), None
    )
    topics = next(
        (ln.x0 for ln in lines if _TOPICS_HEADER_RE.match(ln.text)), None
    )
    if component is None or topics is None or component >= topics:
        return None
    return component, topics


def _in_column(line: _Line, anchor: float, next_anchor: float | None) -> bool:
    if line.x0 < anchor - _X_TOL:
        return False
    return next_anchor is None or line.x0 < next_anchor - _X_TOL


def _read_topic_cells(lines: list[_Line]) -> list[tuple[float, str, str]]:
    """(top, topic_id, name) for every topic in one page's topics column.

    Handles the two shapes a cell arrives in: id and name on one line, or an
    id whose name extracted as a separate fragment beside it.
    """
    complete: list[tuple[float, str, str]] = []
    pending: list[tuple[float, str]] = []
    orphans: list[_Line] = []

    for line in sorted(lines, key=lambda ln: -ln.top):
        match = _TOPIC_LINE_RE.match(line.text)
        if match is None:
            orphans.append(line)
        elif match.group(2).strip():
            complete.append((line.top, match.group(1), match.group(2).strip()))
        else:
            pending.append((line.top, match.group(1)))

    for orphan in orphans:
        near = [
            (abs(orphan.top - top), top, tid)
            for top, tid in pending
            if abs(orphan.top - top) <= _Y_TOL_NAME
        ]
        if near:
            _, top, tid = min(near)
            complete.append((top, tid, orphan.text))
            pending.remove((top, tid))
            continue
        # Not beside any id: a wrapped continuation of the cell above it —
        # but only if it is close enough to be one. Anything further down is
        # page furniture that happens to share the column.
        above = [c for c in complete if c[0] > orphan.top]
        if not above:
            continue
        nearest = min(above, key=lambda c: c[0] - orphan.top)
        if nearest[0] - orphan.top <= _Y_TOL_WRAP:
            complete[complete.index(nearest)] = (
                nearest[0], nearest[1], f"{nearest[2]} {orphan.text}",
            )

    # An id whose name never turned up keeps the id as its name rather than
    # vanishing — the grader can still tag against it.
    complete.extend((top, tid, tid) for top, tid in pending)
    return sorted(complete, key=lambda c: -c[0])


def _parse_math_geometry(
    pdf_path: Path | str,
) -> tuple[dict[str, SyllabusTopic], dict[str, list[str]]] | None:
    """Read the math content-overview table off the page. None if absent."""
    topics: dict[str, SyllabusTopic] = {}
    component_topics: dict[str, list[str]] = {}
    anchors: tuple[float, float] | None = None
    carried_paper: str | None = None
    started = False

    for layout in extract_pages(str(pdf_path)):
        lines = _page_lines(layout)
        found = _column_anchors(lines)
        if found is not None:
            anchors = found
        if anchors is None:
            continue
        component_x, topics_x = anchors

        cells = _read_topic_cells(
            [ln for ln in lines if _in_column(ln, topics_x, None)]
        )
        if not cells:
            if started:
                break  # the table ended on an earlier page
            continue
        started = True

        papers = sorted(
            (
                (ln.top, match.group(1))
                for ln in lines
                if _in_column(ln, component_x, topics_x)
                and (match := _PAPER_CELL_RE.match(ln.text))
            ),
            key=lambda p: -p[0],
        )

        for top, topic_id, name in cells:
            paper = carried_paper
            for paper_top, number in papers:
                if paper_top < top - _Y_TOL_ROW:
                    break
                paper = number
            if paper is None:
                continue
            topics.setdefault(
                topic_id,
                SyllabusTopic(topic_id=topic_id, name=name, category=None),
            )
            ids = component_topics.setdefault(paper, [])
            if topic_id not in ids:
                ids.append(topic_id)
        if papers:
            carried_paper = papers[-1][1]

    if not topics or not component_topics:
        return None
    for ids in component_topics.values():
        ids.sort(key=_topic_sort_key)
    return topics, component_topics


# ── Science family, read from the page geometry ───────────────────
#
# Same lesson as the math table, a different shape. The science content
# overview is two side-by-side columns — AS topics on the left, A Level on
# the right — and pdfminer emits them interleaved by row, so a flowed read
# hands a heading from one column to a topic in the other. Verified on the
# real 9701 document, where topics 10–12 came out under "Analysis" (the
# right column's last heading) instead of "Inorganic chemistry".
#
# The assessment overview has the same problem: Paper 1 and Paper 4 sit side
# by side, so "Questions are based on the AS Level syllabus content." and its
# A Level twin land adjacent in the text with nothing to say which is whose.

_LEVEL_HEADING_LINE_RE = re.compile(
    r"^(AS|A)\s+Level\s+subject\s+content\b", re.IGNORECASE
)
#: "10  Group 2" — one entry of a flat list, id and name on one line.
_SCIENCE_TOPIC_CELL_RE = re.compile(r"^(\d{1,2})\s+(\S.*)$")
#: "Paper 3" alone on its line — a heading, not a mention in prose.
_PAPER_HEADING_RE = re.compile(r"^Paper\s+(\d{1,2})$", re.IGNORECASE)
#: A line belongs to a heading's block if it starts within this of its x.
_COLUMN_TOL = 12.0
#: Prose that reads like a category heading ("AS Level candidates also study
#: practical") but is a sentence fragment about a level.
_LEVEL_PREFIX_RE = re.compile(r"^AS?\s+Level\b", re.IGNORECASE)
#: Dot leaders. The table of contents lists the same headings the real
#: section does ("A Level subject content ....... 10"), so without this the
#: contents page parses as a content overview holding six chapter titles.
_DOT_LEADER_RE = re.compile(r"\.{4,}")


def _nearest(x: float, anchors: list[float]) -> float:
    """The column anchor a line at *x* belongs to.

    Nearest rather than "greatest anchor at or left of x": a column's body
    can start a point or two left of its own heading (313.9 under a heading
    at 315.6 on the real document).
    """
    return min(anchors, key=lambda a: abs(a - x))


def _read_level_columns(
    overview: list[_Line],
) -> tuple[dict[str, SyllabusTopic], dict[str, list[str]]] | None:
    """Topics and their level, read column by column."""
    heads = [
        (line, match.group(1).upper())
        for line in overview
        if (match := _LEVEL_HEADING_LINE_RE.match(line.text))
    ]
    if not heads:
        return None
    anchors = sorted({line.x0 for line, _ in heads})

    topics: dict[str, SyllabusTopic] = {}
    by_level: dict[str, list[str]] = {}
    # A heading owns its column *from its own baseline down* to the next
    # heading in that column. Two-column layouts (9701) put the levels side
    # by side and the y bound never bites; a single-column one stacks them,
    # and then the y bound is the only thing separating AS from A Level.
    for head, level in heads:
        anchor = _nearest(head.x0, anchors)
        floor = max(
            (
                other.top for other, _ in heads
                if _nearest(other.x0, anchors) == anchor
                and other.top < head.top
            ),
            default=float("-inf"),
        )
        category: str | None = None
        column = [
            line for line in overview
            if _nearest(line.x0, anchors) == anchor
            and floor < line.top < head.top
        ]
        for line in sorted(column, key=lambda ln: -ln.top):
            if _DOT_LEADER_RE.search(line.text):
                continue
            if _LEVEL_HEADING_LINE_RE.match(line.text):
                category = None
                continue
            match = _SCIENCE_TOPIC_CELL_RE.match(line.text)
            if match:
                topic_id = match.group(1)
                topics.setdefault(
                    topic_id,
                    SyllabusTopic(
                        topic_id=topic_id,
                        name=match.group(2).strip(),
                        category=category,
                    ),
                )
                by_level.setdefault(level, []).append(topic_id)
            elif _looks_like_category(line.text) and not _LEVEL_PREFIX_RE.match(
                line.text
            ):
                category = line.text
    if not topics:
        return None
    ordered = {
        tid: topics[tid] for tid in sorted(topics, key=_topic_sort_key)
    }
    return ordered, by_level


def _paper_levels(pages: list[list[_Line]]) -> dict[str, str]:
    """Paper number → "AS" / "A", from each paper's own block.

    A paper's block is what sits under its heading *in its own column*, which
    is the only thing that separates Paper 1's content statement from Paper
    4's when the two are printed side by side.
    """
    levels: dict[str, str] = {}
    for lines in pages:
        heads = [
            (line, match.group(1))
            for line in lines
            if (match := _PAPER_HEADING_RE.match(line.text))
        ]
        for head, number in heads:
            if number in levels:
                continue
            floor = max(
                (
                    other.top for other, _ in heads
                    if abs(other.x0 - head.x0) <= _COLUMN_TOL
                    and other.top < head.top
                ),
                default=float("-inf"),
            )
            block = " ".join(
                line.text
                for line in sorted(lines, key=lambda ln: -ln.top)
                if abs(line.x0 - head.x0) <= _COLUMN_TOL
                and floor < line.top < head.top
            )
            if _A_CONTENT_PHRASE in block:
                levels[number] = "A"
            elif _AS_CONTENT_PHRASE in block:
                levels[number] = "AS"
    return levels


def _parse_science_geometry(
    pdf_path: Path | str,
) -> tuple[dict[str, SyllabusTopic], dict[str, list[str]]] | None:
    """Read the science content overview off the page. None if absent."""
    pages = [_page_lines(layout) for layout in extract_pages(str(pdf_path))]
    # The richest page wins rather than the first: the contents page repeats
    # the same headings, and (dot leaders stripped) still yields a handful of
    # chapter titles that look like topics.
    candidates = [
        read
        for lines in pages
        if any(_LEVEL_HEADING_LINE_RE.match(ln.text) for ln in lines)
        and (read := _read_level_columns(lines)) is not None
    ]
    if not candidates:
        return None
    topics, by_level = max(candidates, key=lambda c: len(c[0]))

    as_ids = sorted(set(by_level.get("AS", [])), key=_topic_sort_key)
    # "A Level candidates study the AS topics and the following topics" —
    # the A Level column lists only what it adds.
    a_ids = sorted(
        set(by_level.get("A", [])) | set(as_ids), key=_topic_sort_key
    )

    component_topics: dict[str, list[str]] = {}
    for number, level in _paper_levels(pages).items():
        ids = a_ids if level == "A" else as_ids
        if ids:
            component_topics[number] = ids
    if not component_topics:
        return None
    return topics, component_topics


# ── Store ─────────────────────────────────────────────────────────
#
# A parsed syllabus outlives the session that produced it: the user had to
# find and upload a PDF for it, so re-deriving it is manual work, not a
# recomputation. One JSON per subject id under ``~/.cie_helper/syllabus/``.


def syllabus_path(subject_id: str) -> Path:
    """Where this subject's parsed syllabus is stored."""
    return app_settings.syllabus_dir / f"{subject_id}.json"


def _read(path: Path) -> SyllabusInfo | None:
    if not path.exists():
        return None
    try:
        return SyllabusInfo.model_validate_json(path.read_text("utf-8"))
    except Exception:
        # A truncated or hand-edited file reads as "not stored" rather than
        # taking the Mark tab down with it.
        return None


def _save(info: SyllabusInfo) -> None:
    path = syllabus_path(info.subject_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(info.model_dump_json(indent=2), "utf-8")


def load_syllabus(subject_id: str) -> SyllabusInfo | None:
    """The stored syllabus for a subject, or None if there isn't one.

    Migrates an entry left in the old ``.cache/syllabus`` location on read,
    so an upgrade doesn't silently ask the user to upload the PDF again.
    """
    info = _read(syllabus_path(subject_id))
    if info is not None:
        return info

    legacy = app_settings.legacy_syllabus_cache_dir / f"{subject_id}.json"
    info = _read(legacy)
    if info is not None:
        with contextlib.suppress(OSError):
            _save(info)
            legacy.unlink()
    return info


def stored_syllabuses() -> list[SyllabusInfo]:
    """Every stored syllabus, subject id order — for the settings view."""
    found: dict[str, SyllabusInfo] = {}
    for directory in (
        app_settings.legacy_syllabus_cache_dir,
        app_settings.syllabus_dir,
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            info = _read(path)
            if info is not None:
                found[info.subject_id] = info  # current dir wins
    return [found[key] for key in sorted(found)]


def delete_syllabus(subject_id: str) -> bool:
    """Forget a subject's syllabus. True if anything was removed."""
    removed = False
    for path in (
        syllabus_path(subject_id),
        app_settings.legacy_syllabus_cache_dir / f"{subject_id}.json",
    ):
        if path.exists():
            with contextlib.suppress(OSError):
                path.unlink()
                removed = True
    return removed


# ── Public API ────────────────────────────────────────────────────


def parse_syllabus_text(text: str, subject_id: str) -> SyllabusInfo:
    """Parse already-extracted syllabus text. Raises SyllabusParseError."""
    last_error: SyllabusParseError | None = None
    for region in _content_overview_regions(text):
        if _MATH_MARKER_RE.search(region):
            parser = "math"
        elif _SCIENCE_MARKER_RE.search(region) and _AS_ANCHOR_RE.search(text):
            parser = "science"
        else:
            continue
        try:
            if parser == "math":
                topics, component_topics = _parse_math(region)
            else:
                topics, component_topics = _parse_science(region, text)
        except SyllabusParseError as exc:
            # A table-of-contents line can look like the real thing; keep
            # looking before giving up.
            last_error = exc
            continue
        return SyllabusInfo(
            subject_id=subject_id,
            topics=topics,
            component_topics=component_topics,
        )
    if last_error is not None:
        raise last_error
    raise SyllabusParseError(
        "no recognisable 'Content overview' section — the PDF matches "
        "neither the math-style table nor the science-style flat lists"
    )


def parse_syllabus(
    pdf_path: Path | str, subject_id: str, *, force: bool = False
) -> SyllabusInfo:
    """Parse a local syllabus PDF into topics + a paper→topics mapping.

    Args:
        pdf_path: A syllabus PDF the user uploaded.
        subject_id: Four-digit syllabus code, e.g. ``"9709"``. Also the
            store key — one syllabus per subject.
        force: Re-parse even if one is stored, and replace it. Picking a PDF
            by hand is exactly this case: without it, uploading a corrected
            document would be a no-op against the stored copy.

    Raises:
        SyllabusParseError: The PDF matches neither known layout.
    """
    if not force:
        stored = load_syllabus(subject_id)
        if stored is not None:
            return stored

    # Geometry first for both families — see this module's docstring for what
    # the flowed text gets wrong on the real documents. Text is the fallback,
    # for a layout neither geometry reader recognises.
    geometry = _parse_math_geometry(pdf_path) or _parse_science_geometry(
        pdf_path
    )
    if geometry is not None:
        info = SyllabusInfo(
            subject_id=subject_id,
            topics=geometry[0],
            component_topics=geometry[1],
        )
    else:
        info = parse_syllabus_text(extract_text(str(pdf_path)), subject_id)
    # An unwritable store must not fail the parse.
    with contextlib.suppress(OSError):
        _save(info)
    return info
