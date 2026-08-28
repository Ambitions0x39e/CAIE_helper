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
#: 页内标题 Container：top padding 20 + 24pt 文字行盒约 32。
_TITLE_H = 52
#: build_download_tab 里 Column 的 spacing —— 标题→分段条、分段条→内容各占一次。
#: 24 是其它 tab 里标题到第一个控件的距离（管理页那条 Column 用的是 Flet 默认
#: spacing 10 + 一个 4 的间隔块 + 10），下载页跟着对齐 —— 两边的起手都是
#: padding 20 加同一个 24pt 标题，所以间隙一致就等于分段条和「数据库 / 列表」
#: 切换器落在同一条水平线上。
_STACK_GAP = 24
_TAB_CHROME_H = _HEADER_H + _TITLE_H + SEGMENTED_STRIP_H + _STACK_GAP * 2
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

    # 三个子页只建一次，切换换的是 body 里挂的是谁 —— 重建会丢掉用户填了一半
    # 的表单和查询结果。
    views = [
        build_request_tab(page, state, show_snack, resize_hooks),
        build_by_id_tab(page, state, show_snack),
        build_by_gt_tab(page, state, show_snack),
    ]
    body = ft.Container(views[0], height=_tab_height())

    def _show(index: int) -> None:
        body.content = views[index]
        page.update()

    strip = segmented_strip(
        ["按考季查询", "按 ID 下载", "分数线"], _show,
    )

    # 高度是算出来的，就得跟着窗口走：不接 on_resize 的话，最大化之后内容区
    # 还停在开窗时那个高度，下面留一大块白。page.on_resize 全仓没别人用
    # （其它页都是建页时读 page.width 决定布局），这里独占。
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

    return ft.Container(
        ft.Column(
            [
                ft.Container(
                    section_title("下载试卷"),
                    # top=20 to sit level with every other tab's title. The
                    # other tabs get it from a plain `padding=20` on their
                    # outer Container; this one can't — the sub-pages carry
                    # their own — so the title carries its own padding and has
                    # to match that 20 by hand.
                    padding=ft.Padding(
                        left=theme.SPACE_XL, right=theme.SPACE_XL,
                        top=theme.SPACE_XL, bottom=0,
                    ),
                ),
                # Same 20 as the title and as each sub-page's own padding, so
                # the three stack on one left edge.
                ft.Container(
                    strip,
                    padding=ft.Padding.symmetric(horizontal=theme.SPACE_XL),
                ),
                body,
            ],
            spacing=_STACK_GAP,
        ),
        padding=0,
    )
