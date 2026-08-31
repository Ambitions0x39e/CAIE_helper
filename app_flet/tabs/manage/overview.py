"""【总览】：一张环形图交代整体，下面每个 syllabus 一张卡，点开是它的明细。"""
from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean
from typing import TYPE_CHECKING

import flet as ft
from flet import canvas as cv

from app_flet import theme
from app_flet.components.widgets import hoverable, push_track, segmented_strip
from app_flet.tabs.manage.paper_icon import (
    subject_icon,
    subject_label,
    syllabus_config,
    syllabus_id_of,
    syllabus_names,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from app_flet.state import AppState
    from core.models import PaperRecord

_MIN_FOR_TREND = 2
#: 坐标轴刻度字号。比 MICRO 还小一档，它只是给曲线定标，不参与阅读。
_AXIS_LABEL_SIZE = 10
_CHART_HEIGHT = 350
_CHART_LEFT_PAD = 40
_CHART_RIGHT_PAD = 20
_CHART_TOP_PAD = 10
_CHART_BOTTOM_PAD = 30

# 明细浮层里的版面：够宽就表格在左、曲线占满右边剩下的宽；不够就曲线整宽在上、
# 表格在下。两种都套在横向滚动条里，估宽估歪了是滚动而不是 RenderFlex 溢出。
_SIDE_BY_SIDE_MIN_W = 900
#: 成绩表那一栏的宽和高。高度取跟折线图一样 —— 并排时两块齐平，行数再多也是
#: 表格自己往下滚，而不是把整页顶长、把折线图甩到视野外面。
_TABLE_W = 520
_LAYOUT_SPACING = 16
_CHART_MIN_WIDTH = 320

#: 环宽占直径的比例。
_RING_RATIO = 0.17
#: 总览那颗大环、明细浮层页头那颗、卡片右边那颗小环。只有前两颗中间写字。
_DONUT_BIG = 168
_DONUT_PANEL = 96
_DONUT_SMALL = 68
#: 中心那两行字占环孔（不是直径）的比例。按直径算的话，环宽是按比例走的，孔
#: 反而不成比例 —— 68 的环孔只有 45px，一个按直径算出来的数字会顶满它。
_CENTER_VALUE_RATIO = 0.34
_CENTER_LABEL_RATIO = 0.15
#: 一行放两张卡。
_CARDS_PER_ROW = 2

# ── 明细浮层的展开 ────────────────────────────────────────────────

#: 收起时的缩放。不取 0 —— 从一个点长出来读起来是「弹出一个新东西」，从九成
#: 大长出来才是「这张卡放大成了整页」。
_PANEL_REST_SCALE = 0.92
#: 卡片网格在内容区里大致从哪儿开始（上面压着一张总览卡）。缩放原点的纵向位置
#: 按这个往下摊 —— Flet 不把控件量出来的几何交回 Python，位置只能从卡片在网格
#: 里的行列推，左右两列是准的，纵向是估的。
_GRID_TOP_SHARE = 0.35
#: 展开前先按起始状态画一帧，等它落地再改成终态：补间补的是「已经画出来的那个
#: 值」到新值之间的差，而收起时浮层是 visible=False，没有画出来的值可补。
#
# ponytail: 这个数按「一次往返 + 一帧」估，是这里唯一手调的量。短了只会退化成
# 瞬切，不会出别的错；要精确得等 Flet 给出「这一帧已提交」的回调。
_PAINT_SETTLE_MS = 50


def _panel_origin(index: int, total: int) -> ft.Alignment:
    """第 ``index`` 张卡大致在内容区的哪个位置，给缩放当原点。"""
    rows = max(1, -(-total // _CARDS_PER_ROW))
    x = -0.5 if index % _CARDS_PER_ROW == 0 else 0.5
    row_mid = (index // _CARDS_PER_ROW + 0.5) / rows
    y = _GRID_TOP_SHARE + (1 - _GRID_TOP_SHARE) * row_mid
    return ft.Alignment(x, y * 2 - 1)


def _axis_label_style() -> ft.TextStyle:
    """坐标轴刻度：纯数字，跟表格里的数值走同一档字距。

    颜色是构造后补上的 —— theme 的字距档只管字距和行高两项，不带配色。
    每次返回新对象，同 theme 里那几个工厂。
    """
    style = theme.numeric_style(size=_AXIS_LABEL_SIZE)
    style.color = theme.MUTED
    return style


# ── 数据 ──────────────────────────────────────────────────────────


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


@dataclass(frozen=True)
class _Tally:
    """一组卷子的构成，按「每张卷各占一份」算。

    未完成的卷在 ``data.csv`` 里没有满分（``score_total`` 只在 Completed 时才
    写），所以整块饼没法按分去分。每张卷各占一份：完成的那份按得分率劈成拿到
    的和丢掉的，未完成的整份算未完成。
    """

    total: int
    earned: float
    lost: float
    pending: int


def _tally(records: Sequence[PaperRecord]) -> _Tally:
    done = 0
    earned = 0.0
    for record in records:
        if record.status != "Completed":
            continue
        done += 1
        earned += (record.percentage or 0.0) / 100
    return _Tally(
        total=len(records),
        earned=earned,
        lost=done - earned,
        pending=len(records) - done,
    )


def _sort_key(a: _Attempt) -> tuple[bool, datetime]:
    """Oldest first, undated last.

    A record written before the timestamp column existed has none, and a
    stored naive time is read as UTC — the only zone the app ever writes.
    """
    if a.timestamp is None:
        return (True, datetime.min.replace(tzinfo=UTC))
    ts = a.timestamp
    return (False, ts if ts.tzinfo else ts.replace(tzinfo=UTC))


def _paper_type_digit(paper_id: str) -> str | None:
    match = re.search(r"_qp_(\d)", paper_id)
    return match.group(1) if match else None


def _attempts_of(records: Sequence[PaperRecord]) -> list[_Attempt]:
    return sorted(
        (
            _Attempt(
                paper_id=r.paper_id,
                syllabus_id=syllabus_id_of(r.paper_id),
                paper_type_digit=_paper_type_digit(r.paper_id),
                percentage=r.percentage,
                score_raw=r.score_raw,
                score_total=r.score_total,
                timestamp=r.timestamp,
            )
            for r in records
            if r.status == "Completed" and r.percentage is not None
        ),
        key=_sort_key,
    )


# ── 环形图 ────────────────────────────────────────────────────────


def _donut(
    size: int,
    tally: _Tally,
    *,
    center: ft.Control | None = None,
) -> ft.Control:
    """三段环：绿＝拿到的分，红＝丢掉的分，灰＝还没做。

    自己画而不是接图表库：flet 0.86 的核心包里没有图表控件，而一段圆环就是
    一条 ``canvas.Arc``，为它多装一个包不值。
    """
    thickness = max(6.0, size * _RING_RATIO)
    inset = thickness / 2
    box = size - thickness
    paint = ft.Paint(
        stroke_width=thickness,
        style=ft.PaintingStyle.STROKE,
        stroke_cap=ft.StrokeCap.BUTT,
    )

    def _arc(start: float, sweep: float, color: str) -> cv.Arc:
        return cv.Arc(
            inset, inset, box, box, start, sweep,
            paint=ft.Paint(
                color=color,
                stroke_width=paint.stroke_width,
                style=paint.style,
                stroke_cap=paint.stroke_cap,
            ),
        )

    shapes: list[cv.Shape] = [
        _arc(0.0, 2 * math.pi, theme.HAIRLINE_FAINT),
    ]
    if tally.total:
        # 十二点方向起笔，顺时针。
        angle = -math.pi / 2
        for amount, color in (
            (tally.earned, theme.SCORE_FULL),
            (tally.lost, theme.SCORE_ZERO),
            (tally.pending, theme.HAIRLINE),
        ):
            if amount <= 0:
                continue
            sweep = 2 * math.pi * amount / tally.total
            shapes.append(_arc(angle, sweep, color))
            angle += sweep

    canvas = cv.Canvas(shapes=shapes, width=size, height=size)
    if center is None:
        return canvas
    return ft.Stack(
        [
            canvas,
            ft.Container(
                center, width=size, height=size,
                alignment=ft.Alignment.CENTER,
            ),
        ],
        width=size,
        height=size,
    )


def _donut_center(value: str, label: str, size: int) -> ft.Control:
    """环中央那两行字。字号跟着环孔走，换个直径不用回来改数。"""
    hole = size * (1 - 2 * _RING_RATIO)
    value_size = round(hole * _CENTER_VALUE_RATIO)
    # 标签不跟到看不清为止：小环上按比例算出来是个位数，收到 MICRO 打住。
    label_size = max(theme.MICRO, round(hole * _CENTER_LABEL_RATIO))
    return ft.Column(
        [
            ft.Text(
                value, size=value_size, weight=ft.FontWeight.BOLD,
                color=theme.TEXT_PRIMARY,
                style=theme.numeric_style(size=value_size),
            ),
            ft.Text(
                label, size=label_size, color=theme.MUTED,
                style=theme.caption_style(),
            ),
        ],
        spacing=0,
        tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _legend(tally: _Tally) -> ft.Control:
    done = round(tally.earned + tally.lost)
    earned_rate = tally.earned / done * 100 if done else 0.0
    return ft.Column(
        [
            _legend_row(
                theme.SCORE_FULL, "得分", f"{done} 张 · {earned_rate:.1f}%",
            ),
            _legend_row(
                theme.SCORE_ZERO, "失分", f"{100 - earned_rate:.1f}%",
            ),
            _legend_row(theme.HAIRLINE, "未完成", f"{tally.pending} 张"),
        ],
        spacing=theme.SPACE_SM,
        tight=True,
    )


def _legend_row(color: str, label: str, value: str) -> ft.Control:
    return ft.Row(
        [
            ft.Container(width=10, height=10, border_radius=5, bgcolor=color),
            ft.Text(label, size=theme.CAPTION, style=theme.caption_style()),
            ft.Text(
                value, size=theme.CAPTION, color=theme.MUTED,
                style=theme.numeric_style(size=theme.CAPTION),
            ),
        ],
        spacing=theme.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        tight=True,
    )


# ── 明细：成绩表 + 折线图 ─────────────────────────────────────────


def _trend_chart(attempts: Sequence[_Attempt], width: int) -> ft.Control:
    if len(attempts) < _MIN_FOR_TREND:
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
            style=_axis_label_style(),
            alignment=ft.Alignment.CENTER_LEFT,
        ))

    # X-axis labels (attempt numbers)
    for i in range(n):
        shapes.append(cv.Text(
            _x(i), _CHART_TOP_PAD + plot_h + 6, str(i + 1),
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


def _score_table(attempts: Sequence[_Attempt]) -> ft.DataTable:
    rows = [
        ft.DataRow(cells=[
            ft.DataCell(ft.Text(a.paper_id, style=theme.numeric_style())),
            ft.DataCell(ft.Text(str(a.score_raw), style=theme.numeric_style())),
            ft.DataCell(ft.Text(str(a.score_total), style=theme.numeric_style())),
            ft.DataCell(
                ft.Text(f"{a.percentage:.1f}%", style=theme.numeric_style())
            ),
            ft.DataCell(ft.Text(
                a.timestamp.strftime("%Y-%m-%d %H:%M") if a.timestamp else "",
                color=theme.MUTED,
                size=theme.CAPTION,
                style=theme.caption_style(),
            )),
        ])
        for a in attempts
    ]
    return ft.DataTable(
        columns=[
            ft.DataColumn(label=ft.Text("Paper ID")),
            ft.DataColumn(label=ft.Text("Raw")),
            ft.DataColumn(label=ft.Text("Total")),
            ft.DataColumn(label=ft.Text("%")),
            ft.DataColumn(label=ft.Text("Date")),
        ],
        rows=rows,
        column_spacing=28,  # 让表格的固有宽度贴近 _TABLE_W
        border=ft.Border.all(1, theme.HAIRLINE),
        border_radius=theme.CARD_RADIUS,
        heading_row_color=theme.PRIMARY_TINT,
    )


# ── 卡片 ──────────────────────────────────────────────────────────


def _stat(label: str, value: str) -> ft.Control:
    return ft.Row(
        [
            ft.Text(
                label, size=theme.CAPTION, color=theme.MUTED,
                style=theme.caption_style(),
            ),
            ft.Text(
                value, size=theme.SUBHEAD, weight=ft.FontWeight.W_600,
                style=theme.numeric_style(size=theme.SUBHEAD),
            ),
        ],
        spacing=theme.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        tight=True,
    )


def _syllabus_card(
    syl_id: str,
    records: Sequence[PaperRecord],
    on_open: Callable[[str], None],
) -> ft.Control:
    attempts = _attempts_of(records)
    latest = f"{attempts[-1].percentage:.1f}%" if attempts else "—"
    best = f"{max(a.percentage for a in attempts):.1f}%" if attempts else "—"

    inner = ft.Container(
        ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    subject_icon(syl_id),
                                    size=18, color=theme.PRIMARY,
                                ),
                                ft.Text(
                                    syl_id, size=theme.SECTION,
                                    weight=ft.FontWeight.BOLD,
                                    style=theme.numeric_style(size=theme.SECTION),
                                ),
                            ],
                            spacing=theme.SPACE_SM,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            syllabus_names().get(syl_id, ""),
                            size=theme.CAPTION, color=theme.MUTED,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            style=theme.caption_style(),
                        ),
                        ft.Container(height=theme.SPACE_XS),
                        _stat("最近", latest),
                        _stat("最佳", best),
                        _stat("共", f"{len(records)} 张"),
                    ],
                    spacing=theme.SPACE_XS,
                    expand=True,
                ),
                _donut(_DONUT_SMALL, _tally(records)),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=theme.SPACE_MD,
        ),
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.card_shadow(),
        padding=theme.SPACE_LG,
        animate=ft.Animation(theme.DURATION_INSTANT, theme.CURVE_IN),
        on_click=lambda _: on_open(syl_id),
    )
    return ft.Container(hoverable(inner), expand=True)


