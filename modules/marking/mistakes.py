"""Pure functions behind the 错题本 tab.

Turning a grading run into rows, grouping them, filtering them and writing
them out as CSV are all decisions, not widgets — they live here so they can
be tested without a Flet page, for the same reason ``workflow.py`` exists.

Nothing in this module may import ``flet`` or ``app_flet`` (see CLAUDE.md's
one-directional layering rule); keep user-facing strings on the other side
of the boundary, with the one exception of :data:`UNCLASSIFIED`, which is a
grouping key the UI only echoes.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Collection, Iterable, Mapping
from typing import TYPE_CHECKING

from core.models import MistakeRecord

if TYPE_CHECKING:
    import datetime

    from modules.marking.grader import QuestionResult

#: Bucket for questions with no topic — no syllabus, a component the syllabus
#: does not map (practical papers), or a question the model could not place.
UNCLASSIFIED = "未分类"

#: Separates subject from topic in a filter key. A topic id is only unique
#: within a subject, so "7 Equilibria" from 9701 and 9702 must not merge.
_KEY_SEP = " · "

_CSV_COLUMNS: list[str] = [
    "paper_id",
    "question_id",
    "topic_id",
    "topic_name",
    "score",
    "max_score",
    "comment",
    "timestamp",
]


def subject_id_of(paper_id: str) -> str:
    """``"9709_s25_qp_12"`` → ``"9709"``; the whole id if it has no parts."""
    return paper_id.split("_")[0] if "_" in paper_id else paper_id


def topic_key(record: MistakeRecord) -> str:
    """The filter key one record belongs to: ``"9701 · Equilibria"``."""
    name = record.topic_name or UNCLASSIFIED
    return f"{subject_id_of(record.paper_id)}{_KEY_SEP}{name}"


def mistakes_from_results(
    results: Iterable[QuestionResult],
    *,
    paper_id: str,
    topics: Mapping[str, str] | None = None,
    timestamp: datetime.datetime,
) -> list[MistakeRecord]:
    """Every question that did not get full marks, as records.

    ``topics`` maps topic_id → name (the same mapping the grader was given),
    used to resolve the id the model returned into a readable name. An id the
    mapping doesn't know keeps its id and gets no name, rather than being
    dropped — the tag is still evidence of what the model thought.

    The caller is responsible for the "only for a downloaded mark scheme"
    gate: ``paper_id`` is required here precisely because a record without a
    real one cannot be traced back to a subject, session or component.
    """
    topics = topics or {}
    records: list[MistakeRecord] = []
    for result in results:
        if result.total >= result.max:
            continue
        topic_id = result.topic or None
        records.append(
            MistakeRecord(
                paper_id=paper_id,
                question_id=result.question,
                topic_id=topic_id,
                topic_name=topics.get(topic_id) if topic_id else None,
                score=float(result.total),
                max_score=float(result.max),
                comment=result.comment,
                timestamp=timestamp,
            )
        )
    return records


def group_by_paper(
    records: Iterable[MistakeRecord],
) -> dict[str, list[MistakeRecord]]:
    """Records bucketed by paper, papers in first-seen order.

    First-seen rather than sorted: the store is append-only, so that is
    chronological, and the newest paper stays where the user left it.
    """
    grouped: dict[str, list[MistakeRecord]] = {}
    for record in records:
        grouped.setdefault(record.paper_id, []).append(record)
    return grouped


def distinct_topic_keys(records: Iterable[MistakeRecord]) -> list[str]:
    """Every filter key present, sorted, with 未分类 last.

    Unclassified rows are a leftover bucket rather than a topic, so they sit
    at the end of the filter list instead of wherever collation puts them.
    """
    keys = {topic_key(r) for r in records}
    return sorted(keys, key=lambda k: (k.endswith(UNCLASSIFIED), k))


def filter_by_topic(
    records: Iterable[MistakeRecord], keys: Collection[str]
) -> list[MistakeRecord]:
    """Keep records in any of ``keys``; an empty selection keeps everything.

    "Nothing ticked" means "no filter applied", not "show nothing" — the
    topic view opens with an empty selection.
    """
    items = list(records)
    if not keys:
        return items
    return [r for r in items if topic_key(r) in keys]


def to_csv(records: Iterable[MistakeRecord]) -> str:
    """Serialise records to CSV text, header included.

    Same columns and order as ``MistakeStore``'s own file, so an exported
    selection can be read back by anything that reads the store.
    """
    buffer = io.StringIO()
    # Excel opens \r\n rows fine and a fixed terminator keeps the output
    # identical on every platform, which is what the tests pin.
    writer = csv.DictWriter(
        buffer, fieldnames=_CSV_COLUMNS, lineterminator="\n"
    )
    writer.writeheader()
    for record in records:
        writer.writerow({
            "paper_id": record.paper_id,
            "question_id": record.question_id,
            "topic_id": record.topic_id or "",
            "topic_name": record.topic_name or "",
            "score": f"{record.score:g}",
            "max_score": f"{record.max_score:g}",
            "comment": record.comment,
            "timestamp": record.timestamp.isoformat(),
        })
    return buffer.getvalue()
