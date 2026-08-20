"""Tests for ``modules.marking.mistakes`` — the 错题本's decisions.

Grouping, filtering and CSV export are the three things the tab does to the
store's rows before showing them, so each gets its own section here. The
conversion from a grading run is covered first, since it decides what ever
reaches the store: only questions that lost marks, tagged with the name the
grader's own topic list gives the id.
"""
from __future__ import annotations

import datetime

import pytest

from core.models import MistakeRecord
from modules.marking.grader import MarkDetail, QuestionResult
from modules.marking.mistakes import (
    UNCLASSIFIED,
    distinct_topic_keys,
    filter_by_topic,
    group_by_paper,
    mistakes_from_results,
    subject_id_of,
    to_csv,
    topic_key,
)

_TS = datetime.datetime(2026, 8, 20, 14, 30, 5)
_TOPICS = {"1.1": "Quadratics", "1.2": "Functions"}


def _result(
    question: str,
    total: int,
    max_marks: int,
    topic: str | None = None,
    comment: str = "",
) -> QuestionResult:
    return QuestionResult(
        question=question,
        marks=[MarkDetail(code="M1", awarded=total > 0, reason="…")],
        total=total,
        max=max_marks,
        comment=comment,
        topic=topic,
    )


def _record(
    question_id: str = "Q1",
    *,
    paper_id: str = "9709_s25_qp_12",
    topic_id: str | None = "1.2",
    topic_name: str | None = "Functions",
    score: float = 2.0,
    max_score: float = 5.0,
    comment: str = "",
) -> MistakeRecord:
    return MistakeRecord(
        paper_id=paper_id,
        question_id=question_id,
        topic_id=topic_id,
        topic_name=topic_name,
        score=score,
        max_score=max_score,
        comment=comment,
        timestamp=_TS,
    )


# ── Grading run → records ─────────────────────────────────────────


class TestMistakesFromResults:
    def test_only_questions_that_lost_marks_become_records(self) -> None:
        records = mistakes_from_results(
            [
                _result("Q1", 5, 5, "1.1"),   # full marks — not a mistake
                _result("Q2", 2, 5, "1.2"),
                _result("Q3", 0, 4, "1.1"),
            ],
            paper_id="9709_s25_qp_12",
            topics=_TOPICS,
            timestamp=_TS,
        )

        assert [r.question_id for r in records] == ["Q2", "Q3"]
        assert [r.score for r in records] == [2.0, 0.0]
        assert [r.max_score for r in records] == [5.0, 4.0]

    def test_topic_id_is_resolved_to_its_name(self) -> None:
        record = mistakes_from_results(
            [_result("Q1", 1, 5, "1.2")],
            paper_id="9709_s25_qp_12",
            topics=_TOPICS,
            timestamp=_TS,
        )[0]

        assert record.topic_id == "1.2"
        assert record.topic_name == "Functions"

    def test_an_untagged_question_still_becomes_a_record(self) -> None:
        record = mistakes_from_results(
            [_result("Q1", 1, 5, None)],
            paper_id="9709_s25_qp_12",
            topics=_TOPICS,
            timestamp=_TS,
        )[0]

        assert record.topic_id is None
        assert record.topic_name is None

    def test_an_unknown_topic_id_keeps_the_id_without_a_name(self) -> None:
        """The model's answer is kept as evidence, not silently dropped."""
        record = mistakes_from_results(
            [_result("Q1", 1, 5, "9.9")],
            paper_id="9709_s25_qp_12",
            topics=_TOPICS,
            timestamp=_TS,
        )[0]

        assert record.topic_id == "9.9"
        assert record.topic_name is None

    def test_a_clean_paper_produces_nothing(self) -> None:
        assert (
            mistakes_from_results(
                [_result("Q1", 5, 5), _result("Q2", 3, 3)],
                paper_id="9709_s25_qp_12",
                timestamp=_TS,
            )
            == []
        )


# ── Grouping ──────────────────────────────────────────────────────


