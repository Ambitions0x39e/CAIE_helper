from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

import flet as ft
import pandas as pd
from flet import canvas as cv

from app_flet.components.widgets import metric_card
from core.config_store import ConfigStore

if TYPE_CHECKING:
    from app_flet.state import AppState

_MIN_FOR_TREND = 2
_CHART_HEIGHT = 350
_CHART_LEFT_PAD = 40
_CHART_RIGHT_PAD = 20
_CHART_TOP_PAD = 10
_CHART_BOTTOM_PAD = 30
_ACCENT_COLOR = "#1976D2"


def _extract_syllabus_id(paper_id: str) -> str:
    return paper_id[:4]


def _extract_paper_type_digit(paper_id: str) -> str | None:
    match = re.search(r"_qp_(\d)", paper_id)
    return match.group(1) if match else None


def _trend_chart(
    df: pd.DataFrame,
    width: int = 600,
) -> ft.Control:
    if len(df) < _MIN_FOR_TREND:
        return ft.Text(
            "至少需要 2 次成绩才能绘制趋势图",
            size=12,
            color=ft.Colors.GREY,
            italic=True,
        )

    plot_w = width - _CHART_LEFT_PAD - _CHART_RIGHT_PAD
    plot_h = _CHART_HEIGHT - _CHART_TOP_PAD - _CHART_BOTTOM_PAD
    y_max = 105.0
    attempts = df["attempt"].tolist()
    percentages = df["percentage"].tolist()
    n = len(attempts)

    def _x(i: int) -> float:
        if n == 1:
            return _CHART_LEFT_PAD + plot_w / 2
        return _CHART_LEFT_PAD + (plot_w * i / (n - 1))

    def _y(pct: float) -> float:
        return _CHART_TOP_PAD + plot_h * (1 - pct / y_max)

    shapes: list[cv.Shape] = []

    # Axes
    shapes.append(cv.Line(
        _CHART_LEFT_PAD, _CHART_TOP_PAD,
        _CHART_LEFT_PAD, _CHART_TOP_PAD + plot_h,
        paint=ft.Paint(color=ft.Colors.GREY_300, stroke_width=1),
    ))
    shapes.append(cv.Line(
        _CHART_LEFT_PAD, _CHART_TOP_PAD + plot_h,
        _CHART_LEFT_PAD + plot_w, _CHART_TOP_PAD + plot_h,
        paint=ft.Paint(color=ft.Colors.GREY_300, stroke_width=1),
    ))

    # Y-axis labels/gridlines (0 / 50 / 100 %)
    for pct in (0, 50, 100):
        gy = _y(pct)
        shapes.append(cv.Line(
            _CHART_LEFT_PAD, gy,
            _CHART_LEFT_PAD + plot_w, gy,
            paint=ft.Paint(color=ft.Colors.GREY_100, stroke_width=1),
        ))
        shapes.append(cv.Text(
            0, gy, f"{pct}%",
            style=ft.TextStyle(size=10, color=ft.Colors.GREY),
            alignment=ft.Alignment.CENTER_LEFT,
        ))

    # X-axis labels (attempt numbers)
    for i, attempt in enumerate(attempts):
        shapes.append(cv.Text(
            _x(i), _CHART_TOP_PAD + plot_h + 6, str(attempt),
            style=ft.TextStyle(size=10, color=ft.Colors.GREY),
            alignment=ft.Alignment.TOP_CENTER,
        ))

    # Score line
    coords = [(_x(i), _y(pct)) for i, pct in enumerate(percentages)]
    shapes.append(cv.Points(
        points=[ft.Offset(x, y) for x, y in coords],
        point_mode=cv.PointMode.POLYGON,
        paint=ft.Paint(
            color=_ACCENT_COLOR,
            stroke_width=2,
            style=ft.PaintingStyle.STROKE,
        ),
    ))

    # Markers
    shapes.extend(
        cv.Circle(
            x, y, 4,
            paint=ft.Paint(color=_ACCENT_COLOR, style=ft.PaintingStyle.FILL),
        )
        for x, y in coords
    )

    return cv.Canvas(shapes=shapes, width=width, height=_CHART_HEIGHT)


