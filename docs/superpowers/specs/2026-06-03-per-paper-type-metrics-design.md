# Per-Paper-Type Average Metrics in Analytics Tab

**Date:** 2026-06-03

## Summary

Add three metric cards (Attempts, Average %, Best %) inside each per-paper-type tab in the Analytics tab, displayed between the "Paper X — Trend" heading and the line chart.

## Current behaviour

Within the Analytics tab, each syllabus expander shows:
- A syllabus-level summary row (Papers, Average, Best) across all paper types combined
- Per-paper-type tabs (Paper 1, Paper 2, ...), each containing:
  - A trend line chart
  - A score table

There are no per-paper-type summary metrics.

## Desired behaviour

Within each per-paper-type tab the layout becomes:

```
Paper 1 — Trend
[ Attempts: N ] [ Average: XX.X% ] [ Best: XX.X% ]
[line chart]
[score table]
```

The syllabus-level summary row and all other existing structure remain unchanged.

## Implementation

### File changed

`modules/visualizer.py` — only this file changes.

### New method: `_render_paper_type_metrics`

```python
def _render_paper_type_metrics(self, df: pd.DataFrame) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Attempts", len(df))
    col2.metric("Average", f"{df['percentage'].mean():.1f}%")
    col3.metric("Best", f"{df['percentage'].max():.1f}%")
```

### Modified method: `_render_trend_chart`

Add an optional boolean parameter `show_metrics: bool = False`.
After the heading `st.markdown(...)` and before the early-return / chart body, call `_render_paper_type_metrics(df)` if `show_metrics` is `True`.

```python
def _render_trend_chart(
    self,
    df: pd.DataFrame,
    label: str = "Score Trend",
    show_metrics: bool = False,
) -> None:
    st.markdown(f"**{label} — Trend**")
    if show_metrics:
        self._render_paper_type_metrics(df)
    if len(df) < _MIN_PAPERS_FOR_TREND:
        st.caption("Need at least 2 attempts to draw a trend line.")
        return
    ...
```

### Modified call site: `_render_syllabus_section`

Pass `show_metrics=True` when calling `_render_trend_chart` inside the per-paper-type tab loop:

```python
self._render_trend_chart(type_df, label=f"Paper {digit}", show_metrics=True)
```

The fallback `_render_trend_chart(syl_df, label="All Papers")` call (when no paper type digits are found) is unchanged — `show_metrics` defaults to `False`.

## Edge cases

- **1 attempt:** Average == Best == that score. Metrics cards render normally; trend chart shows the "Need at least 2 attempts" caption.
- **No paper type tabs:** The "All Papers" fallback path has no metrics_df — unchanged behaviour.
- **All scores identical:** Mean == max, both cards show the same value. No special handling needed.

## Non-changes

- `PaperRecord`, `CSVStore`, `core/models.py` — untouched.
- `_extract_paper_type_digit` — untouched.
- Syllabus-level summary metrics row — untouched.
- Overall metrics section — untouched.
