"""Where one component's marks go — per-topic loss rates over the attempt rows.

Pure: reads records, returns numbers. The tutor notes are written from this,
and nothing here decides what to say about it.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from core.models import AttemptRecord
from modules.marking.mistakes import subject_id_of
from modules.marking.workflow import component_paper_number


@dataclass(frozen=True)
class TopicStat:
    topic_id: str | None
    topic_name: str | None
    questions: int
    lost: float
    max_score: float
    #: error_type → marks lost to it. Unclassified losses are not in here.
    errors: dict[str, float]

    @property
    def loss_rate(self) -> float:
        return self.lost / self.max_score if self.max_score else 0.0


@dataclass(frozen=True)
class ComponentProfile:
    subject_id: str
    component: str
    papers: int
    #: Highest loss rate first.
    topics: list[TopicStat]
    errors: dict[str, float]


def latest_attempts(records: Iterable[AttemptRecord]) -> list[AttemptRecord]:
    """One row per (paper, question): the most recent grading of it.

    The store is append-only, so a re-graded paper has two sets of rows;
    counting both would weigh that paper twice.
    """
    latest: dict[tuple[str, str], AttemptRecord] = {}
    for r in records:
        key = (r.paper_id, r.question_id)
        if key not in latest or r.timestamp >= latest[key].timestamp:
            latest[key] = r
    return list(latest.values())


def _errors(rows: Iterable[AttemptRecord]) -> dict[str, float]:
    lost: dict[str, float] = defaultdict(float)
    for r in rows:
        if r.error_type:
            lost[r.error_type] += r.max_score - r.score
    return dict(lost)


def component_profile(
    records: Iterable[AttemptRecord], subject_id: str, component: str,
) -> ComponentProfile | None:
    """The profile of one syllabus's Paper *component*, or None with no rows.

    Unanswered questions (``error_type == "blank"``) count toward ``papers``
    but nowhere else: an unfinished paper says nothing about the topics it
    never reached, and folded into a loss rate it reads as a weakness.

    ponytail: plain loss rate, every paper weighted alike — add a recency
    decay once there are months of papers for an old weakness to fade from.
    """
    rows = [
        r for r in latest_attempts(records)
        if subject_id_of(r.paper_id) == subject_id
        and component_paper_number(r.paper_id) == component
    ]
    if not rows:
        return None
    papers = len({r.paper_id for r in rows})
    rows = [r for r in rows if r.error_type != "blank"]

    by_topic: dict[str | None, list[AttemptRecord]] = defaultdict(list)
    for r in rows:
        by_topic[r.topic_id].append(r)

    topics = [
        TopicStat(
            topic_id=topic_id,
            topic_name=next(
                (r.topic_name for r in reversed(group) if r.topic_name), None,
            ),
            questions=len(group),
            lost=sum(r.max_score - r.score for r in group),
            max_score=sum(r.max_score for r in group),
            errors=_errors(group),
        )
        for topic_id, group in by_topic.items()
    ]
    topics.sort(key=lambda t: (-t.loss_rate, -t.questions))
    return ComponentProfile(
        subject_id=subject_id,
        component=component,
        papers=papers,
        topics=topics,
        errors=_errors(rows),
    )
