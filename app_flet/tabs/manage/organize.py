"""【整理】：两种看法，Finder 的「图标」和「详细信息」。

行的样式（``finder_*``）在这里定义，错题那一节直接拿去用 —— 两处的列不一样
（一处一行是一张卷，一处一行是一道题），共用的是外观，不是列。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.dialogs import show_delete_dialog
from app_flet.components.widgets import (
    hoverable,
    push_track,
    segmented_strip,
    swap_slot,
)
from app_flet.tabs.manage.paper_icon import paper_icon, syllabus_id_of
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import PaperManager

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app_flet.state import AppState
    from core.models import PaperRecord

#: 两个视图在分段条上的先后。序号即推拉的方向，也是 ``state.organize_view``
#: 存的值。
_ICONS = "icons"
_LIST = "list"
_VIEWS = (_ICONS, _LIST)

# ── Finder 行 ─────────────────────────────────────────────────────
#
# 一行的高度是给定的，不是让内容自己长出来的：Finder 那种密排的读感全靠每行
# 一样高，交给内容长的话，有两行评语的那几行会比别的高出一截。

#: 默认行高，一行文字的量。放了下拉框/多行文字的表自己传更高的值。
FINDER_ROW_H = 34
#: 行内左右内边距，表头和数据行共用一个值，列才对得齐。
FINDER_ROW_PAD = theme.SPACE_MD


def finder_text(
    text: str,
    width: int | None = None,
    *,
    expand: bool = False,
    size: int = theme.BODY,
    color: str | None = None,
    lines: int = 1,
    tooltip: str | None = None,
    style: ft.TextStyle | None = None,
) -> ft.Control:
    """一格文字。定宽（或 ``expand``），过长省略，全文挂在悬停提示上。"""
    return ft.Container(
        ft.Text(
            text,
            size=size,
            color=color,
            max_lines=lines,
            overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=tooltip or text or None,
            style=style,
        ),
        width=None if expand else width,
        expand=expand,
    )


def finder_header(
    cells: Sequence[ft.Control], *, height: int = FINDER_ROW_H,
) -> ft.Control:
    return ft.Container(
        ft.Row(
            list(cells), spacing=theme.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=height,
        padding=ft.Padding(left=FINDER_ROW_PAD, right=FINDER_ROW_PAD, top=0, bottom=0),
        bgcolor=theme.PRIMARY_TINT,
        border=ft.Border(bottom=ft.BorderSide(1, theme.HAIRLINE)),
    )


def finder_label(
    text: str, width: int | None = None, *, expand: bool = False,
) -> ft.Control:
    """表头的一格。不挂悬停提示 —— 列名本来就是全的，提示只会挡住下一行。"""
    return ft.Container(
        ft.Text(
            text, size=theme.CAPTION, color=theme.MUTED,
            weight=ft.FontWeight.W_600, max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            style=theme.caption_style(),
        ),
        width=None if expand else width,
        expand=expand,
    )


def finder_row(
    cells: Sequence[ft.Control],
    *,
    on_click: Callable[[ft.Event[ft.Container]], None] | None = None,
    height: int = FINDER_ROW_H,
    selected: Callable[[], bool] | None = None,
) -> tuple[ft.Control, Callable[[], None]]:
    """一条 Finder 行：压紧的行高、底部一条发丝线、悬停整行提亮。
    返回 (控件, 重涂选中态的函数)。

    ``selected`` 收的是取值器不是布尔值：勾选态会在指针还停在行上的时候变，
    进场时快照一次的话，移开指针就把刚点亮的选中态擦掉了（同 ``hoverable``
    的 docstring）。选中态变了要调一次返回的那个函数 —— 底色是从取值器现问
    的，没人去问它就不会变。
    """
    def _rest() -> ft.ColorValue | None:
        return theme.PRIMARY_TINT if selected and selected() else None

    inner = ft.Container(
        ft.Row(
            list(cells), spacing=theme.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=height,
        padding=ft.Padding(
            left=FINDER_ROW_PAD, right=FINDER_ROW_PAD, top=0, bottom=0,
        ),
        bgcolor=_rest(),
        border=ft.Border(bottom=ft.BorderSide(1, theme.HAIRLINE_FAINT)),
        animate=ft.Animation(theme.DURATION_INSTANT, theme.CURVE_IN),
        on_click=on_click,
    )

    def _repaint() -> None:
        inner.bgcolor = _rest()

    return hoverable(inner, rest_bgcolor=_rest), _repaint


def finder_list(header: ft.Control, rows: Sequence[ft.Control]) -> ft.Control:
    """表头 + 行，收在一块白卡片里。

    ``clip_behavior`` 不能省：表头自己是方角的，不裁的话它的两个上角会顶出
    卡片的圆角。
    """
    return ft.Container(
        ft.Column([header, *rows], spacing=0),
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


# ── 图标视图 ──────────────────────────────────────────────────────

#: 图标那一格的边长。操作圆圈也摆在这块方地里，翻面时格子的尺寸不能变。
_ICON_CELL = 96
_ICON_SIZE = 60
#: 一颗操作圆圈的直径，和圆圈之间的缝。两行两列：34 * 2 + 8 = 76，塞得进 96。
_ACTION_SIZE = 34
_ACTION_GAP = 8
#: 一行摆几颗。上排开 QP / 开 MS，下排发送 / 删除。
_ACTIONS_PER_ROW = 2
#: 一格连文字的总宽。
_CELL_W = 116

# ── 详细信息视图的列宽 ────────────────────────────────────────────
#
# 全定宽，中间垫一个弹性空位 —— Paper ID 交给 expand 的话它会独吞整行的余量，
# 一个十四字符的 id 摊到五百多像素宽。操作列按最多的那种行（四个图标按钮）定
# 宽，按钮自己也得定死：IconButton 默认的点击区是 48 见方，跟 icon_size 无关，
# 四个就是 192，比列宽还宽，右边会溢出去。
_W_ICON, _W_NAME, _W_STATUS, _W_SCORE, _W_PCT, _W_TIME = 22, 150, 76, 88, 64, 124
_ACTION_BTN = 36
_W_ACTIONS = 4 * _ACTION_BTN
#: 窄到这个宽度以下就撤掉「时间」那列。上面几个宽度加上格间距和行内边距要
#: 776px，再加导航栏和页面边距的 125px —— 比这窄，弹性空位收到 0 也还是溢出。
_TIME_COL_MIN_PAGE_W = 920


#: 一个操作：图标、提示、颜色、点了做什么。
_Action = tuple[ft.IconData, str, str, Callable[[], None]]


def _action_circle(action: _Action) -> ft.Control:
    icon, tooltip, color, on_click = action
    return hoverable(ft.Container(
        ft.Icon(icon, size=round(_ACTION_SIZE * 0.47), color=color),
        width=_ACTION_SIZE,
        height=_ACTION_SIZE,
        border_radius=_ACTION_SIZE // 2,
        bgcolor=theme.SURFACE,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        alignment=ft.Alignment.CENTER,
        tooltip=tooltip,
        animate=ft.Animation(theme.DURATION_INSTANT, theme.CURVE_IN),
        on_click=on_click,
    ))


def _action_grid(
    actions: Sequence[_Action], on_dismiss: Callable[[], None],
) -> ft.Control:
    """两行两列的圆圈，摆在图标原来那块方地上。

    收起靠点圆圈之外的空白 —— 两行两列没有中心可以放关闭键，而外面那层
    Container 铺满整格，圆圈自己会吃掉落在它们身上的点击。
    """
    rows: list[ft.Control] = [
        ft.Row(
            [_action_circle(a) for a in actions[i:i + _ACTIONS_PER_ROW]],
            spacing=_ACTION_GAP,
            alignment=ft.MainAxisAlignment.CENTER,
            tight=True,
        )
        for i in range(0, len(actions), _ACTIONS_PER_ROW)
    ]
    return ft.Container(
        ft.Column(
            rows,
            spacing=_ACTION_GAP,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        width=_ICON_CELL,
        height=_ICON_CELL,
        alignment=ft.Alignment.CENTER,
        tooltip="点空白处收起",
        on_click=on_dismiss,
    )


# ── 整块 ──────────────────────────────────────────────────────────


def build_organize(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    refresh_cb: Callable[[], None],
) -> ft.Control:
    records = state.store.load_all()
    if not records:
        return ft.Text("暂无记录，请先下载试卷。", size=16, color=theme.MUTED)

    manager = PaperManager(store=state.store)
    if state.organize_view not in _VIEWS:
        state.organize_view = _ICONS
    start = _VIEWS.index(state.organize_view)
    # fill 留 False：这块挂在滚动列里，高度无界，撑满会向无穷大要尺寸。
    content_area, show_view = push_track(
        page, len(_VIEWS), ft.Column(), start=start,
    )

    # ── 操作 ──────────────────────────────────────────────────

    def _open_pdf(path: str) -> None:
        if not path:
            show_snack("文件路径不存在", theme.DANGER)
            return
        res = manager.open_pdf(path)
        if not res.success:
            show_snack(f"打开失败: {res.error}", theme.DANGER)

    def _send_gn(paper_id: str, qp_path: str) -> None:
        if not state.mail_config:
            return
        try:
            mail_req = MailRequest(paper_id=paper_id, qp_path=qp_path)
        except Exception:  # noqa: BLE001 — 校验失败就是不发，理由用户看不懂
            show_snack("无法发送：试卷信息不完整", theme.DANGER)
            return
        mailer = GoodNotesMailer(config=state.mail_config, store=state.store)
        result = mailer.send(mail_req)
        if result.success:
            show_snack(f"已发送到 {result.recipient}", theme.SUCCESS)
        else:
            show_snack(f"发送失败: {result.error}", theme.DANGER)

    def _actions_of(record: PaperRecord) -> list[_Action]:
        """这张卷能做的事。图标视图把它们摆成一圈，详细视图摆成一行。

        回调不收事件参数 —— flet 的 ``on_click`` 两种签名都收，而无参那种同时
        贴合 Container（圈里那颗）和 IconButton（行尾那排），一份定义供两处用。
        ``record`` 是本次调用的入参，每次调用各有一份，所以闭包直接引它就够，
        不需要拿默认参数去锁住当前值。
        """
        acts: list[_Action] = [
            (
                ft.CupertinoIcons.DOC_TEXT, "打开 QP", theme.PRIMARY,
                lambda: _open_pdf(record.qp_path),
            ),
            (
                ft.CupertinoIcons.DOC_CHECKMARK, "打开 MS", theme.PRIMARY,
                lambda: _open_pdf(record.ms_path),
            ),
        ]
        if state.mail_config and record.qp_path:
            acts.append((
                ft.CupertinoIcons.PAPERPLANE, "发送到 GoodNotes", theme.PRIMARY,
                lambda: _send_gn(record.paper_id, record.qp_path),
            ))
        acts.append((
            ft.CupertinoIcons.TRASH, "删除", theme.DANGER,
            lambda: show_delete_dialog(
                page, record.paper_id, state, refresh_cb=refresh_cb,
            ),
        ))
        return acts

    # ── 图标视图 ──────────────────────────────────────────────

    def _icon_cell(record: PaperRecord) -> ft.Control:
        """一张卷：点图标，图标那块方地翻成两行两列的操作圆圈。

        换的是常驻格子里挂的是谁，交给 ``swap_slot`` —— 淡出淡进那一段是它
        验过的，这里不要自己重写一遍。两面每次现建：换出去的那一面已经从树上
        摘掉了，同一个对象再挂回来是让它同时出现在两棵树里。
        """
        slot_ref: list[Callable[[ft.Control], None]] = []

        def _face() -> ft.Control:
            return ft.Container(
                paper_icon(
                    syllabus_id_of(record.paper_id),
                    _ICON_SIZE,
                    done=record.status == "Completed",
                ),
                width=_ICON_CELL,
                height=_ICON_CELL,
                alignment=ft.Alignment.CENTER,
                on_click=lambda: slot_ref[0](_actions()),
            )

        def _actions() -> ft.Control:
            return _action_grid(
                _actions_of(record), lambda: slot_ref[0](_face()),
            )

        slot, show = swap_slot(page, _face(), duration=theme.DURATION_FAST)
        slot_ref.append(show)
        slot.width = _ICON_CELL
        slot.height = _ICON_CELL

        pct = record.percentage
        caption = f"{pct:.0f}%" if pct is not None else "待完成"
        return ft.Container(
            ft.Column(
                [
                    slot,
                    ft.Text(
                        record.paper_id,
                        size=theme.CAPTION,
                        max_lines=2,
                        text_align=ft.TextAlign.CENTER,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        style=theme.numeric_style(size=theme.CAPTION),
                    ),
                    ft.Text(
                        caption,
                        size=theme.MICRO,
                        color=(
                            theme.MUTED if pct is None else theme.TEXT_PRIMARY
                        ),
                        style=theme.numeric_style(size=theme.MICRO),
                    ),
                ],
                spacing=theme.SPACE_XS // 2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=_CELL_W,
        )

    def _icon_view(shown: Sequence[PaperRecord]) -> ft.Control:
        return ft.Row(
            [_icon_cell(r) for r in shown],
            wrap=True,
            spacing=theme.SPACE_MD,
            run_spacing=theme.SPACE_LG,
        )

    # ── 详细信息视图 ──────────────────────────────────────────

    def _list_view(shown: Sequence[PaperRecord]) -> ft.Control:
        with_time = int(page.width or 1280) >= _TIME_COL_MIN_PAGE_W
        header = finder_header([
            finder_label("", _W_ICON),
            finder_label("Paper ID", _W_NAME),
            finder_label("状态", _W_STATUS),
            finder_label("分数", _W_SCORE),
            finder_label("%", _W_PCT),
            *([finder_label("时间", _W_TIME)] if with_time else []),
            ft.Container(expand=True),
            finder_label("操作", _W_ACTIONS),
        ])
        return finder_list(
            header,
            [finder_row(_list_cells(r, with_time=with_time))[0] for r in shown],
        )

    def _list_cells(
        record: PaperRecord, *, with_time: bool,
    ) -> list[ft.Control]:
        pct = record.percentage
        done = record.status == "Completed"
        cells: list[ft.Control] = [
            ft.Container(
                ft.Icon(
                    ft.Icons.INSERT_DRIVE_FILE_OUTLINED,
                    size=_W_ICON,
                    color=theme.SCORE_FULL if done else theme.MUTED,
                ),
                width=_W_ICON,
            ),
            finder_text(
                record.paper_id, _W_NAME,
                style=theme.numeric_style(),
            ),
            finder_text(
                "已完成" if done else "待完成", _W_STATUS,
                size=theme.CAPTION,
                color=theme.TEXT_PRIMARY if done else theme.MUTED,
                style=theme.caption_style(),
            ),
            finder_text(
                f"{record.score_raw:g}/{record.score_total:g}"
                if record.score_raw is not None
                and record.score_total is not None
                else "—",
                _W_SCORE,
                style=theme.numeric_style(),
            ),
            finder_text(
                f"{pct:.1f}%" if pct is not None else "—", _W_PCT,
                style=theme.numeric_style(),
            ),
        ]
        if with_time:
            cells.append(finder_text(
                record.timestamp.strftime("%Y-%m-%d %H:%M")
                if record.timestamp else "",
                _W_TIME,
                size=theme.CAPTION, color=theme.MUTED,
                style=theme.caption_style(),
            ))
        cells.extend([
            # 弹性空位吃掉整行的余量，前面每列才守得住自己的宽度。
            ft.Container(expand=True),
            ft.Container(
                ft.Row(
                    [
                        ft.IconButton(
                            icon, tooltip=tip, icon_color=color,
                            on_click=handler, icon_size=16,
                            width=_ACTION_BTN, height=_ACTION_BTN, padding=0,
                        )
                        for icon, tip, color, handler in _actions_of(record)
                    ],
                    spacing=0,
                    alignment=ft.MainAxisAlignment.END,
                ),
                width=_W_ACTIONS,
            ),
        ])
        return cells

    # ── 壳 ────────────────────────────────────────────────────

    def _shown() -> list[PaperRecord]:
        if state.hide_completed:
            return [r for r in records if r.status == "Pending"]
        return list(records)

    def _pane(index: int) -> ft.Control:
        shown = _shown()
        if not shown:
            return ft.Text("没有匹配的记录。", color=theme.MUTED)
        return _icon_view(shown) if index == 0 else _list_view(shown)

    def _show(index: int) -> None:
        # 每次给一个**新的** Column：换的是格子里挂的是谁，原地 clear + extend
        # 会把旧树销毁掉，Flutter 侧就没有可供补间的东西。
        #
        # 序号没变时 push_track 只换内容不推 —— 勾「隐藏已完成」走的就是这条，
        # 同一个视图重新过滤一遍，推一下会读成换了页。
        show_view(index, ft.Column([_pane(index)]))

    def _on_view_change(index: int) -> None:
        state.organize_view = _VIEWS[index]
        _show(index)

    def _on_hide_toggle(e: ft.Event[ft.Switch]) -> None:
        state.hide_completed = e.control.value or False
        _show(_VIEWS.index(state.organize_view))

    # 分段条在正中，开关贴右边。两侧各垫一个等重的弹性空位，中间那条才真的落在
    # 行的中线上 —— 只在左边垫一个的话，它会被右边的开关推得偏左。
    toolbar = ft.Row(
        [
            ft.Container(expand=True),
            segmented_strip(
                ["图标", "详细信息"], _on_view_change, selected=start,
            ),
            ft.Container(
                ft.Switch(
                    label="隐藏已完成",
                    value=state.hide_completed,
                    on_change=_on_hide_toggle,
                ),
                expand=True,
                alignment=ft.Alignment.CENTER_RIGHT,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    _show(start)
    return ft.Column([toolbar, content_area], spacing=theme.SPACE_MD)