# ── 明细浮层 ──────────────────────────────────────────────────────


def _table_box(attempts: Sequence[_Attempt]) -> ft.Control:
    """成绩表，装在一个定死尺寸的盒子里，纵横两向各自滚。

    盒子必须定高：滚动列要有确定的高度才滚得起来，交给内容长的话它会一直长下
    去，把折线图挤出视野 —— 那正是「表格比图长」的样子。
    """
    return ft.Container(
        ft.Column(
            [ft.Row([_score_table(attempts)], scroll=ft.ScrollMode.AUTO)],
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
        ),
        width=_TABLE_W,
        height=_CHART_HEIGHT,
    )


def _panel_body(
    page: ft.Page,
    attempts: Sequence[_Attempt],
) -> ft.Control:
    """成绩表 + 折线图。够宽并排，不够就上下摞。"""
    avail = int(page.width or 1024) - theme.NAV_CHROME_W - theme.SPACE_XL * 4
    if avail >= _SIDE_BY_SIDE_MIN_W:
        chart_w = max(
            _CHART_MIN_WIDTH, avail - _TABLE_W - _LAYOUT_SPACING,
        )
        return ft.Row(
            [_table_box(attempts), _trend_chart(attempts, chart_w)],
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=_LAYOUT_SPACING,
        )
    chart_w = max(_CHART_MIN_WIDTH, avail)
    return ft.Column(
        [
            ft.Row([_trend_chart(attempts, chart_w)], scroll=ft.ScrollMode.AUTO),
            _table_box(attempts),
        ],
        spacing=_LAYOUT_SPACING,
    )


