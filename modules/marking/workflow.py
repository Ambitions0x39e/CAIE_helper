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
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
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
    from pathlib import Path

    from core.settings import GraderConfig
    from modules.marking.ms_parser import PaperConfig
    from modules.marking.page_segmenter import PageClip, QuestionRegion
    from modules.marking.syllabus_parser import SyllabusInfo

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


# ── Grading run ───────────────────────────────────────────────────

class Renderer(Protocol):
    """The slice of NativeRenderer a grading run needs.

    Declared structurally so tests can drive :func:`grade_paper` without a
    Flet page, an event loop, or the pdfrx service behind it.
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


@dataclass(frozen=True)
class QuestionFailure:
    """One question that could not be rendered or graded.

    Rendering and grading a question is independent of every other question,
    so one failing must not stop the rest — see :func:`grade_paper`.
    """

    question: str
    error: str


@dataclass
class GradeOutcome:
    """Result of a grading run — each question succeeds or fails on its own.

    ``results`` holds every question that graded cleanly, restored to
    ``question_ids`` order (not completion order, which is nondeterministic
    under concurrency). ``failures`` lists the rest.
    """

    results: list[QuestionResult] = field(default_factory=list)
    failures: list[QuestionFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


# Caps how many questions render/grade at once. Each slot holds an HTTP
# round trip open for up to the configured timeout (120-300s) — this bounds
# load on the API and the render RPC, not CPU, so it doesn't need to track
# core count (same reasoning as setup_step.py's concurrent MS-parse/scan).
_MAX_CONCURRENT_QUESTIONS = 4


def grade_paper(
    *,
    config: GraderConfig,
    paper_config: PaperConfig,
    paper_type: PaperType,
    pdf_source: str | bytes | Path,
    question_ids: list[str],
    assignments: Mapping[str, list[int]],
    clips: Mapping[str, list[PageClip]],
    renderer: Renderer,
    syllabus_info: SyllabusInfo | None = None,
    paper_id: str | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    max_workers: int = _MAX_CONCURRENT_QUESTIONS,
) -> GradeOutcome:
    """Grade every question concurrently, rendering its pages or clips.

    Clips (from segmentation) are preferred over whole pages: they crop to
    the question, so the model sees less unrelated working.

    Each question renders and grades on its own worker thread. A stalled
    render or a failed API call is recorded against that question alone and
    does not stop the others — unlike a plain sequential loop, where one
    failure would abort every question queued behind it.

    ``on_progress`` calls are serialised (never invoked concurrently from two
    threads), so a caller that pushes them straight into a UI update doesn't
    need its own locking.

    ``syllabus_info`` + ``paper_id`` are resolved once per run into the topic
    list every question is graded against; either being absent simply means
    the questions come back untagged, never that the run fails.
    """
    outcome = GradeOutcome()
    total = len(question_ids)
    if total == 0:
        if on_progress is not None:
            on_progress(0, 0, "")
        return outcome

    results_by_qid: dict[str, QuestionResult] = {}
    progress_lock = threading.Lock()
    done = 0
    # Resolved once, not per question: it is the same for the whole paper.
    topic_list = topics_for_paper(syllabus_info, paper_id)

    def _grade_one(qid: str) -> None:
        nonlocal done
        try:
            qcfg = paper_config.questions[qid]
            region_clips = clips.get(qid)
            if region_clips:
                images = renderer.render_regions(
                    pdf_source, region_clips, config.dpi,
                )
            else:
                images = renderer.render_pages(
                    pdf_source, list(assignments[qid]), config.dpi,
                )
            raw = grade_question(
                config=config,
                images=images,
                question_id=qid,
                mark_scheme=qcfg.mark_scheme,
                max_marks=qcfg.max_marks,
                paper_type=paper_type,
                topic_list=topic_list,
            )
            result: QuestionResult | None = parse_grading_result(raw)
            failure: QuestionFailure | None = None
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            # Log the traceback: a toast auto-dismisses, and the stack is
            # what pins down a render/API stall.
            _log.exception("grading failed on question %s", qid)
            result = None
            failure = QuestionFailure(question=qid, error=str(exc))

        with progress_lock:
            if result is not None:
                results_by_qid[qid] = result
            if failure is not None:
                outcome.failures.append(failure)
            done += 1
            if on_progress is not None:
                on_progress(done, total, qid)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_grade_one, question_ids))

    outcome.results = [
        results_by_qid[qid] for qid in question_ids if qid in results_by_qid
    ]
    if on_progress is not None:
        on_progress(total, total, "")
    return outcome
