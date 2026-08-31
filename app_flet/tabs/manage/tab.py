"""把【管理】的三节串起来，并托管总览那层明细浮层。"""
from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.widgets import (
    push_track,
    section_title,
    segmented_strip,
)
from app_flet.tabs.manage.mistakes import build_mistakes
from app_flet.tabs.manage.organize import build_organize
from app_flet.tabs.manage.overview import build_overview

if TYPE_CHECKING:
    from collections.abc import Callable

    from app_flet.state import AppState

#: 三节在分段条上的先后。序号即推拉的方向，也是 ``state.manage_view`` 存的值。
_SECTIONS = ("overview", "organize", "mistakes")
_LABELS = ("总览", "整理", "错题")

# 固定框高度 = 窗口高 - 它上面/外面那些东西。不能用 expand：main.py 的
# content_area 是 scroll=AUTO 的 Column，滚动容器里高度无界，expand 撑不出
# 约束，明细浮层会跟着内容一起滚，就不是浮层了。同 mark 页那一套。
#: 页头 Container：上下 padding 各 12 + Material 按钮 40。
_HEADER_H = 64
#: 页头顶部 + 轨道底部两处边距。
_TAB_PADDING_H = theme.SPACE_XL * 2
_FRAME_MIN_H = 320
_FALLBACK_PAGE_H = 800


def build_manage_tab(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    refresh_cb: Callable[[], None],
    export_picker: ft.FilePicker,
) -> ft.Container:
    # 浮层建一次，内容由 overview 在点开某个 syllabus 时填（见 _fill_panel）。
    # 它盖满整个内容区 —— 左边的导航栏和顶上的页头还在，照样点得动。
    panel = ft.Container(
        bgcolor=theme.PAGE_BG,
        padding=theme.SPACE_XL,
        left=0,
        top=0,
        right=0,
        bottom=0,
        # 展开是从被点的那张卡长成整页：缩放的原点由 overview 按卡片在网格里
        # 的行列给（见 _panel_origin），这两条补间只管走完那段路。
        animate_scale=ft.Animation(theme.DURATION_BASE, theme.CURVE_PAGE),
        animate_opacity=ft.Animation(theme.DURATION_BASE, theme.CURVE_PAGE),
        visible=False,
    )

    def _section(index: int) -> ft.Control:
        if index == 0:
            return build_overview(page, state, panel)
        if index == 1:
            return build_organize(page, state, show_snack, refresh_cb)
        return build_mistakes(page, state, show_snack, export_picker)

    if state.manage_view not in _SECTIONS:
        state.manage_view = _SECTIONS[0]
    index = _SECTIONS.index(state.manage_view)

    # 边距交给轨道内部而不是套在外面：套在外面裁剪边界就退到边距内侧，滑动的
    # 那一节会在离边缘还有 20px 的地方凭空出现，中间留一条白边。
    #
    # fill 留 False：轨道挂在滚动列里，高度无界，撑满会向无穷大要尺寸。
    track, show_section = push_track(
        page, len(_SECTIONS), ft.Column(),
        start=index,
        padding=ft.Padding(
            left=theme.SPACE_XL, right=theme.SPACE_XL,
            top=theme.SPACE_MD, bottom=theme.SPACE_XL,
        ),
    )

    def _on_section_change(i: int) -> None:
        state.manage_view = _SECTIONS[i]
        # 换节等于离开总览那一层，浮层跟着收 —— 留着它，切到「整理」看到的
        # 还是上一节的明细。
        panel.visible = False
        show_section(i, ft.Column([_section(i)]))

    header = ft.Container(
        ft.Column(
            [
                section_title("管理"),
                # 分段条自己按文字长度撑开，装在一条居中的 Row 里才落在页面
                # 中线上；标题仍然靠左。
                ft.Row(
                    [segmented_strip(
                        list(_LABELS), _on_section_change, selected=index,
                    )],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=theme.SPACE_MD,
        ),
        padding=ft.Padding(
            left=theme.SPACE_XL, right=theme.SPACE_XL,
            top=theme.SPACE_XL, bottom=0,
        ),
    )

    show_section(index, ft.Column([_section(index)]))
    scroll_col = ft.Column([header, track], spacing=0, scroll=ft.ScrollMode.AUTO)

    def _frame_height() -> int:
        return max(
            _FRAME_MIN_H,
            int(page.height or _FALLBACK_PAGE_H) - _HEADER_H - _TAB_PADDING_H,
        )

    frame = ft.Stack([scroll_col, panel], height=_frame_height())

    # 高度是算出来的，就得跟着窗口走：不接 on_resize 的话，最大化之后框还停在
    # 开窗时那个高度，下面留一大块白。每个 tab 切进来都会重建，所以这里的赋值
    # 总是当前 tab 的。
    def _on_page_resize(_: ft.ControlEvent) -> None:
        new_height = _frame_height()
        if new_height == frame.height:
            return
        frame.height = new_height
        page.update()

    page.on_resize = _on_page_resize  # type: ignore[assignment]

    # padding=0：页面边距下放给了 header 和推拉轨道，留在这里会把裁剪边界推到
    # 边距内侧。
    return ft.Container(frame, padding=0)
