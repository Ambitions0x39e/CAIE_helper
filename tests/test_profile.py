"""Tests for ``modules.profile`` — the numbers the tutor notes are written from."""
from __future__ import annotations

import datetime

from core.models import AttemptRecord
from modules.profile import component_profile, latest_attempts

_T0 = datetime.datetime(2026, 9, 1, 12, 0)
_T1 = datetime.datetime(2026, 9, 2, 12, 0)


def _a(
    question: str, score: float, max_score: float, topic: str | None = "7",
    *, paper: str = "9701_s25_qp_22", error: str | None = None,
    at: datetime.datetime = _T0,
) -> AttemptRecord:
    return AttemptRecord(
        paper_id=paper, question_id=question, topic_id=topic,
        topic_name={"7": "Equilibria", "5": "Energetics"}.get(topic or ""),
        error_type=error,  # type: ignore[arg-type]
        score=score, max_score=max_score, timestamp=at,
    )


def test_a_regraded_paper_counts_once_at_its_latest_marks() -> None:
    rows = [_a("1", 0, 4, at=_T0), _a("1", 3, 4, at=_T1)]

    assert [r.score for r in latest_attempts(rows)] == [3.0]
    profile = component_profile(rows, "9701", "2")
    assert profile is not None
    assert profile.topics[0].questions == 1
    assert profile.topics[0].lost == 1.0


def test_topics_are_ranked_by_loss_rate_with_their_error_breakdown() -> None:
    rows = [
        _a("1", 4, 4, "5"),
        _a("2", 1, 5, "5", error="slip"),
        _a("3", 0, 2, "7", error="concept"),
        _a("4", 1, 2, "7", error="misread"),
    ]

    profile = component_profile(rows, "9701", "2")

    assert profile is not None
    stats = [(t.topic_name, t.questions, t.lost, t.max_score) for t in profile.topics]
    assert stats == [
        ("Equilibria", 2, 3.0, 4.0),
        ("Energetics", 2, 4.0, 9.0),
    ]
    assert profile.topics[0].errors == {"concept": 2.0, "misread": 1.0}
    assert profile.errors == {"slip": 4.0, "concept": 2.0, "misread": 1.0}
    assert profile.papers == 1


def test_only_the_asked_syllabus_and_component_count() -> None:
    rows = [
        _a("1", 0, 4),
        _a("1", 0, 4, paper="9701_s25_qp_42"),
        _a("1", 0, 4, paper="9702_s25_qp_22"),
    ]

    profile = component_profile(rows, "9701", "2")

    assert profile is not None
    assert profile.topics[0].questions == 1
    assert component_profile(rows, "9701", "3") is None
