"""A grading run as attempt rows — every question, full marks included.

The mistake rows only say where marks were lost; these carry the denominator
(how often a topic came up at all) that a per-topic loss rate needs.

Nothing in this module may import ``app_web`` (see CLAUDE.md's
one-directional layering rule).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from core.models import AttemptRecord

if TYPE_CHECKING:
    import datetime

    from modules.marking.grader import QuestionResult


def attempts_from_results(
    results: Iterable[QuestionResult],
    *,
    paper_id: str,
    topics: Mapping[str, str] | None = None,
    scores: Mapping[str, float] | None = None,
    timestamp: datetime.datetime,
) -> list[AttemptRecord]:
    """One record per graded question.

    ``scores`` is the user's per-question override, preferred over the
    model's mark as in ``mistakes_from_results``. ``error_type`` is dropped
    at full marks — a question adjusted up to full lost nothing to classify.
    """
    topics = topics or {}
    scores = scores or {}
    records: list[AttemptRecord] = []
    for result in results:
        score = float(scores.get(result.question, result.total))
        topic_id = result.topic or None
        records.append(
            AttemptRecord(
                paper_id=paper_id,
                question_id=result.question,
                topic_id=topic_id,
                topic_name=topics.get(topic_id) if topic_id else None,
                error_type=result.error_type if score < result.max else None,
                score=score,
                max_score=float(result.max),
                timestamp=timestamp,
            )
        )
    return records
