from __future__ import annotations

import datetime

import pandas as pd

from core.models import PaperRecord
from modules.visualizer import PaperVisualizer


def _completed(paper_id: str, raw: float, total: float) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        status="Completed",
        score_raw=raw,
        score_total=total,
        timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
    )


def test_render_paper_type_metrics_shows_three_columns(monkeypatch):
    """_render_paper_type_metrics renders 3 columns with Attempts, Average, Best."""
    calls: list[tuple[str, object]] = []

    class FakeCol:
        def metric(self, label: str, value: object) -> None:
            calls.append((label, value))

    monkeypatch.setattr(
        "streamlit.columns",
        lambda n: [FakeCol(), FakeCol(), FakeCol()],
    )

    records = [_completed("9702_s23_qp_11", 60, 100), _completed("9702_s24_qp_11", 80, 100)]
    viz = PaperVisualizer(records=records)

    df = pd.DataFrame([{"percentage": 60.0}, {"percentage": 80.0}])
    viz._render_paper_type_metrics(df)

    labels = [c[0] for c in calls]
    assert "Attempts" in labels
    assert "Average" in labels
    assert "Best" in labels

    attempts_val = next(v for l, v in calls if l == "Attempts")
    assert attempts_val == 2

    avg_val = next(v for l, v in calls if l == "Average")
    assert avg_val == "70.0%"

    best_val = next(v for l, v in calls if l == "Best")
    assert best_val == "80.0%"