def _fill_panel(
    page: ft.Page,
    panel: ft.Container,
    syl_id: str,
    syl_entry: Mapping[str, object],
    attempts: Sequence[_Attempt],
    tally: _Tally,
    on_close: Callable[[], None],
) -> None:
    """把一个 syllabus 的明细填进浮层。开合的动画在调用方（见 ``build_overview``
    里的 ``_show_panel`` / ``_hide_panel``），这里只管内容。"""
    digits = sorted({a.paper_type_digit for a in attempts if a.paper_type_digit})
    pt_raw = syl_entry.get("paper_types", {})
    pt_names: dict[str, str] = pt_raw if isinstance(pt_raw, dict) else {}

    # 一个 Paper 一格：切换时旧的往一侧出、新的从另一侧进，方向由分段条上的
    # 先后决定。fill=True —— 浮层是定高的，松约束下格子会缩到内容的固有高度，
    # 格子里那根滚动列就撑不出约束了。
    track, show_pane = push_track(
        page, max(len(digits), 1), ft.Column(), fill=True,
    )

    def _pane(digit: str | None) -> ft.Control:
        if digit is None:
            shown, caption = list(attempts), "全部"
        else:
            shown = [a for a in attempts if a.paper_type_digit == digit]
            caption = f"Paper {digit} — {pt_names.get(digit, 'Unknown')}"
        return ft.Column(
            [
                ft.Text(
                    caption, size=theme.SECTION, weight=ft.FontWeight.BOLD,
                    style=theme.section_style(),
                ),
                _panel_body(page, shown),
            ],
            spacing=theme.SPACE_MD,
            scroll=ft.ScrollMode.AUTO,
        )

    def _on_pick(index: int) -> None:
        show_pane(index, _pane(digits[index]))

    def _close(_: ft.Event[ft.IconButton]) -> None:
        on_close()

    header = ft.Row(
        [
            ft.IconButton(
                ft.CupertinoIcons.CHEVRON_LEFT,
                icon_size=18, tooltip="返回", on_click=_close,
            ),
            ft.Icon(subject_icon(syl_id), color=theme.PRIMARY, size=20),
            ft.Text(
                subject_label(syl_id), size=theme.TITLE,
                weight=ft.FontWeight.BOLD, style=theme.title_style(),
            ),
            ft.Container(expand=True),
            _donut(
                _DONUT_PANEL, tally,
                center=_donut_center(str(tally.total), "张", _DONUT_PANEL),
            ),
        ],
        spacing=theme.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    controls: list[ft.Control] = [header]
    if digits:
        controls.append(ft.Row(
            [segmented_strip(
                [f"Paper {d}" for d in digits], _on_pick, selected=0,
            )],
            alignment=ft.MainAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        ))
    show_pane(0, _pane(digits[0] if digits else None))
    # 高度落在这一层：轨道要 fill，就得从上面拿到一个确定的盒子。
    controls.append(ft.Container(track, expand=True))

    panel.content = ft.Column(controls, spacing=theme.SPACE_MD)


# ── 组装 ──────────────────────────────────────────────────────────


def build_overview(
    page: ft.Page,
    state: AppState,
    panel: ft.Container,
) -> ft.Control:
    records = state.store.load_all()
    if not records:
        return ft.Text("暂无记录，请先下载试卷。", size=16, color=theme.MUTED)

    by_syllabus: dict[str, list[PaperRecord]] = {}
    for record in records:
        by_syllabus.setdefault(syllabus_id_of(record.paper_id), []).append(record)

    overall = _tally(records)
    completed = [a.percentage for a in _attempts_of(records)]

    # 展开/收起共用一个原点，收起才会缩回它出来的那张卡。
    origin = [ft.Alignment.CENTER]
    #: 收起的动画还没走完就又点开了一张卡时，只让最后那次算数 —— 否则先发的
    #: 那次「藏起来」会落在后发的「展开」之后，屏幕上留下一片空白。
    latest = [0]

    def _show_panel() -> None:
        panel.scale = ft.Scale(_PANEL_REST_SCALE, alignment=origin[0])
        panel.opacity = 0
        panel.visible = True
        page.update()
        token = latest[0] = latest[0] + 1

        async def _grow() -> None:
            await asyncio.sleep(_PAINT_SETTLE_MS / 1000)
            if token != latest[0]:
                return
            panel.scale = ft.Scale(1, alignment=origin[0])
            panel.opacity = 1
            page.update()

        page.run_task(_grow)

    def _hide_panel() -> None:
        panel.scale = ft.Scale(_PANEL_REST_SCALE, alignment=origin[0])
        panel.opacity = 0
        page.update()
        token = latest[0] = latest[0] + 1

        async def _drop() -> None:
            await asyncio.sleep(theme.DURATION_BASE / 1000)
            if token != latest[0]:
                return
            panel.visible = False
            page.update()

        page.run_task(_drop)

    syllabus_ids = sorted(by_syllabus)

    def _open(syl_id: str) -> None:
        group = by_syllabus[syl_id]
        origin[0] = _panel_origin(syllabus_ids.index(syl_id), len(syllabus_ids))
        _fill_panel(
            page, panel, syl_id,
            syllabus_config().get(syl_id, {}),
            _attempts_of(group),
            _tally(group),
            _hide_panel,
        )
        _show_panel()

    cards = [
        _syllabus_card(syl_id, by_syllabus[syl_id], _open)
        for syl_id in syllabus_ids
    ]
    # 一行两张。落单的那张后面垫一个等宽的空位，否则它会独自铺满整行，
    # 跟上面每张的宽度对不上。
    rows: list[ft.Control] = []
    for i in range(0, len(cards), _CARDS_PER_ROW):
        row = cards[i:i + _CARDS_PER_ROW]
        row += [ft.Container(expand=True)] * (_CARDS_PER_ROW - len(row))
        # 别给 vertical_alignment=STRETCH：这一行挂在滚动列里，竖直方向没有
        # 约束，而 stretch 要求子控件填满竖直范围 —— 布局阶段就崩，整节一片
        # 空白，Python 侧不报错。两张卡的内容结构一样，本来就一样高。
        rows.append(ft.Row(row, spacing=theme.SPACE_MD))

    summary = ft.Container(
        ft.Row(
            [
                _donut(
                    _DONUT_BIG, overall,
                    center=_donut_center(
                        str(overall.total), "总体", _DONUT_BIG,
                    ),
                ),
                ft.Container(width=theme.SPACE_XL),
                _legend(overall),
                ft.Container(expand=True),
                ft.Column(
                    [
                        _stat(
                            "平均",
                            f"{fmean(completed):.1f}%" if completed else "—",
                        ),
                        _stat(
                            "最高",
                            f"{max(completed):.1f}%" if completed else "—",
                        ),
                        _stat("学科", f"{len(by_syllabus)} 门"),
                    ],
                    spacing=theme.SPACE_SM,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                    tight=True,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.card_shadow(),
        padding=theme.SPACE_XL,
    )

    return ft.Column([summary, *rows], spacing=theme.SPACE_MD)
