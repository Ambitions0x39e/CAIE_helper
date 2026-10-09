"""A grading run over a set of questions, whichever papers they come from.

A whole paper, a practice set and a redone batch of mistakes are all a
:class:`Sheet`: answer pages in one PDF, each item naming the paper and mark
scheme sub-question it answers. :func:`grade_sheet` grades every item against
its own paper's mark scheme, grading type and topic list.

Nothing in this module may import ``app_web``, nor reach ``modules.tutor`` or
``modules.profile`` — ``tests/test_tutor.py`` pins the second.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from modules.marking.grader import (
    QuestionResult,
    grade_question,
    listed_marks,
    parse_grading_result,
)
from modules.marking.page_segmenter import PageClip

if TYPE_CHECKING:
    from core.models import PaperType
    from core.settings import GraderConfig
    from modules.marking.ms_parser import PaperConfig
    from modules.marking.workflow import Renderer

_log = logging.getLogger("cie_helper.mark")


class SheetItem(BaseModel):
    paper_id: str
    #: The mark scheme's sub-question key, ``"Q3a"``.
    question_id: str
    #: Pages of the answer PDF, 1-based like ``Renderer.render_pages``.
    pages: list[int]
    #: Cropped regions; when present they are graded instead of whole pages.
    clips: list[PageClip] = []


class Sheet(BaseModel):
    kind: Literal["paper", "practice", "mistakes"]
    #: The export the answers were written on; None for a whole paper.
    export_id: str | None = None
    pdf_path: str
    items: list[SheetItem]


@dataclass(frozen=True)
class QuestionFailure:
    """One question that could not be rendered or graded.

    Rendering and grading a question is independent of every other question,
    so one failing must not stop the rest — see :func:`grade_sheet`.
    """

    question: str
    error: str
    paper_id: str = ""


@dataclass
class GradeOutcome:
    """Result of a grading run — each question succeeds or fails on its own.

    ``results`` holds every item that graded cleanly, in sheet order (not
    completion order, which is nondeterministic under concurrency).
    ``failures`` lists the rest.
    """

    results: list[QuestionResult] = field(default_factory=list)
    failures: list[QuestionFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


# Caps how many questions render/grade at once. Each slot holds an HTTP
# round trip open for up to the configured timeout (120-300s) — this bounds
# load on the API and the render RPC, not CPU, so it doesn't need to track
# core count.
_MAX_CONCURRENT_QUESTIONS = 4


def grade_sheet(
    *,
    config: GraderConfig,
    sheet: Sheet,
    paper_configs: Mapping[str, tuple[PaperConfig, PaperType]],
    topics_of: Callable[[str], dict[str, str] | None],
    renderer: Renderer,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_result: Callable[[QuestionResult], None] | None = None,
    max_workers: int = _MAX_CONCURRENT_QUESTIONS,
) -> GradeOutcome:
    """Grade every item concurrently, rendering its clips or pages.

    Clips (from segmentation) are preferred over whole pages: they crop to
    the question, so the model sees less unrelated working.

    Each item renders and grades on its own worker thread. A stalled render
    or a failed API call is recorded against that item alone and does not
    stop the others.

    ``on_progress`` and ``on_result`` calls are serialised (never invoked
    concurrently from two threads), so a caller that pushes them straight into
    a UI update doesn't need its own locking. ``on_result`` fires the moment a
    question comes back, out of sheet order.

    ``topics_of`` is asked once per paper, not per item; None means that
    paper's questions come back untagged, never that the run fails.
    """
    outcome = GradeOutcome()
    items = sheet.items
    total = len(items)
    if total == 0:
        if on_progress is not None:
            on_progress(0, 0, "")
        return outcome

    topics = {pid: topics_of(pid) for pid in dict.fromkeys(i.paper_id for i in items)}
    results: dict[int, QuestionResult] = {}
    progress_lock = threading.Lock()
    done = 0

    def _grade_one(index: int) -> None:
        nonlocal done
        item = items[index]
        qid = item.question_id
        try:
            paper_config, paper_type = paper_configs[item.paper_id]
            qcfg = paper_config.questions[qid]
            if item.clips:
                images = renderer.render_regions(sheet.pdf_path, item.clips, config.dpi)
            elif item.pages:
                images = renderer.render_pages(sheet.pdf_path, item.pages, config.dpi)
            else:
                raise ValueError(f"{qid} 没有作答页")

            def ask(missing: int | None = None) -> QuestionResult:
                return parse_grading_result(grade_question(
                    config=config,
                    images=images,
                    question_id=qid,
                    mark_scheme=qcfg.mark_scheme,
                    max_marks=qcfg.max_marks,
                    paper_type=paper_type,
                    topic_list=topics[item.paper_id],
                    missing_marks=missing,
                ))

            graded = ask()
            # A marking point left out of `marks` is a mark the student can
            # never get. Asked again with the gap named, the reply that
            # accounts for more of the question wins.
            short = qcfg.max_marks - listed_marks(graded)
            if short > 0:
                retry = ask(short)
                if listed_marks(retry) > listed_marks(graded):
                    graded = retry
            # The reply carries no paper id, and its question id is the
            # model's echo: both are taken from the item.
            result: QuestionResult | None = graded.model_copy(
                update={"paper_id": item.paper_id, "question": qid},
            )
            failure: QuestionFailure | None = None
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            # Log the traceback: a toast auto-dismisses, and the stack is
            # what pins down a render/API stall.
            _log.exception("grading failed on %s %s", item.paper_id, qid)
            result = None
            failure = QuestionFailure(
                question=qid, error=str(exc), paper_id=item.paper_id,
            )

        with progress_lock:
            if result is not None:
                results[index] = result
                if on_result is not None:
                    on_result(result)
            if failure is not None:
                outcome.failures.append(failure)
            done += 1
            if on_progress is not None:
                on_progress(done, total, qid)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_grade_one, range(total)))

    outcome.results = [results[i] for i in range(total) if i in results]
    if on_progress is not None:
        on_progress(total, total, "")
    return outcome
