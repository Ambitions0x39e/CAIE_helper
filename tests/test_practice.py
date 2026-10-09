"""Tests for ``modules.practice`` — 专项练习."""
from __future__ import annotations

import pytest

from modules.downloader import QueryEntry, QueryResult
from modules.marking.syllabus_parser import SyllabusInfo, SyllabusTopic
from modules.practice import (
    Picked,
    component_topics,
    papers_in_range,
    select,
    sessions_between,
)

# -- sessions_between --------------------------------------------------------


def test_a_range_runs_through_every_season_in_between() -> None:
    assert sessions_between(2023, "s", 2024, "w") == [
        ("2023", "s"), ("2023", "w"),
        ("2024", "m"), ("2024", "s"), ("2024", "w"),
    ]


def test_a_single_session_range_is_that_session() -> None:
    assert sessions_between(2024, "m", 2024, "m") == [("2024", "m")]


def test_a_backwards_range_is_empty() -> None:
    assert sessions_between(2024, "w", 2023, "s") == []


def test_an_unknown_season_is_refused() -> None:
    with pytest.raises(ValueError):
        sessions_between(2023, "x", 2024, "w")


# -- papers_in_range ---------------------------------------------------------


def _listing(*ids: str) -> QueryResult:
    return QueryResult(success=True, entries=[
        QueryEntry(paper_id=i, kind="qp" if "_qp_" in i else "other")
        for i in ids
    ])


def test_only_the_wanted_components_question_papers_are_taken() -> None:
    listings = {
        ("2023", "s"): _listing(
            "9709_s23_qp_41", "9709_s23_ms_41", "9709_s23_qp_42",
            "9709_s23_qp_31", "9709_s23_qp_43",
        ),
        ("2023", "w"): _listing("9709_w23_qp_41"),
    }
    ids, warnings = papers_in_range(
        "9709", "4", [("2023", "s"), ("2023", "w")],
        query=lambda _s, y, season: listings[(y, season)],
    )
    assert ids == [
        "9709_s23_qp_41", "9709_s23_qp_42", "9709_s23_qp_43", "9709_w23_qp_41",
    ]
    assert warnings == []


def test_a_session_that_fails_to_list_is_a_warning_not_an_abort() -> None:
    def query(_s: str, year: str, season: str) -> QueryResult:
        if season == "w":
            return QueryResult(success=False, error="HTTP 500")
        return _listing("9709_s23_qp_42")

    ids, warnings = papers_in_range(
        "9709", "4", [("2023", "s"), ("2023", "w")], query=query,
    )
    assert ids == ["9709_s23_qp_42"]
    assert warnings == ["w23: HTTP 500"]


# -- component_topics --------------------------------------------------------


def _syllabus() -> SyllabusInfo:
    return SyllabusInfo(
        subject_id="9709",
        topics={
            "4.1": SyllabusTopic(topic_id="4.1", name="Forces and equilibrium"),
            "4.2": SyllabusTopic(topic_id="4.2", name="Kinematics"),
            "1.1": SyllabusTopic(topic_id="1.1", name="Quadratics"),
        },
        component_topics={"4": ["4.1", "4.2"], "1": ["1.1"]},
    )


def test_component_topics_are_the_ones_the_syllabus_maps_to_it() -> None:
    assert component_topics(_syllabus(), "4") == {
        "4.1": "Forces and equilibrium", "4.2": "Kinematics",
    }


def test_no_syllabus_or_an_unmapped_component_has_no_topics() -> None:
    assert component_topics(None, "4") == {}
    assert component_topics(_syllabus(), "6") == {}


# -- select ------------------------------------------------------------------


def test_any_matching_topic_selects_the_question_in_paper_order() -> None:
    classified = {
        "9709_s23_qp_41": {"1": ["4.1"], "2": ["4.2", "4.5"], "3": []},
        "9709_w23_qp_41": {"1": ["4.5"], "4": ["4.2"]},
    }
    assert select(classified, {"4.2", "4.5"}) == [
        Picked("9709_s23_qp_41", "2"),
        Picked("9709_w23_qp_41", "1"),
        Picked("9709_w23_qp_41", "4"),
    ]


@pytest.mark.parametrize("season", ["", "ms", "M"])
def test_a_season_must_be_exactly_one_known_code(season: str) -> None:
    with pytest.raises(ValueError):
        sessions_between(2023, season, 2024, "w")
