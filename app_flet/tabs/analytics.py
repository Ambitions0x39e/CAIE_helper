from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

import flet as ft
import pandas as pd
from flet import canvas as cv

from app_flet import theme
from app_flet.components.widgets import (
    metric_card,
    section_title,
    segmented_strip,
)
from core.config_store import ConfigStore

if TYPE_CHECKING:
    from app_flet.state import AppState

_MIN_FOR_TREND = 2
#: 坐标轴刻度字号。比 MICRO 还小一档，它只是给曲线定标，不参与阅读。
_AXIS_LABEL_SIZE = 10
_CHART_HEIGHT = 350
_CHART_LEFT_PAD = 40
_CHART_RIGHT_PAD = 20
_CHART_TOP_PAD = 10
_CHART_BOTTOM_PAD = 30

#: main.py's nav_rail (_NAV_BUTTON_SIZE 64 + 20 padding = 84) plus the 1px
#: VerticalDivider beside it — page.width is the *whole window*, not the
#: slice handed to content_area, so this has to come off before any width
#: math here. Missing this made the chart width assume ~85px more room than
#: content_area actually has, overflowing the right edge by ~9-10%.
_NAV_CHROME_W = 85

# Flexible chart/table layout. The tab has 20px padding each side and each
# syllabus panel adds 16px each side → usable inner width ≈
# (page.width - _NAV_CHROME_W) - 72.
_INNER_PADDING = 72
# Side-by-side (table left, chart right) needs the table (~520px with
# column_spacing=28) plus a chart of at least _CHART_MIN_WIDTH; below this
# page width, stack the chart full-width above the table instead.
_SIDE_BY_SIDE_MIN_PAGE_W = 950
_TABLE_EST_WIDTH = 520
_LAYOUT_SPACING = 16
_CHART_MIN_WIDTH = 320


def _axis_label_style() -> ft.TextStyle:
    """坐标轴刻度：纯数字，跟表格里的数值走同一档字距。

    颜色是构造后补上的 —— theme 的字距档只管字距和行高两项，不带配色。
    每次返回新对象，同 theme 里那几个工厂。
    """
    style = theme.numeric_style(size=_AXIS_LABEL_SIZE)
    style.color = theme.MUTED
    return style


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
            size=theme.CAPTION,
            color=theme.MUTED,
            italic=True,
            style=theme.caption_style(),
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
        paint=ft.Paint(color=theme.HAIRLINE, stroke_width=1),
    ))
    shapes.append(cv.Line(
        _CHART_LEFT_PAD, _CHART_TOP_PAD + plot_h,
        _CHART_LEFT_PAD + plot_w, _CHART_TOP_PAD + plot_h,
        paint=ft.Paint(color=theme.HAIRLINE, stroke_width=1),
    ))

    # Y-axis labels/gridlines (0 / 50 / 100 %)
    for pct in (0, 50, 100):
        gy = _y(pct)
        shapes.append(cv.Line(
            _CHART_LEFT_PAD, gy,
            _CHART_LEFT_PAD + plot_w, gy,
            paint=ft.Paint(color=theme.HAIRLINE_FAINT, stroke_width=1),
        ))
        shapes.append(cv.Text(
            0, gy, f"{pct}%",
            style=_axis_label_style(),
            alignment=ft.Alignment.CENTER_LEFT,
        ))

    # X-axis labels (attempt numbers)
    for i, attempt in enumerate(attempts):
        shapes.append(cv.Text(
            _x(i), _CHART_TOP_PAD + plot_h + 6, str(attempt),
            style=_axis_label_style(),
            alignment=ft.Alignment.TOP_CENTER,
        ))

    # Score line
    coords = [(_x(i), _y(pct)) for i, pct in enumerate(percentages)]
    shapes.append(cv.Points(
        points=[ft.Offset(x, y) for x, y in coords],
        point_mode=cv.PointMode.POLYGON,
        paint=ft.Paint(
            color=theme.PRIMARY,
            stroke_width=2,
            style=ft.PaintingStyle.STROKE,
        ),
    ))

    # Markers
    shapes.extend(
        cv.Circle(
            x, y, 4,
            paint=ft.Paint(color=theme.PRIMARY, style=ft.PaintingStyle.FILL),
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
                        style=theme.numeric_style(),
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        str(row["score_raw"]),
                        style=theme.numeric_style(),
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        str(row["score_total"]),
                        style=theme.numeric_style(),
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        f"{row['percentage']:.1f}%",
                        style=theme.numeric_style(),
                    ),
                ),
                ft.DataCell(
                    ft.Text(
                        ts,
                        color=theme.MUTED,
                        size=theme.CAPTION,
                        style=theme.caption_style(),
                    ),
                ),
            ])
        )
    return ft.DataTable(
        columns=[
            ft.DataColumn(
                label=ft.Text("Paper ID"),
            ),
            ft.DataColumn(
                label=ft.Text("Raw"),
            ),
            ft.DataColumn(
                label=ft.Text("Total"),
            ),
            ft.DataColumn(
                label=ft.Text("%"),
            ),
            ft.DataColumn(
                label=ft.Text("Date"),
            ),
        ],
        rows=rows,
        column_spacing=28,  # keep the table near _TABLE_EST_WIDTH
        border=ft.Border.all(1, theme.HAIRLINE),
        border_radius=8,
        heading_row_color=theme.PRIMARY_TINT,
    )


