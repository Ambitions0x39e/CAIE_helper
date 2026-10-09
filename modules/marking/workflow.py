"""UI-agnostic orchestration for the Mark tab's flow.

Plain functions over explicit arguments: the UI layer keeps the widgets,
the threading and the user-facing strings, and calls in here for the decisions.

Nothing in this module may import ``app_web`` (see CLAUDE.md's one-directional
layering rule) — that constraint is exactly what makes it testable, so keep
UI strings on the other side of the boundary.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from modules.marking.mcq_parser import is_valid_manual_answer

if TYPE_CHECKING:
    from pathlib import Path

    from modules.marking.grader import QuestionResult
    from modules.marking.page_segmenter import PageClip, QuestionRegion
    from modules.marking.syllabus_parser import SyllabusInfo


# ── Page assignments ──────────────────────────────────────────────

def parse_page_spec(spec: str) -> list[int] | None:
    """Parse a page box ("2", "2,3") into page numbers.

    Returns ``None`` when the text is not a clean comma-separated integer
    list, so a caller can tell "typed something unusable" apart from "left
    it blank" — the old inline version conflated the two.
    """
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        return None
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


def collect_page_assignments(
    raw: Mapping[str, str],
) -> dict[str, list[int]]:
    """Question id → page numbers, dropping blank and malformed entries."""
    assignments: dict[str, list[int]] = {}
    for qid, spec in raw.items():
        pages = parse_page_spec(spec)
        if pages is not None:
            assignments[qid] = pages
    return assignments


def regions_to_page_map(
    regions: Iterable[QuestionRegion],
) -> tuple[dict[str, str], dict[str, list[PageClip]]]:
    """Turn segmenter regions into the tab's page strings + clip lists.

    A region whose clips resolve to no pages is skipped entirely rather than
    stored as a blank entry — a phantom "" would count as a detected question
    and understate the real shortfall.
    """
    pages: dict[str, str] = {}
    clips: dict[str, list[PageClip]] = {}
    for region in regions:
        page_nums = sorted({c.page_idx + 1 for c in region.clips})
        if not page_nums:
            continue
        pages[region.question_id] = ",".join(str(p) for p in page_nums)
        clips[region.question_id] = region.clips
    return pages, clips


# ── MCQ answers ───────────────────────────────────────────────────

def merge_mcq_answers(
    detected: Mapping[str, str],
    manual: Mapping[str, str],
) -> dict[str, str]:
    """Overlay hand-typed answers on the detected ones, ignoring junk."""
    merged = dict(detected)
    for qid, value in manual.items():
        if is_valid_manual_answer(value):
            merged[qid] = value
    return merged


# ── Scores ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScoreSummary:
    """A graded paper's totals, after any manual score overrides."""

    score: float
    max_score: float

    @property
    def percentage(self) -> float:
        return (self.score / self.max_score * 100) if self.max_score else 0.0


def summarise_scores(
    results: Iterable[QuestionResult],
    overrides: Mapping[str, float] | None = None,
) -> ScoreSummary:
    """Total a grading run, preferring the user's override for each question."""
    overrides = overrides or {}
    items = list(results)
    return ScoreSummary(
        score=sum(overrides.get(r.question, r.total) for r in items),
        max_score=sum(r.max for r in items),
    )


# ── Syllabus topics ───────────────────────────────────────────────

def component_paper_number(paper_id: str) -> str | None:
    """``"9701_s25_qp_21"`` → ``"2"``; None when the id isn't that shape.

    Same convention as ``config_store.get_paper_page_config``: the paper
    number is the component's first digit. The id has to be a *downloaded*
    one (``<subject>_<season><year>_qp_<component>``) — the mark scheme's own
    cover-page id ("9701/21/M/J/25") is not guaranteed to line up with it.
    """
    parts = paper_id.split("_")
    if len(parts) < 4:
        return None
    component = parts[3]
    return component[0] if component[:1].isdigit() else None


def topics_for_paper(
    syllabus_info: SyllabusInfo | None, paper_id: str | None
) -> dict[str, str] | None:
    """Topic id → name for this paper, or None when it can't be resolved.

    Returns None — never an empty dict — for every "no topics" case (no
    syllabus, unusable paper id, or a component the syllabus doesn't map,
    such as a practical paper), so the grader's prompt omits the topic
    section instead of showing an empty list.
    """
    if syllabus_info is None or not paper_id:
        return None
    paper_number = component_paper_number(paper_id)
    if paper_number is None:
        return None
    topic_ids = syllabus_info.component_topics.get(paper_number)
    if not topic_ids:
        return None
    named = {
        tid: syllabus_info.topics[tid].name
        for tid in topic_ids
        if tid in syllabus_info.topics
    }
    return named or None


# ── Rendering ─────────────────────────────────────────────────────

class Renderer(Protocol):
    """The slice of a renderer a grading run needs.

    Declared structurally so a test can drive ``sheet.grade_sheet`` with a
    stub, and so nothing here has to name a concrete rasterizer.
    """

    def render_regions(
        self,
        source: str | bytes | Path,
        clips: list[PageClip],
        dpi: int = ...,
    ) -> list[bytes]: ...

    def render_pages(
        self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = ...,
    ) -> list[bytes]: ...
