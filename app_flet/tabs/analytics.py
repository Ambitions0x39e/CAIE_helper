from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean
from typing import TYPE_CHECKING

import flet as ft
from flet import canvas as cv

from app_flet import theme
from app_flet.components.widgets import metric_card, section_title
from core.config_store import ConfigStore

if TYPE_CHECKING:
    from app_flet.state import AppState

_MIN_FOR_TREND = 2
_CHART_HEIGHT = 350
_CHART_LEFT_PAD = 40
_CHART_RIGHT_PAD = 20
_CHART_TOP_PAD = 10
_CHART_BOTTOM_PAD = 30

# Flexible chart/table layout. The tab has 20px padding each side and each
# syllabus panel adds 16px each side → usable inner width ≈
# (page.width - theme.NAV_CHROME_W) - 72.
_INNER_PADDING = 72
# Side-by-side (table left, chart right) needs the table (~520px with
# column_spacing=28) plus a chart of at least _CHART_MIN_WIDTH; below this
# page width, stack the chart full-width above the table instead.
_SIDE_BY_SIDE_MIN_PAGE_W = 950
_TABLE_EST_WIDTH = 520
_LAYOUT_SPACING = 16
_CHART_MIN_WIDTH = 320


@dataclass(frozen=True)
class _Attempt:
    """One completed paper, as the charts and tables need it."""

    paper_id: str
    syllabus_id: str
    paper_type_digit: str | None
    percentage: float
    score_raw: float | None
    score_total: float | None
    timestamp: datetime | None


def _sort_key(a: _Attempt) -> tuple[bool, datetime]:
    """Oldest first, undated last.

    A record written before the timestamp column existed has none, and a
    stored naive time is read as UTC — the only zone the app ever writes.
    """
    if a.timestamp is None:
        return (True, datetime.min.replace(tzinfo=UTC))
    ts = a.timestamp
    return (False, ts if ts.tzinfo else ts.replace(tzinfo=UTC))


def _extract_syllabus_id(paper_id: str) -> str:
    return paper_id[:4]


def _extract_paper_type_digit(paper_id: str) -> str | None:
    match = re.search(r"_qp_(\d)", paper_id)
    return match.group(1) if match else None


def _trend_chart(
    attempts: Sequence[_Attempt],
    width: int = 600,
) -> ft.Control:
    if len(attempts) < _MIN_FOR_TREND:
        return ft.Text(
            "至少需要 2 次成绩才能绘制趋势图",
            size=12,
            color=theme.MUTED,
            italic=True,
        )

    plot_w = width - _CHART_LEFT_PAD - _CHART_RIGHT_PAD
    plot_h = _CHART_HEIGHT - _CHART_TOP_PAD - _CHART_BOTTOM_PAD
    y_max = 105.0
    percentages = [a.percentage for a in attempts]
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
            style=ft.TextStyle(size=10, color=theme.MUTED),
            alignment=ft.Alignment.CENTER_LEFT,
        ))

    # X-axis labels (attempt numbers)
    for i in range(n):
        shapes.append(cv.Text(
            _x(i), _CHART_TOP_PAD + plot_h + 6, str(i + 1),
            style=ft.TextStyle(size=10, color=theme.MUTED),
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


def _score_table(attempts: Sequence[_Attempt]) -> ft.DataTable:
    rows = [
        ft.DataRow(cells=[
            ft.DataCell(ft.Text(a.paper_id)),
            ft.DataCell(ft.Text(str(a.score_raw))),
            ft.DataCell(ft.Text(str(a.score_total))),
            ft.DataCell(ft.Text(f"{a.percentage:.1f}%")),
            ft.DataCell(ft.Text(
                a.timestamp.strftime("%Y-%m-%d %H:%M") if a.timestamp else "",
                color=theme.MUTED,
                size=12,
            )),
        ])
        for a in attempts
    ]
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
    syl_attempts: Sequence[_Attempt],
) -> ft.ExpansionTile:
    syl_name = syl_entry.get("name", syl_id)

    syl_avg = fmean(a.percentage for a in syl_attempts)
    syl_best = max(a.percentage for a in syl_attempts)
    syl_count = len(syl_attempts)

    syl_metrics = ft.Row(
        [
            metric_card("Papers", str(syl_count), theme.PRIMARY),
            metric_card("Average", f"{syl_avg:.1f}%", theme.SUCCESS),
            metric_card("Best", f"{syl_best:.1f}%", theme.WARNING),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    pt_digits = sorted(
        {a.paper_type_digit for a in syl_attempts if a.paper_type_digit}
    )
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
            type_attempts = list(syl_attempts)
            type_title = f"{syl_id} — All"
        else:
            type_attempts = [
                a for a in syl_attempts if a.paper_type_digit == digit
            ]
            pt_label = pt_config.get(digit, "Unknown")
            type_title = f"Paper {digit} — {pt_label}"

        title = ft.Text(
            type_title, size=16,
            weight=ft.FontWeight.BOLD,
        )

        # Flexible layout, decided from the live window width each rebuild:
        # wide enough → table left, chart fills the remaining width on the
        # right; otherwise → chart full-width on top, table below. Both
        # variants sit in horizontal scrollers so an estimate mismatch
        # scrolls instead of throwing a RenderFlex overflow.
        page_w = int(page.width or 390) - theme.NAV_CHROME_W
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
                        _score_table(type_attempts),
                        _trend_chart(type_attempts, width=chart_w),
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
                    [_trend_chart(type_attempts, width=chart_w)],
                    scroll=ft.ScrollMode.AUTO,
                ),
                ft.Row(
                    [_score_table(type_attempts)],
                    scroll=ft.ScrollMode.AUTO,
                ),
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

    attempts = sorted(
        (
            _Attempt(
                paper_id=r.paper_id,
                syllabus_id=_extract_syllabus_id(r.paper_id),
                paper_type_digit=_extract_paper_type_digit(r.paper_id),
                percentage=r.percentage,
                score_raw=r.score_raw,
                score_total=r.score_total,
                timestamp=r.timestamp,
            )
            for r in completed
            if r.percentage is not None
        ),
        key=_sort_key,
    )
    if not attempts:
        return ft.Container(
            ft.Text("没有有效的成绩数据。", color=theme.MUTED),
            padding=20,
        )

    # Overall metrics
    avg = fmean(a.percentage for a in attempts)
    best = max(a.percentage for a in attempts)
    latest = attempts[-1].percentage

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
    syllabus_ids = sorted({a.syllabus_id for a in attempts})

    syllabus_sections: list[ft.Control] = [
        _build_syllabus_section(
            page, syl_id, syllabus_config.get(syl_id, {}),
            [a for a in attempts if a.syllabus_id == syl_id],
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