def _build_syllabus_section(
    page: ft.Page,
    syl_id: str,
    syl_entry: Mapping[str, object],
    syl_df: pd.DataFrame,
) -> ft.ExpansionTile:
    syl_name = syl_entry.get("name", syl_id)

    syl_avg = syl_df["percentage"].mean()
    syl_best = syl_df["percentage"].max()
    syl_count = len(syl_df)

    syl_metrics = ft.Row(
        [
            metric_card("Papers", str(syl_count), theme.PRIMARY),
            metric_card("Average", f"{syl_avg:.1f}%", theme.SUCCESS),
            metric_card("Best", f"{syl_best:.1f}%", theme.WARNING),
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

        title = ft.Text(
            type_title, size=16,
            weight=ft.FontWeight.BOLD,
            style=theme.section_style(),
        )

        # Flexible layout, decided from the live window width each rebuild:
        # wide enough → table left, chart fills the remaining width on the
        # right; otherwise → chart full-width on top, table below. Both
        # variants sit in horizontal scrollers so an estimate mismatch
        # scrolls instead of throwing a RenderFlex overflow.
        page_w = int(page.width or 390) - _NAV_CHROME_W
        avail = page_w - _INNER_PADDING
        if page_w >= _SIDE_BY_SIDE_MIN_PAGE_W:
            chart_w = max(
                _CHART_MIN_WIDTH,
                avail - _TABLE_EST_WIDTH - _LAYOUT_SPACING,
            )
            type_content.controls.extend([
                title,
                ft.Row(
                    [
                        _score_table(type_df),
                        _trend_chart(type_df, width=chart_w),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=_LAYOUT_SPACING,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ])
        else:
            chart_w = max(_CHART_MIN_WIDTH, avail)
            type_content.controls.extend([
                title,
                ft.Row(
                    [_trend_chart(type_df, width=chart_w)],
                    scroll=ft.ScrollMode.AUTO,
                ),
                ft.Row(
                    [_score_table(type_df)],
                    scroll=ft.ScrollMode.AUTO,
                ),
            ])

    def _on_type_change(index: int) -> None:
        selected_digit[0] = pt_digits[index]
        _rebuild_type_content()
        page.update()

    header_controls: list[ft.Control] = [syl_metrics]
    if pt_digits:
        type_selector = segmented_strip(
            [f"Paper {digit}" for digit in pt_digits],
            _on_type_change,
            selected=(
                pt_digits.index(selected_digit[0])
                if selected_digit[0] in pt_digits else 0
            ),
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
                section_title("统计分析"),
                ft.Container(height=20),
                ft.Text(
                    "暂无已完成的试卷，提交分数后查看统计。",
                    color=theme.MUTED,
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
            ft.Text("没有有效的成绩数据。", color=theme.MUTED),
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

    overall_metrics = ft.Row(
        [
            metric_card("总试卷", str(total), theme.PRIMARY),
            metric_card("已完成", str(done), theme.SUCCESS),
            metric_card("平均分", f"{avg:.1f}%", theme.CARD_PURPLE),
            metric_card("最高分", f"{best:.1f}%", theme.WARNING),
            metric_card(
                "最新",
                f"{latest:.1f}%",
                theme.CARD_TEAL,
            ),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    config_store = ConfigStore()
    syllabus_config = config_store.load_syllabus_config()
    syllabus_ids = sorted(df["syllabus_id"].unique())

    syllabus_sections: list[ft.Control] = [
        _build_syllabus_section(
            page, syl_id, syllabus_config.get(syl_id, {}),
            df[df["syllabus_id"] == syl_id].copy().reset_index(drop=True),
        )
        for syl_id in syllabus_ids
    ]

    controls: list[ft.Control] = [
        section_title("统计分析"),
        ft.Container(height=12),
        ft.Text(
            "Overall",
            weight=ft.FontWeight.BOLD,
        ),
        overall_metrics,
    ]
    controls.append(ft.Divider())
    controls.extend(syllabus_sections)

    return ft.Container(
        ft.Column(controls, spacing=8),
        padding=20,
    )
