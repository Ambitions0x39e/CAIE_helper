"""Tests for ``core.storage.MistakeStore`` and ``core.models.MistakeRecord``.

Every test drives a real CSV under ``tmp_path`` — the store itself is never
faked, so a round trip really goes through pandas and back through Pydantic.
That is the point: the fields most likely to break in transit are the two
optional ones (an untagged question writes blanks, which must come back as
``None`` and not the string ``"nan"``) and the timestamp.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.models import MistakeRecord
from core.storage import MistakeStore

_TS = datetime.datetime(2026, 8, 20, 14, 30, 5)


def _record(
    question_id: str = "Q1",
    *,
    paper_id: str = "9709_s25_qp_12",
    topic_id: str | None = "1.2",
    topic_name: str | None = "Functions",
    score: float = 2.0,
    max_score: float = 5.0,
    comment: str = "漏了定义域",
    timestamp: datetime.datetime = _TS,
) -> MistakeRecord:
    return MistakeRecord(
        paper_id=paper_id,
        question_id=question_id,
        topic_id=topic_id,
        topic_name=topic_name,
        score=score,
        max_score=max_score,
        comment=comment,
        timestamp=timestamp,
    )


@pytest.fixture
def store(tmp_path: Path) -> MistakeStore:
    return MistakeStore(csv_path=tmp_path / "mistakes.csv")


# ── Round trip ────────────────────────────────────────────────────


def test_append_then_load_all_round_trips_every_field(
    store: MistakeStore,
) -> None:
    record = _record()
    store.append_many([record])

    loaded = store.load_all()

    assert len(loaded) == 1
    assert loaded[0] == record


def test_untagged_question_round_trips_as_none(store: MistakeStore) -> None:
    """No syllabus → blank topic columns → None, never the string "nan"."""
    store.append_many([_record(topic_id=None, topic_name=None)])

    loaded = store.load_all()[0]

    assert loaded.topic_id is None
    assert loaded.topic_name is None


def test_a_fresh_store_is_empty_not_missing(tmp_path: Path) -> None:
    store = MistakeStore(csv_path=tmp_path / "sub" / "mistakes.csv")

    assert store.load_all() == []
    assert (tmp_path / "sub" / "mistakes.csv").exists()


def test_append_many_keeps_existing_rows_and_order(
    store: MistakeStore,
) -> None:
    store.append_many([_record("Q1")])
    store.append_many([_record("Q2"), _record("Q3")])

    assert [r.question_id for r in store.load_all()] == ["Q1", "Q2", "Q3"]


def test_regrading_a_paper_appends_a_second_set_of_rows(
    store: MistakeStore,
) -> None:
    """Append-only, per the design doc: no dedup, no overwrite in v1."""
    store.append_many([_record("Q1", score=2.0)])
    store.append_many([_record("Q1", score=4.0)])

    assert [r.score for r in store.load_all()] == [2.0, 4.0]


# ── Update ────────────────────────────────────────────────────────


def test_update_at_replaces_only_that_row(store: MistakeStore) -> None:
    store.append_many([_record("Q1"), _record("Q2"), _record("Q3")])

    store.update_at(1, _record("Q2", topic_id="7", topic_name="Equilibria"))

    loaded = store.load_all()
    assert [r.question_id for r in loaded] == ["Q1", "Q2", "Q3"]
    assert loaded[1].topic_id == "7"
    assert loaded[1].topic_name == "Equilibria"
    assert loaded[0].topic_id == "1.2"
    assert loaded[2].topic_id == "1.2"


def test_update_at_can_clear_a_tag(store: MistakeStore) -> None:
    """A cleared topic must round-trip as None, not the string "nan"."""
    store.append_many([_record("Q1")])

    store.update_at(0, _record("Q1", topic_id=None, topic_name=None))

    assert store.load_all()[0].topic_id is None


@pytest.mark.parametrize("index", [-1, 1, 99])
def test_update_at_rejects_an_index_outside_the_store(
    store: MistakeStore, index: int
) -> None:
    """Silently appending or dropping a row would be worse than raising."""
    store.append_many([_record("Q1")])

    with pytest.raises(IndexError):
        store.update_at(index, _record("Q1"))

    assert len(store.load_all()) == 1


def test_update_at_indexes_match_load_all_after_a_regrade(
    store: MistakeStore,
) -> None:
    """Duplicated (paper_id, question_id) pairs are exactly why the store
    updates by position — the pair identifies two rows, the index one."""
    store.append_many([_record("Q1", score=2.0), _record("Q1", score=4.0)])

    store.update_at(0, _record("Q1", score=2.0, topic_id="3",
                               topic_name="Chemical bonding"))

    loaded = store.load_all()
    assert [r.score for r in loaded] == [2.0, 4.0]
    assert loaded[0].topic_id == "3"
    assert loaded[1].topic_id == "1.2"


# ── Delete ────────────────────────────────────────────────────────


def test_delete_removes_every_row_of_one_paper(store: MistakeStore) -> None:
    store.append_many([_record("Q1"), _record("Q2")])
    store.append_many([_record("Q1", paper_id="9709_s25_qp_13")])

    store.delete("9709_s25_qp_12")

    assert [r.paper_id for r in store.load_all()] == ["9709_s25_qp_13"]


def test_delete_can_target_a_single_question(store: MistakeStore) -> None:
    store.append_many([_record("Q1"), _record("Q2")])

    store.delete("9709_s25_qp_12", "Q1")

    assert [r.question_id for r in store.load_all()] == ["Q2"]


def test_delete_of_an_unknown_paper_raises(store: MistakeStore) -> None:
    store.append_many([_record("Q1")])

    with pytest.raises(KeyError):
        store.delete("9701_s25_qp_21")


# ── Model validation ──────────────────────────────────────────────


def test_score_above_max_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        _record(score=6.0, max_score=5.0)


def test_negative_score_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be negative"):
        _record(score=-1.0)


def test_blank_question_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _record("   ")
