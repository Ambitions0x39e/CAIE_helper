"""Score submission must never write a record load_all() can't read back.

Regression: PaperManager.submit_score built its updated record with
``model_copy(update=...)``, which skips every Pydantic validator. A score
above the paper's total was therefore written to data.csv without complaint —
and load_all(), which *does* validate, then raised on that row forever after,
taking the Analytics and Manage tabs down with it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.models import PaperRecord
from core.storage import CSVStore
from modules.manager import PaperManager, ScoreUpdate


@pytest.fixture
def store(tmp_path: Path) -> CSVStore:
    s = CSVStore(csv_path=tmp_path / "data.csv")
    s.save_all([PaperRecord(paper_id="9709_s24_qp_12", status="Pending")])
    return s


class TestScoreUpdateValidation:
    """The first gate: the input schema itself."""

    def test_rejects_score_above_total(self) -> None:
        with pytest.raises(ValidationError, match="cannot exceed"):
            ScoreUpdate(
                paper_id="9709_s24_qp_12", score_raw=99, score_total=50,
            )

    def test_rejects_zero_total(self) -> None:
        with pytest.raises(ValidationError, match="greater than zero"):
            ScoreUpdate(
                paper_id="9709_s24_qp_12", score_raw=0, score_total=0,
            )

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="cannot be negative"):
            ScoreUpdate(
                paper_id="9709_s24_qp_12", score_raw=-1, score_total=50,
            )

    def test_accepts_exactly_100_percent(self) -> None:
        update = ScoreUpdate(
            paper_id="9709_s24_qp_12", score_raw=50, score_total=50,
        )
        assert update.score_raw == update.score_total


class TestSubmitScore:
    def test_happy_path_round_trips(self, store: CSVStore) -> None:
        result = PaperManager(store=store).submit_score(ScoreUpdate(
            paper_id="9709_s24_qp_12", score_raw=42, score_total=50,
        ))
        assert result.success, result.error

        # The whole point: the store is still readable afterwards.
        reloaded = store.load_all()
        assert reloaded[0].status == "Completed"
        assert reloaded[0].percentage == 84.0

    def test_stamps_a_timestamp(self, store: CSVStore) -> None:
        # The Mark tab used to hand-roll this update and skip the timestamp,
        # leaving graded papers Completed but undated.
        PaperManager(store=store).submit_score(ScoreUpdate(
            paper_id="9709_s24_qp_12", score_raw=42, score_total=50,
        ))
        assert store.load_all()[0].timestamp is not None

    def test_impossible_score_cannot_reach_the_csv(
        self, store: CSVStore,
    ) -> None:
        # model_construct bypasses ScoreUpdate's own validation, standing in
        # for any caller that skips the input schema. submit_score must still
        # refuse rather than corrupt the store.
        rogue = ScoreUpdate.model_construct(
            paper_id="9709_s24_qp_12", score_raw=99.0, score_total=50.0,
        )
        result = PaperManager(store=store).submit_score(rogue)

        assert not result.success
        assert result.error is not None
        assert "cannot exceed" in result.error

        # And the store is untouched and still loadable — the real failure
        # mode was a write that only exploded on the *next* read.
        records = store.load_all()
        assert records[0].status == "Pending"
        assert records[0].score_raw is None

    def test_missing_paper_is_reported_not_raised(
        self, store: CSVStore,
    ) -> None:
        result = PaperManager(store=store).submit_score(ScoreUpdate(
            paper_id="0000_s24_qp_99", score_raw=1, score_total=50,
        ))
        assert not result.success
        assert "not found" in (result.error or "")
