"""Assembles the Mark tab from its sections and owns the rebuild loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.widgets import (
    push_track,
    section_title,
    segmented_strip,
)
from app_flet.tabs.mark.context import MarkTabContext
from app_flet.tabs.mark.grade_step import build_check_step
from app_flet.tabs.mark.mcq import build_mcq_flow
from app_flet.tabs.mark.results import (
    build_detail_panel,
    build_results,
    refresh_detail_panel,
)
from app_flet.tabs.mark.setup_step import build_setup_step
from core.models import PaperType

if TYPE_CHECKING:
    from app_flet.state import AppState

# 固定框高度 = 窗口高 - 它上面/外面那些东西。不能用 expand：main.py 的
# content_area 是 scroll=AUTO 的 Column，滚动容器里高度无界，expand 撑不出
# 约束，这一页会按内在高度铺开 —— 那样详情浮层会跟着内容一起滚，就不是浮层了。
# 算出来的高度必须跟着窗口走，见 build_mark_tab 里的 on_resize。
#: 页头 Container：上下 padding 各 12 + Material 按钮 40。
_HEADER_H = 64
#: 页头顶部 + 轨道底部两处边距。外层 Container 的 padding 是 0，边距下放给了
#: 这两处（裁剪边界要贴着页面边缘，见 build_mark_tab）。
_TAB_PADDING_H = theme.SPACE_XL * 2
_FRAME_MIN_H = 320
_FALLBACK_PAGE_H = 800

#: 三步的名字，顺序就是流程顺序。
_STEPS = ("选卷", "核对", "结果")
#: 导航条两侧那两条单格的格宽。两边给同一个值，整条才是对称的 —— 不给的话
#: 「前一步」三个字比「回到当前步骤」六个字窄一半。
_SIDE_CELL_W = 108


def build_mark_tab(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    ms_picker: ft.FilePicker,
    answer_picker: ft.FilePicker,
) -> ft.Container:
    # 外层滚动列只装两样：不动的页头，和会推拉的轨道。当前这一步的内容列
    # 每次 rebuild 新建，挂到 ctx.content 上供各 section 追加控件。
    scroll_col = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO)
    ctx = MarkTabContext(
        page=page,
        state=state,
        show_snack=show_snack,
        ms_picker=ms_picker,
        answer_picker=answer_picker,
        content=ft.Column(),
        thinking=(
            state.grader_config.enable_thinking
            if state.grader_config else False
        ),
    )

    panel = build_detail_panel(ctx)
    ctx.detail_panel = panel

    # 页头（标题 + 导航条）不参与推拉：推的是步骤的内容，导航条是**指着**步骤
    # 的东西，跟着一起滑就等于它也在换。所以它待在轨道外面，每次重画。
    bar_slot = ft.Container()
    header = ft.Container(
        ft.Column([section_title("AI 批改"), bar_slot], spacing=theme.SPACE_MD),
        padding=ft.Padding(
            left=theme.SPACE_XL, right=theme.SPACE_XL,
            top=theme.SPACE_XL, bottom=0,
        ),
    )
    # 边距交给轨道内部而不是套在外面：套在外面裁剪边界就退到边距内侧，滑动的
    # 那一页会在离边缘还有 20px 的地方凭空出现，中间留一条白边。
    #
    # fill 留 False：轨道挂在 content 那根滚动列里，高度无界，撑满会向无穷大
    # 要尺寸。
    track, show_step = push_track(
        page, len(_STEPS), ft.Column(),
        padding=ft.Padding(
            left=theme.SPACE_XL, right=theme.SPACE_XL,
            top=theme.SPACE_MD, bottom=theme.SPACE_XL,
        ),
    )
    scroll_col.controls.extend([header, track])

    def rebuild() -> None:
        ctx.sync_page_inputs()

        if state.paper_type is PaperType.MCQ:
            # MCQ 不分步：它的批改/展示逻辑还没重做（见 specs 的排除项），
            # 分步得等那次重做一起给，现在切开只会把一个待改的流程切成三段。
            # 借第 0 格当普通容器用——它从不换格，也就从不推拉。
            bar_slot.content = None
            body, step = _mcq_body(ctx), 0
        else:
            _sync_steps(ctx)
            bar_slot.content = _step_bar(ctx)
            body, step = _step_body(ctx), ctx.view_step

        # 浮层活在轨道之外，上面那些都碰不到它 —— 每次都要单独刷。
        refresh_detail_panel(ctx)
        # ctx.content 指的是**当前这一步的内容列**，不是外层滚动列：section
        # 往里追加进度条之类的东西时，要落在轨道格子内侧，跟着这一步一起推拉。
        ctx.content = ft.Column(body, spacing=theme.SPACE_MD)
        # show 自己收尾 page.update()；步没换时它只换内容不动画，所以每次
        # rebuild 都能无脑调 —— 勾一个框不会触发一次推拉。
        show_step(step, ctx.content)

    ctx.rebuild = rebuild
    rebuild()

    def _frame_height() -> int:
        return max(
            _FRAME_MIN_H,
            int(page.height or _FALLBACK_PAGE_H)
            - _HEADER_H - _TAB_PADDING_H,
        )

    # scroll_col 不定位，在 Stack 里铺满整个框并自己滚；panel 贴右上角浮在它
    # 上面，
    # 高度交给内容自己长（见 build_detail_panel）。页面边距下放给了 header 和
    # 轨道各自去带（见上面推拉那段），所以浮层的位置得自己补出同样的内缩。
    panel.right = theme.SPACE_XL
    panel.top = theme.SPACE_XL
    frame = ft.Stack([scroll_col, panel], height=_frame_height())

    # 高度是算出来的，就得跟着窗口走：不接 on_resize 的话，最大化之后框还停在
    # 开窗时那个高度，下面留一大块白。每个 tab 切进来都会重建，所以这里的赋值
    # 总是当前 tab 的 —— 上一个 tab 挂的那个已经没人看了。
    def _on_page_resize(_: ft.ControlEvent) -> None:
        new_height = _frame_height()
        if new_height == frame.height:
            return
        frame.height = new_height
        page.update()

    page.on_resize = _on_page_resize  # type: ignore[assignment]

    # padding=0：页面边距下放给了 header 和推拉轨道，见 build_mark_tab 里
    # 那两段——留在这里会把裁剪边界推到边距内侧。
    return ft.Container(frame, padding=0)


# ── 三步骨架 ──────────────────────────────────────────────────────

def _reached_step(ctx: MarkTabContext) -> int:
    """流程真正走到第几步。只看状态，不看用户翻到了哪。"""
    state = ctx.state
    if state.grading_results or state.grading_in_progress:
        return 2
    if state.paper_config and state.answer_pdf_path and state.auto_pages_done:
        return 1
    return 0


def _sync_steps(ctx: MarkTabContext) -> None:
    """把进度和视图对齐到当前状态。画任何东西之前先跑一次。"""
    ctx.reached_step = max(ctx.reached_step, _reached_step(ctx))
    # 进度可能倒退（换了一份卷子），翻到的位置得跟着收回来，否则会停在一个
    # 已经没有内容的步骤上。
    ctx.view_step = min(ctx.view_step, ctx.reached_step)


def _step_body(ctx: MarkTabContext) -> list[ft.Control]:
    if ctx.view_step == 0:
        controls: list[ft.Control] = list(build_setup_step(ctx))
        if ctx.parsing:
            # 解析在跑：底下那些说的是上一份卷子，先不给。
            controls.extend(
                c for c in (ctx.parse_bar, ctx.parse_text, ctx.scan_text)
                if c is not None
            )
        return controls
    if ctx.view_step == 1:
        return build_check_step(ctx)
    return build_results(ctx)


def _step_bar(ctx: MarkTabContext) -> ft.Control:
    """三段导航条：退一格 / 直接跳 / 跳回进度所在的那一步。

    中间那条把够不着的步骤灰掉 —— 判据是**进度**（``reached_step``），不是
    你翻到了哪。往回翻不会让后面的步骤重新变灰。
    """
    def _goto(step: int) -> None:
        ctx.view_step = max(0, min(step, ctx.reached_step))
        ctx.rebuild()

    prev = segmented_strip(
        ["前一步"],
        lambda _: _goto(ctx.view_step - 1),
        selected=-1,
        cell_width=_SIDE_CELL_W,
        disabled=() if ctx.view_step > 0 else (0,),
    )
    steps = segmented_strip(
        list(_STEPS),
        _goto,
        selected=ctx.view_step,
        disabled=range(ctx.reached_step + 1, len(_STEPS)),
    )
    current = segmented_strip(
        ["回到当前步骤"],
        lambda _: _goto(ctx.reached_step),
        selected=-1,
        cell_width=_SIDE_CELL_W,
        disabled=() if ctx.view_step < ctx.reached_step else (0,),
    )
    # 三条挨在一起当一整条读。间距取的是 segmented_strip 自己格与格之间的那个
    # 值 —— 条内条外一样宽，三条才连成一片而不是散成三块。
    return ft.Row(
        [prev, steps, current],
        spacing=theme.SPACE_XS,
        alignment=ft.MainAxisAlignment.CENTER,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _mcq_body(ctx: MarkTabContext) -> list[ft.Control]:
    controls: list[ft.Control] = list(build_setup_step(ctx))
    if ctx.parsing:
        controls.extend(
            c for c in (ctx.parse_bar, ctx.parse_text, ctx.scan_text)
            if c is not None
        )
        return controls
    if ctx.state.paper_config:
        controls.extend(build_mcq_flow(ctx))
    return controls
