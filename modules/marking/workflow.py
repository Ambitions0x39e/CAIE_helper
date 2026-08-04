"""UI-agnostic orchestration for the Mark tab's flow.

Everything here used to live inside ``app_flet/tabs/mark.py``'s
``build_mark_tab`` closure, where it read and wrote a dozen shared ``list``
refs and Flet controls — so none of it could be tested. These are plain
functions over explicit arguments; the Flet layer keeps the widgets, the
threading and the user-facing strings, and calls in here for the decisions.

Nothing in this module may import ``flet`` or ``app_flet`` (see CLAUDE.md's
one-directional layering rule) — that constraint is exactly what makes it
testable, so keep UI strings on the other side of the boundary.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from core.models import PaperType
from modules.marking.grader import (
    QuestionResult,
    grade_question,
    parse_grading_result,
)
from modules.marking.mcq_parser import is_valid_manual_answer

if TYPE_CHECKING:
    from core.settings import GraderConfig
    from modules.marking.ms_parser import PaperConfig
    from modules.marking.page_segmenter import PageClip, QuestionRegion

_log = logging.getLogger("cie_helper.mark")


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


# ── Grading run ───────────────────────────────────────────────────

class Renderer(Protocol):
    """The slice of NativeRenderer a grading run needs.

    Declared structurally so tests can drive :func:`grade_paper` without a
    Flet page, an event loop, or the pdfrx service behind it.
    """

    def render_regions(
        self, source: bytes, clips: list[PageClip], dpi: int = ...,
    ) -> list[bytes]: ...

    def render_pages(
        self, source: bytes, page_numbers: list[int], dpi: int = ...,
    ) -> list[bytes]: ...


@dataclass
class GradeOutcome:
    """Result of a grading run — partial results survive a mid-run failure."""

    results: list[QuestionResult] = field(default_factory=list)
    #: Question being graded when it blew up; ``None`` if the run completed.
    failed_question: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def grade_paper(
    *,
    config: GraderConfig,
    paper_config: PaperConfig,
    paper_type: PaperType,
    pdf_bytes: bytes,
    question_ids: list[str],
    assignments: Mapping[str, list[int]],
    clips: Mapping[str, list[PageClip]],
    renderer: Renderer,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> GradeOutcome:
    """Grade each question in turn, rendering its pages or clipped regions.

    Clips (from segmentation) are preferred over whole pages: they crop to
    the question, so the model sees less unrelated working.

    A failure aborts the run but keeps whatever was already graded, and names
    the question it died on — a stalled render or API call is otherwise very
    hard to pin down from a toast.
    """
    outcome = GradeOutcome()
    total = len(question_ids)

    for i, qid in enumerate(question_ids):
        if on_progress is not None:
            on_progress(i, total, qid)
        try:
            qcfg = paper_config.questions[qid]
            region_clips = clips.get(qid)
            if region_clips:
                images = renderer.render_regions(
                    pdf_bytes, region_clips, config.dpi,
                )
            else:
                images = renderer.render_pages(
                    pdf_bytes, list(assignments[qid]), config.dpi,
                )
            raw = grade_question(
                config=config,
                images=images,
                question_id=qid,
                mark_scheme=qcfg.mark_scheme,
                max_marks=qcfg.max_marks,
                paper_type=paper_type,
            )
            outcome.results.append(parse_grading_result(raw))
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            # Log the traceback: a toast auto-dismisses, and the stack is
            # what pins down a render/API stall.
            _log.exception("grading failed on question %s", qid)
            outcome.failed_question = qid
            outcome.error = str(exc)
            return outcome

    if on_progress is not None:
        on_progress(total, total, "")
    return outcome