def _score_table(df: pd.DataFrame) -> ft.DataTable:
    rows: list[ft.DataRow] = []
    for _, row in df.iterrows():
        ts = (
            row["timestamp"].strftime("%Y-%m-%d %H:%M")
            if pd.notna(row["timestamp"])
            else ""
        )
        rows.append(
            ft.DataRow(cells=[
                ft.DataCell(
                    ft.Text(
                        str(row["paper_id"]),
                        color=ft.Colors.BLACK,
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        str(row["score_raw"]),
                        color=ft.Colors.BLACK,
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        str(row["score_total"]),
                        color=ft.Colors.BLACK,
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        f"{row['percentage']:.1f}%",
                        color=ft.Colors.BLACK,
                    ),
                ),
                ft.DataCell(
                    ft.Text(ts, color=ft.Colors.GREY, size=12),
                ),
            ])
        )
    return ft.DataTable(
        columns=[
            ft.DataColumn(
                label=ft.Text("Paper ID", color=ft.Colors.BLACK),
            ),
            ft.DataColumn(
                label=ft.Text("Raw", color=ft.Colors.BLACK),
            ),
            ft.DataColumn(
                label=ft.Text("Total", color=ft.Colors.BLACK),
            ),
            ft.DataColumn(
                label=ft.Text("%", color=ft.Colors.BLACK),
            ),
            ft.DataColumn(
                label=ft.Text("Date", color=ft.Colors.BLACK),
            ),
        ],
        rows=rows,
        border=ft.Border.all(1, ft.Colors.GREY_300),
        border_radius=8,
        heading_row_color=ft.Colors.BLUE_50,
    )


