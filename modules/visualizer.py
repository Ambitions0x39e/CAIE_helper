from __future__ import annotations

import re
from typing import Final

import pandas as pd
import streamlit as st

from core.config_store import ConfigStore
from core.models import PaperRecord

_MIN_PAPERS_FOR_TREND: Final[int] = 2


def _extract_syllabus_id(paper_id: str) -> str:
    """Extract 4-char syllabus ID, e.g. '9702_s23_qp_11' → '9702'."""
    return paper_id[:4]


def _extract_paper_type_digit(paper_id: str) -> str | None:
    """
    Extract the variant digit x from qp_x1 pattern.
    e.g. '9702_s23_qp_11' → '1'
         '9702_s23_qp_21' → '2'
    Returns None if pattern doesn't match.
    """
    match = re.search(r"_qp_(\d)", paper_id)
    return match.group(1) if match else None


class PaperVisualizer:
    """
    Renders analytics for completed PaperRecords inside a Streamlit page.
    Grouped by syllabus ID (first 4 chars of paper_id), with per-paper-type trend graphs.
    """

    def __init__(self, records: list[PaperRecord], config_store: ConfigStore | None = None) -> None:
        self._completed = [r for r in records if r.status == "Completed"]
        self._config = config_store or ConfigStore()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def render(self) -> None:
        st.subheader("📊 Analytics")

        if not self._completed:
            st.info("No completed papers yet. Submit a score to see analytics.")
            return

        df = self._build_dataframe()
        syllabus_ids = sorted(df["syllabus_id"].unique())
        syllabus_config = self._config.load_syllabus_config()

        # Overall summary metrics across all syllabuses
        self._render_overall_metrics(df)
        st.divider()

        # Per-syllabus sections
        for syllabus_id in syllabus_ids:
            label = syllabus_config.get(syllabus_id, {}).get("name", syllabus_id)
            with st.expander(f"📚 {syllabus_id} — {label}", expanded=True):
                syl_df = df[df["syllabus_id"] == syllabus_id].copy()
                self._render_syllabus_section(syl_df, syllabus_id, syllabus_config)

    # ------------------------------------------------------------------
    # Private: build DataFrame
    # ------------------------------------------------------------------

    def _build_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "paper_id": r.paper_id,
                "syllabus_id": _extract_syllabus_id(r.paper_id),
                "paper_type_digit": _extract_paper_type_digit(r.paper_id),
                "percentage": r.percentage,
                "score_raw": r.score_raw,
                "score_total": r.score_total,
                "timestamp": r.timestamp,
            }
            for r in self._completed
            if r.percentage is not None
        ]
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
        return df

    # ------------------------------------------------------------------
    # Private: overall metrics
    # ------------------------------------------------------------------

    def _render_overall_metrics(self, df: pd.DataFrame) -> None:
        st.markdown("**Overall**")
        avg = df["percentage"].mean()
        total = len(df)
        best = df["percentage"].max()
        latest = df["percentage"].iloc[-1]
        delta = (
            latest - df["percentage"].iloc[-2]
            if total >= _MIN_PAPERS_FOR_TREND
            else None
        )
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Completed", total)
        col2.metric("Overall Average", f"{avg:.1f}%")
        col3.metric("Best Score", f"{best:.1f}%")
        col4.metric(
            "Latest Score",
            f"{latest:.1f}%",
            delta=f"{delta:+.1f}%" if delta is not None else None,
        )

    # ------------------------------------------------------------------
    # Private: per-syllabus section
    # ------------------------------------------------------------------

    def _render_syllabus_section(
        self,
        syl_df: pd.DataFrame,
        syllabus_id: str,
        syllabus_config: dict[str, dict[str, str | dict[str, str]]],
    ) -> None:
        avg = syl_df["percentage"].mean()
        best = syl_df["percentage"].max()
        total = len(syl_df)

        col1, col2, col3 = st.columns(3)
        col1.metric("Papers", total)
        col2.metric("Average", f"{avg:.1f}%")
        col3.metric("Best", f"{best:.1f}%")

        st.divider()

        paper_type_digits = sorted(syl_df["paper_type_digit"].dropna().unique())

        if not paper_type_digits:
            self._render_trend_chart(syl_df, label="All Papers")
        else:
            syl_entry = syllabus_config.get(syllabus_id, {})
            pt_raw = syl_entry.get("paper_types", {})
            paper_types_config: dict[str, str] = pt_raw if isinstance(pt_raw, dict) else {}
            tabs = st.tabs(
                [
                    f"Paper {d} — {paper_types_config.get(d, 'Unknown')}"
                    for d in paper_type_digits
                ]
            )
            for tab, digit in zip(tabs, paper_type_digits):
                with tab:
                    type_df = syl_df[syl_df["paper_type_digit"] == digit].copy()
                    type_df = type_df.reset_index(drop=True)
                    type_df["attempt"] = type_df.index + 1
                    self._render_trend_chart(type_df, label=f"Paper {digit}", show_metrics=True)
                    self._render_score_table(type_df)

    # ------------------------------------------------------------------
    # Private: chart + table
    # ------------------------------------------------------------------

    def _render_trend_chart(
        self,
        df: pd.DataFrame,
        label: str = "Score Trend",
        show_metrics: bool = False,
    ) -> None:
        if show_metrics:
            attempts = len(df)
            avg = df["percentage"].mean()
            best = df["percentage"].max()
            st.markdown(
                f"**{label}** &nbsp;<small style='color:gray'>"
                f"Attempts: {attempts} &nbsp;·&nbsp; "
                f"Average: {avg:.1f}% &nbsp;·&nbsp; "
                f"Best: {best:.1f}%</small>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"**{label}**")
        if len(df) < _MIN_PAPERS_FOR_TREND:
            st.caption("Need at least 2 attempts to draw a trend line.")
            return
        chart_df = df.copy()
        if "attempt" not in chart_df.columns:
            chart_df["attempt"] = range(1, len(chart_df) + 1)
        chart_df = chart_df.set_index("attempt")[["percentage"]]
        chart_df.index.name = "Attempt #"
        st.line_chart(chart_df, y="percentage", y_label="Score (%)", x_label="Attempt #")

    def _render_score_table(self, df: pd.DataFrame) -> None:
        display = df[["paper_id", "score_raw", "score_total", "percentage", "timestamp"]].copy()
        display.columns = ["Paper ID", "Raw", "Total", "%", "Completed At"]
        display["Completed At"] = display["Completed At"].dt.strftime("%Y-%m-%d %H:%M UTC")
        st.dataframe(display, width="stretch", hide_index=True)
