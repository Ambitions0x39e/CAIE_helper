"""专项练习: every question on chosen topics, across a range of sessions.

The 错题本 can only draw on papers that were graded, because a question's
topic is something the grader decides. Practice draws on papers never done,
so it classifies them itself — one vision call per paper, cached on disk —
and hands the picks to :mod:`modules.question_pdf`.

Nothing here may import ``app_web``.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Final, NamedTuple

from modules.downloader import QueryResult, query_available

if TYPE_CHECKING:
    from modules.marking.syllabus_parser import SyllabusInfo

#: CIE's sessions in calendar order within a year.
SEASONS: Final = "msw"


class Picked(NamedTuple):
    """One question chosen for the practice set — a ``QuestionRef``."""

    paper_id: str
    question_id: str


def _season_index(season: str) -> int:
    # ``in`` on a str is substring matching: "" and "ms" would pass a bare check.
    if len(season) != 1 or season not in SEASONS:
        raise ValueError(f"未知考季: {season!r}")
    return SEASONS.index(season)


def sessions_between(
    start_year: int, start_season: str, end_year: int, end_season: str
) -> list[tuple[str, str]]:
    """Every (year, season) from start to end inclusive, in calendar order."""
    start = start_year * 3 + _season_index(start_season)
    end = end_year * 3 + _season_index(end_season)
    return [(str(i // 3), SEASONS[i % 3]) for i in range(start, end + 1)]


def papers_in_range(
    subject: str,
    component: str,
    sessions: Sequence[tuple[str, str]],
    query: Callable[[str, str, str], QueryResult] = query_available,  # type: ignore[assignment]
) -> tuple[list[str], list[str]]:
    """The QP ids of *component* (``"4"`` → 41, 42, 43 …) in every session.

    A session that fails to list is a warning: the others are still worth
    practising from. A session that lists nothing (a future one, or a March
    session with no such component) contributes nothing, silently.
    """
    ids: list[str] = []
    warnings: list[str] = []
    for year, season in sessions:
        result = query(subject, year, season)
        if not result.success:
            warnings.append(f"{season}{year[-2:]}: {result.error}")
            continue
        ids.extend(sorted(
            e.paper_id for e in result.entries
            if e.kind == "qp" and e.paper_id.split("_")[3].startswith(component)
        ))
    return ids, warnings


def component_topics(info: SyllabusInfo | None, component: str) -> dict[str, str]:
    """Topic id → name for the topics the syllabus maps to *component*."""
    if info is None:
        return {}
    return {
        tid: info.topics[tid].name
        for tid in info.component_topics.get(component, [])
        if tid in info.topics
    }


def select(
    classified: Mapping[str, Mapping[str, Sequence[str]]],
    wanted: Collection[str],
) -> list[Picked]:
    """Every question tagged with any of *wanted*, paper by paper."""
    return [
        Picked(paper_id, question_id)
        for paper_id, questions in classified.items()
        for question_id, topics in questions.items()
        if any(t in wanted for t in topics)
    ]
