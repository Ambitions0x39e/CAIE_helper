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


def test_render_trend_chart_merges_metrics_into_heading(monkeypatch):
    """_render_trend_chart with show_metrics=True renders title + Attempts/Average/Best inline."""
    markdowns: list[str] = []
    monkeypatch.setattr(
        "streamlit.markdown",
        lambda text, unsafe_allow_html=False: markdowns.append(text),
    )
    monkeypatch.setattr("streamlit.caption", lambda text: None)
    monkeypatch.setattr("streamlit.line_chart", lambda *a, **kw: None)

    records = [_completed("9702_s23_qp_11", 60, 100), _completed("9702_s24_qp_11", 80, 100)]
    viz = PaperVisualizer(records=records)

    df = pd.DataFrame(
        [{"percentage": 60.0, "attempt": 1}, {"percentage": 80.0, "attempt": 2}]
    )
    viz._render_trend_chart(df, label="Paper 1", show_metrics=True)

    assert markdowns, "Expected at least one st.markdown call"
    heading = markdowns[0]
    assert "Paper 1" in heading
    assert "Attempts: 2" in heading
    assert "Average: 70.0%" in heading
    assert "Best: 80.0%" in heading
    assert "Trend" not in heading
