"""Tests for the attempt rows — ``core.storage.AttemptStore`` and
``modules.marking.attempts.attempts_from_results``.

The store is driven through a real CSV under ``tmp_path``; ``error_type`` is
the field most likely to break in transit, since a blank cell must come back
as None and not fail the Literal.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.models import AttemptRecord
from core.storage import AttemptStore
from modules.marking.attempts import attempts_from_results
from modules.marking.grader import QuestionResult

_TS = datetime.datetime(2026, 9, 24, 10, 0, 0)


def _result(
    question: str, total: int, max_marks: int,
    topic: str | None = "7", error_type: str | None = None,
) -> QuestionResult:
    return QuestionResult(
        question=question, marks=[], total=total, max=max_marks,
        topic=topic, error_type=error_type,  # type: ignore[arg-type]
    )


def test_store_round_trips_a_classified_and_an_unclassified_row(
    tmp_path: Path,
) -> None:
    store = AttemptStore(csv_path=tmp_path / "attempts.csv")
    rows = attempts_from_results(
        [_result("1", 1, 3, error_type="slip"), _result("2", 3, 3, topic=None)],
        paper_id="9701_s25_qp_22",
        topics={"7": "Equilibria"},
        timestamp=_TS,
    )

    store.append_many(rows)

    assert store.load_all() == rows
    assert store.load_all()[1].error_type is None


def test_a_fresh_store_is_empty_not_missing(tmp_path: Path) -> None:
    assert AttemptStore(csv_path=tmp_path / "attempts.csv").load_all() == []


def test_an_unknown_error_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AttemptRecord(
            paper_id="p", question_id="1", score=0.0, max_score=1.0,
            error_type="vibes",  # type: ignore[arg-type]
            timestamp=_TS,
        )


def test_every_question_becomes_an_attempt() -> None:
    rows = attempts_from_results(
        [_result("1", 3, 3), _result("2", 0, 2, error_type="blank")],
        paper_id="9701_s25_qp_22",
        timestamp=_TS,
    )

    assert [(r.question_id, r.score, r.max_score) for r in rows] == [
        ("1", 3.0, 3.0),
        ("2", 0.0, 2.0),
    ]


def test_full_marks_carry_no_error_type_even_after_an_override() -> None:
    """Adjusted up to full marks, the question lost nothing to classify."""
    rows = attempts_from_results(
        [_result("1", 1, 3, error_type="slip"), _result("2", 1, 3, error_type="slip")],
        paper_id="9701_s25_qp_22",
        scores={"1": 3},
        timestamp=_TS,
    )

    assert [(r.score, r.error_type) for r in rows] == [(3.0, None), (1.0, "slip")]


def test_a_correction_is_recorded_beside_what_the_model_said() -> None:
    model = [_result("1", 1, 3, "7", "slip"), _result("2", 0, 3, "7", "concept")]
    corrected = [
        model[0].model_copy(update={"topic": "5", "error_type": "misread"}),
        model[1],
    ]

    rows = attempts_from_results(
        corrected, model_results=model, paper_id="9701_s25_qp_22", timestamp=_TS,
    )

    assert [
        (r.topic_id, r.model_topic_id, r.error_type, r.model_error_type)
        for r in rows
    ] == [("5", "7", "misread", "slip"), ("7", "7", "concept", "concept")]


def test_without_model_results_the_run_counts_as_uncorrected() -> None:
    row = attempts_from_results(
        [_result("1", 1, 3, "7", "slip")], paper_id="9701_s25_qp_22", timestamp=_TS,
    )[0]

    assert (row.model_topic_id, row.model_error_type) == ("7", "slip")


def test_full_marks_drop_the_models_error_type_too() -> None:
    """Otherwise a question adjusted up to full would read as a correction."""
    row = attempts_from_results(
        [_result("1", 1, 3, error_type="slip")],
        paper_id="9701_s25_qp_22",
        scores={"1": 3},
        timestamp=_TS,
    )[0]

    assert (row.error_type, row.model_error_type) == (None, None)


def test_a_file_without_the_model_columns_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "attempts.csv"
    path.write_text(
        "paper_id,question_id,topic_id,topic_name,error_type,score,max_score,timestamp\n"
        "9701_s25_qp_22,1,7,Equilibria,slip,1.0,3.0,2026-09-24T10:00:00\n",
        encoding="utf-8",
    )

    row = AttemptStore(csv_path=path).load_all()[0]

    assert (row.error_type, row.model_topic_id, row.model_error_type) == (
        "slip", None, None,
    )
