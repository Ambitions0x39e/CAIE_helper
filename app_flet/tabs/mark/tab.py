"""Assembles the Mark tab from its sections and owns the rebuild loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.widgets import section_title, segmented_strip
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
#: 本页外层 Container 自己的上下 padding。
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
    content = ft.Column(spacing=theme.SPACE_MD, scroll=ft.ScrollMode.AUTO)
    ctx = MarkTabContext(
        page=page,
        state=state,
        show_snack=show_snack,
        ms_picker=ms_picker,
        answer_picker=answer_picker,
        content=content,
        thinking=(
            state.grader_config.enable_thinking
            if state.grader_config else False
        ),
    )

    panel = build_detail_panel(ctx)
    ctx.detail_panel = panel

    def rebuild() -> None:
        ctx.sync_page_inputs()
        content.controls.clear()
        content.controls.append(section_title("AI 批改"))

        if state.paper_type is PaperType.MCQ:
            # MCQ 不分步：它的批改/展示逻辑还没重做（见 specs 的排除项），
            # 分步得等那次重做一起给，现在切开只会把一个待改的流程切成三段。
            content.controls.extend(_mcq_body(ctx))
        else:
            content.controls.extend(_stepped_body(ctx))

        # 浮层活在 content 之外，上面那些 extend 碰不到它 —— 每次都要单独刷。
        refresh_detail_panel(ctx)
        page.update()

    ctx.rebuild = rebuild
    rebuild()

    def _frame_height() -> int:
        return max(
            _FRAME_MIN_H,
            int(page.height or _FALLBACK_PAGE_H)
            - _HEADER_H - _TAB_PADDING_H,
        )

    # content 不定位，在 Stack 里铺满整个框并自己滚；panel 贴右上角浮在它上面，
    # 高度交给内容自己长（见 build_detail_panel）。
    frame = ft.Stack([content, panel], height=_frame_height())

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

    return ft.Container(frame, padding=theme.SPACE_XL)


# ── 三步骨架 ──────────────────────────────────────────────────────

def _reached_step(ctx: MarkTabContext) -> int:
    """流程真正走到第几步。只看状态，不看用户翻到了哪。"""
    state = ctx.state
    if state.grading_results or state.grading_in_progress:
        return 2
    if state.paper_config and state.answer_pdf_path and state.auto_pages_done:
        return 1
    return 0


def _stepped_body(ctx: MarkTabContext) -> list[ft.Control]:
    ctx.reached_step = max(ctx.reached_step, _reached_step(ctx))
    # 进度可能倒退（换了一份卷子），翻到的位置得跟着收回来，否则会停在一个
    # 已经没有内容的步骤上。
    ctx.view_step = min(ctx.view_step, ctx.reached_step)

    controls: list[ft.Control] = [_step_bar(ctx)]
    if ctx.view_step == 0:
        controls.extend(build_setup_step(ctx))
        if ctx.parsing:
            # 解析在跑：底下那些说的是上一份卷子，先不给。
            controls.extend(
                c for c in (ctx.parse_bar, ctx.parse_text, ctx.scan_text)
                if c is not None
            )
    elif ctx.view_step == 1:
        controls.extend(build_check_step(ctx))
    else:
        controls.extend(build_results(ctx))
    return controls


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
