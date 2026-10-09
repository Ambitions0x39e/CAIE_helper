"""An export's record: the blank paper and everything grading it will need.

The 错题本 export and 专项练习 both end here. The questions are laid out by
:mod:`modules.question_pdf`; this adds the snapshot — each paper's mark scheme
parts, grading type and topic list as they stand at export time — so a paper
handed back weeks later is graded against what it was exported with.

Nothing here may import ``app_web``.
"""
from __future__ import annotations

import datetime
from collections.abc import Collection, Iterable, Mapping
from typing import Literal

from core.models import (
    ExportedMark,
    ExportedPaper,
    ExportedQuestion,
    ExportManifest,
)
from modules.question_pdf import QuestionRef, build_export, main_question_id


def build_record(
    kind: Literal["practice", "mistakes"],
    title: str,
    records: Iterable[QuestionRef],
    qp_path_of: Mapping[str, str],
    ms_path_of: Mapping[str, str],
    *,
    now: datetime.datetime | None = None,
) -> tuple[ExportManifest, bytes, list[str]]:
    """(manifest, blank paper, warnings) for the questions in *records*.

    Raises:
        ValueError: nothing at all could be exported.
    """
    now = now or datetime.datetime.now()
    export_id = f"{now:%Y%m%d-%H%M%S}-{kind}"
    data, pages, warnings = build_export(records, qp_path_of, export_id)

    questions = [
        ExportedQuestion(paper_id=paper_id, question_id=question_id, pages=on)
        for (paper_id, question_id), on in pages.items()
    ]
    papers: dict[str, ExportedPaper] = {}
    for paper_id in dict.fromkeys(q.paper_id for q in questions):
        mains = {q.question_id for q in questions if q.paper_id == paper_id}
        papers[paper_id] = snapshot_paper(
            paper_id, mains, ms_path_of.get(paper_id, ""),
        )
    untyped = [pid for pid, paper in papers.items() if paper.paper_type is None]
    if untyped:
        warnings.append(
            f"{', '.join(untyped)}: 不知道批改类型，这几题交回时不能批改"
        )

    manifest = ExportManifest(
        export_id=export_id, kind=kind, title=title, created_at=now,
        questions=questions, papers=papers,
    )
    return manifest, data, warnings


def snapshot_paper(
    paper_id: str, mains: Collection[str], ms_path: str,
) -> ExportedPaper:
    """One paper's part of the snapshot: the mark scheme parts of *mains*,
    the grading type and the topic list.

    The type the mark scheme was last parsed for wins over the one the
    syllabus implies — it is the one the student picked when grading it.
    """
    from modules.marking.mistakes import subject_id_of
    from modules.marking.ms_parser import cached_mark_scheme
    from modules.marking.syllabus_parser import load_syllabus, resolve_grading_type
    from modules.marking.workflow import topics_for_paper

    config = cached_mark_scheme(ms_path) if ms_path else None
    ms = None if config is None else {
        qid: ExportedMark(max_marks=q.max_marks, mark_scheme=q.mark_scheme)
        for qid, q in config.questions.items()
        if main_question_id(qid) in mains
    }
    return ExportedPaper(
        paper_type=(config.paper_type if config else None)
        or resolve_grading_type(paper_id),
        topics=topics_for_paper(load_syllabus(subject_id_of(paper_id)), paper_id),
        ms=ms,
    )