class TestGroupByPaper:
    def test_rows_are_bucketed_by_paper_in_first_seen_order(self) -> None:
        records = [
            _record("Q1", paper_id="9709_s25_qp_12"),
            _record("Q1", paper_id="9701_s25_qp_21"),
            _record("Q2", paper_id="9709_s25_qp_12"),
        ]

        grouped = group_by_paper(records)

        assert list(grouped) == ["9709_s25_qp_12", "9701_s25_qp_21"]
        assert [r.question_id for r in grouped["9709_s25_qp_12"]] == [
            "Q1", "Q2",
        ]
        assert len(grouped["9701_s25_qp_21"]) == 1

    def test_a_regraded_paper_keeps_both_sets_in_one_bucket(self) -> None:
        grouped = group_by_paper([_record("Q1"), _record("Q1")])

        assert len(grouped["9709_s25_qp_12"]) == 2

    def test_no_records_is_an_empty_mapping(self) -> None:
        assert group_by_paper([]) == {}


# ── Filtering ─────────────────────────────────────────────────────


class TestFilterByTopic:
    def test_selected_keys_are_kept(self) -> None:
        records = [
            _record("Q1", topic_name="Functions"),
            _record("Q2", topic_name="Series"),
            _record("Q3", topic_name="Functions"),
        ]

        kept = filter_by_topic(records, {"9709 · Functions"})

        assert [r.question_id for r in kept] == ["Q1", "Q3"]

    def test_an_empty_selection_means_no_filter(self) -> None:
        records = [_record("Q1"), _record("Q2", topic_name="Series")]

        assert filter_by_topic(records, set()) == records

    def test_the_same_topic_name_in_two_subjects_does_not_merge(self) -> None:
        """topic_id is only unique within a subject — so is topic_name."""
        chem = _record(
            "Q1", paper_id="9701_s25_qp_21", topic_id="7",
            topic_name="Equilibria",
        )
        phys = _record(
            "Q1", paper_id="9702_s25_qp_21", topic_id="7",
            topic_name="Equilibria",
        )

        kept = filter_by_topic([chem, phys], {"9701 · Equilibria"})

        assert kept == [chem]

    def test_untagged_rows_filter_as_unclassified(self) -> None:
        tagged = _record("Q1")
        untagged = _record("Q2", topic_id=None, topic_name=None)

        assert topic_key(untagged) == f"9709 · {UNCLASSIFIED}"
        assert filter_by_topic([tagged, untagged], {f"9709 · {UNCLASSIFIED}"}) == [
            untagged
        ]

    def test_distinct_keys_are_sorted_with_unclassified_last(self) -> None:
        records = [
            _record("Q1", topic_name=None, topic_id=None),
            _record("Q2", topic_name="Series"),
            _record("Q3", topic_name="Functions"),
            _record("Q4", topic_name="Series"),
        ]

        assert distinct_topic_keys(records) == [
            "9709 · Functions",
            "9709 · Series",
            f"9709 · {UNCLASSIFIED}",
        ]

    @pytest.mark.parametrize(
        ("paper_id", "expected"),
        [("9709_s25_qp_12", "9709"), ("9701", "9701")],
    )
    def test_subject_id_of(self, paper_id: str, expected: str) -> None:
        assert subject_id_of(paper_id) == expected


# ── CSV export ────────────────────────────────────────────────────


class TestToCsv:
    def test_header_and_one_row(self) -> None:
        text = to_csv([_record("Q1", comment="漏了定义域")])

        assert text.splitlines()[0] == (
            "paper_id,question_id,topic_id,topic_name,score,max_score,"
            "comment,timestamp"
        )
        assert text.splitlines()[1] == (
            "9709_s25_qp_12,Q1,1.2,Functions,2,5,漏了定义域,"
            "2026-08-20T14:30:05"
        )

    def test_missing_topics_export_as_empty_cells_not_none(self) -> None:
        text = to_csv([_record("Q1", topic_id=None, topic_name=None)])

        assert text.splitlines()[1].startswith("9709_s25_qp_12,Q1,,,")
        assert "None" not in text

    def test_a_comment_with_a_comma_is_quoted(self) -> None:
        text = to_csv([_record("Q1", comment="第一步对, 第二步错")])

        assert '"第一步对, 第二步错"' in text

    def test_no_records_still_exports_the_header(self) -> None:
        assert to_csv([]).strip().startswith("paper_id,question_id")

    def test_every_row_is_exported(self) -> None:
        text = to_csv([_record("Q1"), _record("Q2"), _record("Q3")])

        assert len(text.strip().splitlines()) == 4