def _build_syllabus_section(
    page: ft.Page,
    syl_id: str,
    syl_entry: Mapping[str, object],
    syl_df: pd.DataFrame,
    chart_width: int,
) -> ft.ExpansionTile:
    syl_name = syl_entry.get("name", syl_id)

    syl_avg = syl_df["percentage"].mean()
    syl_best = syl_df["percentage"].max()
    syl_count = len(syl_df)

    syl_metrics = ft.Row(
        [
            metric_card("Papers", str(syl_count), ft.Colors.BLUE),
            metric_card("Average", f"{syl_avg:.1f}%", ft.Colors.GREEN),
            metric_card("Best", f"{syl_best:.1f}%", ft.Colors.ORANGE),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    pt_digits = sorted(syl_df["paper_type_digit"].dropna().unique())
    pt_raw = syl_entry.get("paper_types", {})
    pt_config: dict[str, str] = pt_raw if isinstance(pt_raw, dict) else {}

    type_content = ft.Column()
    selected_digit: list[str | None] = [
        pt_digits[0] if pt_digits else None,
    ]

    def _rebuild_type_content() -> None:
        type_content.controls.clear()
        digit = selected_digit[0]

        if digit is None:
            type_df = syl_df.copy()
            type_title = f"{syl_id} — All"
        else:
            type_df = (
                syl_df[syl_df["paper_type_digit"] == digit]
                .copy()
                .reset_index(drop=True)
            )
            pt_label = pt_config.get(digit, "Unknown")
            type_title = f"Paper {digit} — {pt_label}"

        type_df["attempt"] = range(1, len(type_df) + 1)

        type_content.controls.extend([
            ft.Text(
                type_title, size=16,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
            ft.Row(
                [_trend_chart(type_df, width=chart_width)],
                scroll=ft.ScrollMode.AUTO,
            ),
            ft.Row([_score_table(type_df)], scroll=ft.ScrollMode.AUTO),
        ])

    def _on_type_change(e: ft.ControlEvent) -> None:
        selected = e.control.selected  # type: ignore[attr-defined]
        if selected:
            selected_digit[0] = next(iter(selected))
            _rebuild_type_content()
            page.update()

    header_controls: list[ft.Control] = [syl_metrics]
    if pt_digits:
        type_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(
                    value=digit,
                    label=ft.Text(f"Paper {digit}"),
                )
                for digit in pt_digits
            ],
            selected=[selected_digit[0]] if selected_digit[0] else [],
            allow_multiple_selection=False,
            on_change=_on_type_change,  # type: ignore[arg-type]
        )
        # Scroll horizontally so several paper types don't overflow on a phone.
        header_controls.append(
            ft.Row([type_selector], scroll=ft.ScrollMode.AUTO)
        )

    panel_content = ft.Column(
        [*header_controls, ft.Divider(), type_content],
    )

    # Build lazily the first time this syllabus panel is expanded, instead of
    # eagerly for every syllabus when the Analytics tab is opened.
    content_built = [False]

    def _on_expand_change(e: ft.ControlEvent) -> None:
        expanded = str(e.data).lower() == "true"
        if expanded and not content_built[0]:
            content_built[0] = True
            _rebuild_type_content()
            page.update()

    return ft.ExpansionTile(
        title=ft.Text(
            f"📚 {syl_id} — {syl_name}",
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLACK,
        ),
        expanded=False,
        on_change=_on_expand_change,  # type: ignore[arg-type]
        controls=[
            ft.Container(
                panel_content,
                padding=ft.Padding(left=16, right=16, top=4, bottom=12),
            ),
        ],
    )


def build_analytics_tab(
    page: ft.Page,
    state: AppState,
) -> ft.Container:
    records = state.store.load_all()
    completed = [
        r for r in records if r.status == "Completed"
    ]
    total = len(records)
    done = len(completed)

    if not completed:
        return ft.Container(
            ft.Column([
                ft.Text(
                    "统计分析",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLACK,
                ),
                ft.Container(height=20),
                ft.Text(
                    "暂无已完成的试卷，提交分数后查看统计。",
                    color=ft.Colors.GREY,
                ),
            ]),
            padding=20,
        )

    # Build DataFrame
    rows_data = [
        {
            "paper_id": r.paper_id,
            "syllabus_id": _extract_syllabus_id(r.paper_id),
            "paper_type_digit": _extract_paper_type_digit(
                r.paper_id,
            ),
            "percentage": r.percentage,
            "score_raw": r.score_raw,
            "score_total": r.score_total,
            "timestamp": r.timestamp,
        }
        for r in completed
        if r.percentage is not None
    ]
    if not rows_data:
        return ft.Container(
            ft.Text("没有有效的成绩数据。", color=ft.Colors.GREY),
            padding=20,
        )

    df = pd.DataFrame(rows_data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp", ascending=True).reset_index(
        drop=True,
    )

    # Overall metrics
    avg = df["percentage"].mean()
    best = df["percentage"].max()
    latest = df["percentage"].iloc[-1]
    delta = (
        latest - df["percentage"].iloc[-2]
        if done >= _MIN_FOR_TREND
        else None
    )

    delta_text = f"{delta:+.1f}%" if delta is not None else ""

    overall_metrics = ft.Row(
        [
            metric_card("总试卷", str(total), ft.Colors.BLUE),
            metric_card("已完成", str(done), ft.Colors.GREEN),
            metric_card("平均分", f"{avg:.1f}%", ft.Colors.PURPLE),
            metric_card("最高分", f"{best:.1f}%", ft.Colors.ORANGE),
            metric_card(
                "最新",
                f"{latest:.1f}%",
                ft.Colors.TEAL,
            ),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    # Per-syllabus sections. Size the trend chart to the current screen: the
    # tab has 20px padding each side and each syllabus panel adds 16px each
    # side, so the usable inner width is roughly page.width - 72. Clamp to a
    # sane range; the chart is also wrapped in a horizontal scroller so any
    # residual mismatch scrolls instead of throwing a RenderFlex overflow.
    chart_width = int(max(280, min(600, (page.width or 390) - 72)))

    config_store = ConfigStore()
    syllabus_config = config_store.load_syllabus_config()
    syllabus_ids = sorted(df["syllabus_id"].unique())

    syllabus_sections: list[ft.Control] = [
        _build_syllabus_section(
            page, syl_id, syllabus_config.get(syl_id, {}),
            df[df["syllabus_id"] == syl_id].copy().reset_index(drop=True),
            chart_width,
        )
        for syl_id in syllabus_ids
    ]

    controls: list[ft.Control] = [
        ft.Text(
            "统计分析",
            size=24,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLACK,
        ),
        ft.Container(height=12),
        ft.Text(
            "Overall",
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLACK,
        ),
        overall_metrics,
    ]
    if delta_text:
        controls.append(
            ft.Text(
                f"最新变化: {delta_text}",
                size=12,
                color=ft.Colors.GREY,
            ),
        )
    controls.append(ft.Divider())
    controls.extend(syllabus_sections)

    return ft.Container(
        ft.Column(controls, spacing=8),
        padding=20,
    )
