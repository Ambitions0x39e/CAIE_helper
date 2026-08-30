"""把三个子页装进一条分段条，并管理内容区高度。"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from app_flet.state import AppState


from app_flet import theme
from app_flet.components.widgets import (
    SEGMENTED_STRIP_H,
    push_track,
    section_title,
    segmented_strip,
)
from app_flet.tabs.download.by_id import build_by_id_tab
from app_flet.tabs.download.gt import build_by_gt_tab
from app_flet.tabs.download.request import build_request_tab

# 内容区高度 = 窗口高 - 它上面那些东西的高度。
# 不能用 expand：外层 content_area 是 scroll=AUTO 的 Column，滚动容器里高度无界，
# expand 撑不出约束，子页会按内在高度铺开 —— 那正是页面底下拖出一大截空白的原因。
# 高度是算出来的，就必须跟着窗口走，见 build_download_tab 里的 on_resize。
#
# 拆成具名的几项而不是一个数：一个光秃秃的数看不出以后动页头/标题时该改
# 哪一项，具名之后改对应那一项就行。导航栏在左侧一列，不占这里的垂直空间。
#: 页头 Container：上下 padding 各 12 + Material 按钮 40。
_HEADER_H = 64
#: 页内标题那一行：上边距 20 + 24pt 文字的行盒约 32。
_TITLE_BLOCK_H = theme.SPACE_XL + 32
#: 标题→分段条→内容，两处都是同一个间隙。管理页和批改页的页头是同一个构造
#: （padding top 20 + section_title + Column spacing + 分段条，内容再隔一个
#: 同样的间隙），三个 tab 的分段条和内容起点因此落在同一条水平线上。改这里
#: 之前先看那两处。
_STACK_GAP = theme.SPACE_MD
#: 分段条到内容那一档间隙由子页自己的 top padding 带（三个子页都是
#: _STACK_GAP），所以不在这里再加一份 —— 外层 Column 的 spacing 是 0。
_TAB_CHROME_H = (
    _HEADER_H + _TITLE_BLOCK_H + _STACK_GAP + SEGMENTED_STRIP_H
)
_TAB_MIN_H = 320
_FALLBACK_PAGE_H = 800


def build_download_tab(
    page: ft.Page,
    state: AppState,
    show_snack: object,
) -> ft.Container:
    # 见 _TAB_CHROME_H 注释：滚动父容器里必须给个确定高度，不能靠 expand。
    def _tab_height() -> int:
        return max(
            _TAB_MIN_H, int(page.height or _FALLBACK_PAGE_H) - _TAB_CHROME_H
        )

    # 子页需要在窗口变宽/变窄时重排的，把回调挂进来（见 _reflow_on_resize）。
    # 回调返回「是否真的重排了」，没变化就不刷 UI。
    resize_hooks: list[Callable[[], bool]] = []

    # 三个子页只建一次，切换换的是槽位里挂的是谁 —— 重建会丢掉用户填了一半
    # 的表单和查询结果。
    views = [
        build_request_tab(page, state, show_snack, resize_hooks),
        build_by_id_tab(page, state, show_snack),
        build_by_gt_tab(page, state, show_snack),
    ]
    # 三格的先后跟分段条上的先后一致，推拉的方向就直接由它得出：往右边那一段
    # 切，旧的往左出、新的从右边推进来。
    #
    # fill=True：这块视口是定高的，松约束下格子会缩到内容的固有高度，子页的
    # expand + 内部滚动就不成立了（见 _TAB_CHROME_H）。
    track, show_view = push_track(page, len(views), views[0], fill=True)
    # 高度留在最外面这一层：它是视口的尺寸，不跟着内容走。
    body = ft.Container(track, height=_tab_height())

    def _show(index: int) -> None:
        show_view(index, views[index])

    strip = segmented_strip(
        ["按考季查询", "按 ID 下载", "分数线"], _show,
    )

    # 高度是算出来的，就得跟着窗口走：不接 on_resize 的话，最大化之后内容区
    # 还停在开窗时那个高度，下面留一大块白。批改页出于同样的理由也挂
    # page.on_resize —— 每切一次 tab 整页都会重建，所以这个槽位里总是当前
    # tab 的那一个，两边不会打架。
    def _on_page_resize(_: ft.ControlEvent) -> None:
        # on_resize fires continuously while the window is dragged. Pushing a
        # full page.update() on every one of those events — each re-diffing a
        # sub-page that may hold a many-row table — is what made resizing lock
        # up, so only touch the UI when something actually changed.
        new_height = _tab_height()
        changed = new_height != body.height
        if changed:
            body.height = new_height
        for hook in resize_hooks:
            changed = hook() or changed
        if changed:
            page.update()

    page.on_resize = _on_page_resize  # type: ignore[assignment]

    # 页头和管理页 / 批改页是同一个构造：标题和分段条装在一条 spacing 为
    # _STACK_GAP 的 Column 里，外面 padding top 20、bottom 0，内容再隔同一个
    # 间隙。左边距 20 跟每个子页自己带的那份对齐，三层落在同一条左边线上。
    header = ft.Container(
        ft.Column(
            [
                section_title("下载试卷"),
                # 分段条自己按文字长度撑开，装在一条居中的 Row 里才落在页面
                # 中线上；标题仍然靠左。
                ft.Row([strip], alignment=ft.MainAxisAlignment.CENTER),
            ],
            spacing=_STACK_GAP,
        ),
        padding=ft.Padding(
            left=theme.SPACE_XL, right=theme.SPACE_XL,
            top=theme.SPACE_XL, bottom=0,
        ),
    )

    return ft.Container(
        ft.Column([header, body], spacing=0),
        padding=0,
    )
