"""把三个子页装进一个 Tabs，并管理它的高度。"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from app_flet.state import AppState


from app_flet.components.widgets import section_title
from app_flet.tabs.download.by_id import build_by_id_tab
from app_flet.tabs.download.gt import build_by_gt_tab
from app_flet.tabs.download.request import build_request_tab

# 标签页内容区高度 = 窗口高 - 它上面那些东西的高度。
# 不能用 expand：外层 content_area 是 scroll=AUTO 的 Column，滚动容器里高度无界，
# expand 撑不出约束，TabBarView 会按内在高度铺开 —— 那正是页面底下拖出一大截空白的原因。
# 高度是算出来的，就必须跟着窗口走，见 build_download_tab 里的 on_resize。
#
# 拆成具名的几项而不是一个数：一个光秃秃的数看不出以后动页头/标题时该改
# 哪一项，具名之后改对应那一项就行。导航栏在左侧一列，不占这里的垂直空间。
#: 页头 Container：上下 padding 各 12 + Material 按钮 40。
_HEADER_H = 64
#: 页内标题 Container：top padding 20 + 24pt 文字行盒约 32。
_TITLE_H = 52
#: build_download_tab 里 Column 的 spacing。
_TITLE_GAP = 8
_TAB_CHROME_H = _HEADER_H + _TITLE_H + _TITLE_GAP
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

    tabs: ft.Tabs = ft.Tabs(
        length=3,
        selected_index=0,
        height=_tab_height(),
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="按考季查询"),
                        ft.Tab(label="按 ID 下载"),
                        ft.Tab(label="分数线"),
                    ]
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        build_request_tab(
                            page, state, show_snack, resize_hooks,
                        ),
                        build_by_id_tab(page, state, show_snack),
                        build_by_gt_tab(page, state, show_snack),
                    ],
                ),
            ],
        ),
    )

    # 高度是算出来的，就得跟着窗口走：不接 on_resize 的话，最大化之后标签页
    # 还停在开窗时那个高度，下面留一大块白。page.on_resize 全仓没别人用
    # （其它页都是建页时读 page.width 决定布局），这里独占。
    def _on_page_resize(_: ft.ControlEvent) -> None:
        # on_resize fires continuously while the window is dragged. Pushing a
        # full page.update() on every one of those events — each re-diffing a
        # tab that may hold a many-row table — is what made resizing lock up,
        # so only touch the UI when something actually changed.
        new_height = _tab_height()
        changed = new_height != tabs.height
        if changed:
            tabs.height = new_height
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
                    # outer Container; this one can't — the sub-tabs below
                    # must run edge to edge — so the title carries its own
                    # padding and has to match that 20 by hand.
                    padding=ft.Padding(left=20, right=20, top=20, bottom=0),
                ),
                tabs,
            ],
            spacing=8,
        ),
        padding=0,
    )
