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
import re
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
    from core.models import ExportManifest, PaperType
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


# ── Handing an export back ────────────────────────────────────────

#: The footer ``question_pdf`` prints on every exported page.
_MARKER_RE = re.compile(r"CIEH (\S+) (\S+) (\S+) \d+/\d+")


class ForeignPaper(ValueError):
    """The PDF carries another export's markers."""


def pages_by_question(
    pdf_path: str, export_id: str,
) -> dict[tuple[str, str], list[int]]:
    """(paper_id, main question) → the 1-based pages of *pdf_path* holding it.

    A marked page goes to the question its marker names; an unmarked one —
    a page added in GoodNotes — to the question of the marked page before
    it. Pages before the first marker belong to nothing and are dropped.

    Read with ``all_texts``: a layered export may wrap each original page in
    a form XObject, and the marker then sits inside an ``LTFigure`` the
    default parameters do not read text from. The segmenter must not share
    this — with ``all_texts`` it mistakes short words for question numbers.

    Raises:
        ForeignPaper: a marker names another export.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTFigure, LTTextContainer

    def marker(element: object) -> re.Match[str] | None:
        for child in element:  # type: ignore[attr-defined]
            if isinstance(child, LTTextContainer):
                found = _MARKER_RE.search(child.get_text())
                if found:
                    return found
            elif isinstance(child, LTFigure):
                found = marker(child)
                if found:
                    return found
        return None

    out: dict[tuple[str, str], list[int]] = {}
    current: tuple[str, str] | None = None
    laparams = LAParams(all_texts=True)
    for number, page in enumerate(extract_pages(pdf_path, laparams=laparams), 1):
        found = marker(page)
        if found:
            if found.group(1) != export_id:
                raise ForeignPaper(found.group(1))
            current = (found.group(2), found.group(3))
        if current is not None:
            out.setdefault(current, []).append(number)
    return out


@dataclass
class HandBack:
    """An export handed back, ready for :func:`grade_sheet`."""

    sheet: Sheet
    paper_configs: dict[str, tuple[PaperConfig, PaperType]]
    #: (paper_id, main question) that cannot be graded, and why.
    skipped: list[tuple[str, str, str]]


def sheet_from_export(manifest: ExportManifest, pdf_path: str) -> HandBack:
    """The answers in *pdf_path* as a sheet, graded against the export's
    snapshot.

    Each exported main question becomes its mark scheme parts, all on the
    question's pages. A question is skipped with its reason when no page was
    found for it, or its paper went out with no mark scheme or no grading
    type.

    Raises:
        ForeignPaper: the PDF is another export's.
    """
    from modules.marking.ms_parser import PaperConfig, QuestionConfig
    from modules.question_pdf import main_question_id

    pages = pages_by_question(pdf_path, manifest.export_id)
    items: list[SheetItem] = []
    configs: dict[str, tuple[PaperConfig, PaperType]] = {}
    skipped: list[tuple[str, str, str]] = []
    for question in manifest.questions:
        pid, main = question.paper_id, question.question_id
        paper = manifest.papers.get(pid)
        on = pages.get((pid, main))
        if not on:
            skipped.append((pid, main, "no_pages"))
            continue
        if paper is None or paper.ms is None:
            skipped.append((pid, main, "no_mark_scheme"))
            continue
        if paper.paper_type is None:
            skipped.append((pid, main, "no_grading_type"))
            continue
        parts = [qid for qid in paper.ms if main_question_id(qid) == main]
        if not parts:
            skipped.append((pid, main, "no_mark_scheme"))
            continue
        if pid not in configs:
            configs[pid] = (
                PaperConfig(
                    paper_id=pid,
                    total_marks=sum(m.max_marks for m in paper.ms.values()),
                    questions={
                        qid: QuestionConfig(
                            max_marks=m.max_marks, mark_scheme=m.mark_scheme,
                        )
                        for qid, m in paper.ms.items()
                    },
                    paper_type=paper.paper_type,
                ),
                paper.paper_type,
            )
        items += [SheetItem(paper_id=pid, question_id=qid, pages=on) for qid in parts]
    sheet = Sheet(
        kind=manifest.kind, export_id=manifest.export_id,
        pdf_path=pdf_path, items=items,
    )
    return HandBack(sheet=sheet, paper_configs=configs, skipped=skipped)
