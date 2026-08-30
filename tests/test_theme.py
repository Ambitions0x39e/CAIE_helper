"""Tests for app_flet.theme and the hover wrapper in app_flet.components.widgets.

These are the interaction states — the part of the design system that has no
static appearance to eyeball. A button whose three states all resolve to the
same colour looks completely normal in a screenshot, so the checks that matter
here are the ones asserting the states differ.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft
import pytest

from app_flet import theme
from app_flet.components.widgets import (
    _FADE_OUT_SHARE,
    PILL_RADIUS,
    SEGMENTED_STRIP_H,
    hoverable,
    push_track,
    section_title,
    segmented_strip,
    skeleton,
    swap_slot,
)

#: Every semantic colour that filled_button() is called with, by name so a
#: failure says which one.
SEMANTIC_COLORS = [
    ("PRIMARY", theme.PRIMARY),
    ("SUCCESS", theme.SUCCESS),
    ("DANGER", theme.DANGER),
    ("WARNING", theme.WARNING),
    ("ACCENT", theme.ACCENT),
    ("NEUTRAL", theme.NEUTRAL),
]

#: Curve families whose whole point is overshoot. A mouse click carries no
#: momentum, so a bounce on a desktop form is decoration with a physics
#: excuse — see the motion spec.
_OVERSHOOT_PREFIXES = ("BOUNCE_", "ELASTIC_")
_OVERSHOOT_SUFFIX = "_BACK"


def _state_map(bgcolor: str) -> dict[ft.ControlState, Any]:
    """filled_button()'s bgcolor, asserted to be a state map before returning."""
    style = theme.filled_button(bgcolor)
    assert isinstance(style.bgcolor, dict), (
        f"bgcolor must be a ControlState map, got {type(style.bgcolor).__name__}"
    )
    return style.bgcolor


class _FakePage:
    """Stands in for ft.Page off-session: counts updates, drops the tasks.

    swap_slot's second half runs in a coroutine on the page's event loop,
    which does not exist here. Everything asserted below is the first half —
    the part that runs synchronously on the click.
    """

    def __init__(self) -> None:
        self.updates = 0

    def update(self) -> None:
        self.updates += 1

    def run_task(self, handler: Any, *args: Any, **kwargs: Any) -> None:
        handler(*args, **kwargs).close()


def _fire(handler: Callable[[Any], None] | None) -> None:
    """Run a hover handler outside a live session.

    The handler repaints the control it wraps and then calls
    ``Control.update()``, which needs a page attached and raises off-screen.
    The repaint has already happened by then — that is the part under test —
    so the RuntimeError is expected, and matched on its message so an
    unrelated failure can't slip through as a pass.
    """
    assert handler is not None
    with pytest.raises(RuntimeError, match="must be added to the page first"):
        handler(None)


# ── filled_button: three states ───────────────────────────────────


@pytest.mark.parametrize(("name", "color"), SEMANTIC_COLORS)
def test_filled_button_declares_all_three_states(name: str, color: str) -> None:
    """All three states present, and default is the colour that was asked for."""
    states = _state_map(color)
    assert set(states) == {
        ft.ControlState.DEFAULT,
        ft.ControlState.HOVERED,
        ft.ControlState.PRESSED,
    }, f"{name} is missing a state"
    assert states[ft.ControlState.DEFAULT] == color


@pytest.mark.parametrize(("name", "color"), SEMANTIC_COLORS)
def test_filled_button_states_are_distinct(name: str, color: str) -> None:
    """Three states mapped to one colour would pass every structural check and
    still give the user no feedback at all."""
    states = _state_map(color)
    values = [
        states[ft.ControlState.DEFAULT],
        states[ft.ControlState.HOVERED],
        states[ft.ControlState.PRESSED],
    ]
    assert len({str(v) for v in values}) == 3, f"{name} reuses a colour: {values}"


@pytest.mark.parametrize(("name", "color"), SEMANTIC_COLORS)
def test_filled_button_drops_the_material_ripple(name: str, color: str) -> None:
    """The state map is the feedback; the default overlay would stack a second
    one on top of it."""
    assert theme.filled_button(color).overlay_color == ft.Colors.TRANSPARENT


def test_filled_button_defaults_to_primary() -> None:
    assert theme.filled_button().bgcolor == theme.filled_button(theme.PRIMARY).bgcolor


def test_filled_button_shades_cover_every_semantic_color() -> None:
    """A colour missing from the shade table silently degrades to a flat button."""
    for name, color in SEMANTIC_COLORS:
        assert color in theme._BUTTON_SHADES, f"{name} has no hover/pressed shades"


# ── motion tokens ─────────────────────────────────────────────────


def test_durations_are_ordered() -> None:
    assert (
        theme.DURATION_INSTANT
        < theme.DURATION_FAST
        < theme.DURATION_BASE
        < theme.DURATION_SLOW
    )


def test_interaction_states_are_faster_than_the_eye_leads() -> None:
    """The pointer-tracking tier has to stay far below the tier that guides the
    eye across a page — at scale-step durations it reads as lag, not feedback."""
    assert theme.DURATION_INSTANT <= 60


@pytest.mark.parametrize(
    "token", ["CURVE_IN", "CURVE_OUT", "CURVE_PAGE"],
)
def test_curves_are_real_and_never_overshoot(token: str) -> None:
    curve = getattr(theme, token)
    assert isinstance(curve, ft.AnimationCurve)
    assert not curve.name.startswith(_OVERSHOOT_PREFIXES)
    assert not curve.name.endswith(_OVERSHOOT_SUFFIX)


def test_in_and_out_curves_mirror_each_other() -> None:
    """A reversible transition has to walk the same path back."""
    assert theme.CURVE_IN == ft.AnimationCurve.EASE_OUT_CUBIC
    assert theme.CURVE_OUT == ft.AnimationCurve.EASE_IN_CUBIC


# ── hoverable ─────────────────────────────────────────────────────


def test_hoverable_wraps_in_a_gesture_detector() -> None:
    """Container.on_hover fires but never repaints; GestureDetector is the only
    hover path that works, so the wrapper must produce one."""
    inner = ft.Container()
    wrapper = hoverable(inner)
    assert isinstance(wrapper, ft.GestureDetector)
    assert wrapper.content is inner
    assert wrapper.on_enter is not None
    assert wrapper.on_exit is not None


def test_hoverable_paints_on_enter_and_restores_on_exit() -> None:
    inner = ft.Container(bgcolor=theme.SURFACE)
    wrapper = hoverable(inner, hover_bgcolor=theme.SURFACE_HOVER)

    _fire(wrapper.on_enter)
    assert inner.bgcolor == theme.SURFACE_HOVER

    _fire(wrapper.on_exit)
    assert inner.bgcolor == theme.SURFACE


def test_hoverable_hover_color_differs_from_rest() -> None:
    """Painting the resting colour on hover is the silent no-op this whole
    layer exists to prevent."""
    assert theme.SURFACE_HOVER != theme.SURFACE
    assert theme.SURFACE_HOVER != theme.PAGE_BG
    assert theme.SURFACE_PRESSED != theme.SURFACE_HOVER


def test_hoverable_asks_the_rest_provider_at_exit_not_at_build() -> None:
    """The nav rail repaints the button the pointer is sitting on: click it and
    its resting colour changes while the cursor is still inside. A colour
    captured on enter would wipe the selection back off on the way out.
    """
    inner = ft.Container(bgcolor=None)
    resting: list[str | None] = [None]
    wrapper = hoverable(inner, rest_bgcolor=lambda: resting[0])

    _fire(wrapper.on_enter)
    resting[0] = theme.SURFACE  # selection lands while the pointer is inside
    _fire(wrapper.on_exit)

    assert inner.bgcolor == theme.SURFACE


def test_surface_states_are_three_distinct_colors() -> None:
    """静息 / 悬停 / 按下 / 选中 四档铺底，任意两档撞色，那两个状态就分不出来。"""
    tints = {
        "hover": theme.SURFACE_HOVER,
        "pressed": theme.SURFACE_PRESSED,
        "selected": theme.PRIMARY_TINT,
        "page": theme.PAGE_BG,
    }
    assert len(set(tints.values())) == len(tints), tints


def test_hoverable_tints_foreground_and_restores_it() -> None:
    """底色和前景必须一起动 —— SURFACE_HOVER 在 PAGE_BG 上对比很浅，单靠底色
    读不出来。"""
    icon = ft.Icon(ft.Icons.DOWNLOAD, color=theme.MUTED)
    label = ft.Text("下载", color=theme.MUTED)
    inner = ft.Container(ft.Row([icon, label]))
    wrapper = hoverable(inner, tinted=[icon, label])

    _fire(wrapper.on_enter)
    assert icon.color == theme.TEXT_PRIMARY
    assert label.color == theme.TEXT_PRIMARY

    _fire(wrapper.on_exit)
    assert icon.color == theme.MUTED
    assert label.color == theme.MUTED


def test_hoverable_asks_the_color_provider_at_exit_too() -> None:
    """前景色跟底色同一个约定：选中状态可能在指针还在里面时变。"""
    icon = ft.Icon(ft.Icons.DOWNLOAD, color=theme.MUTED)
    resting: list[str] = [theme.MUTED]
    wrapper = hoverable(
        ft.Container(icon), tinted=[icon], rest_color=lambda: resting[0],
    )

    _fire(wrapper.on_enter)
    resting[0] = theme.PRIMARY
    _fire(wrapper.on_exit)

    assert icon.color == theme.PRIMARY


# ── segmented_strip ───────────────────────────────────────────────


def _track(strip: ft.Container) -> ft.Row:
    assert isinstance(strip.content, ft.Row)
    return strip.content


def _gestures(strip: ft.Container) -> list[ft.GestureDetector]:
    return [
        c for c in _track(strip).controls if isinstance(c, ft.GestureDetector)
    ]


def _cells(strip: ft.Container) -> list[ft.Container]:
    out: list[ft.Container] = []
    for gd in _gestures(strip):
        assert isinstance(gd.content, ft.Container)
        out.append(gd.content)
    return out


def _splits(strip: ft.Container) -> list[ft.Container]:
    """The 1px rules between segments, in order."""
    return [
        c
        for c in _track(strip).controls
        if isinstance(c, ft.Container) and c.width == 1
    ]


def _label(cell: ft.Container) -> ft.Text:
    assert isinstance(cell.content, ft.Text)
    return cell.content


def _click(strip: ft.Container, index: int) -> None:
    handler = _cells(strip)[index].on_click
    assert handler is not None
    handler(None)  # type: ignore[arg-type]


def test_segmented_strip_is_one_capsule_around_the_segments() -> None:
    strip = segmented_strip(["一", "二", "三"], lambda _: None)
    assert isinstance(strip, ft.Container)
    assert strip.bgcolor == theme.PRIMARY_TINT
    assert strip.border is not None
    assert strip.border_radius == PILL_RADIUS
    assert strip.height == SEGMENTED_STRIP_H
    assert len(_cells(strip)) == 3
    #: n 段之间有 n-1 道分隔线。
    assert len(_splits(strip)) == 2


def test_segmented_strip_hugs_its_segments() -> None:
    """胶囊只该有三段那么宽。

    ``ft.Container`` 一旦带 ``alignment``，在有界约束下就会撑满父容器 ——
    里面 Row 的 ``tight`` 拦不住它，胶囊会横铺整页。这条断言守的就是那个
    陷阱：加回 alignment 不报错、不崩溃，只是宽度悄悄变成一整行。
    """
    strip = segmented_strip(["一", "二", "三"], lambda _: None)
    assert strip.alignment is None
    assert strip.width is None
    assert not strip.expand
    assert _track(strip).tight is True


def test_segmented_strip_paints_only_the_selected_cell() -> None:
    strip = segmented_strip(["一", "二", "三"], lambda _: None)
    for i, cell in enumerate(_cells(strip)):
        label = _label(cell)
        if i == 0:
            assert cell.bgcolor == theme.SURFACE
            assert label.color == theme.PRIMARY
            assert label.weight == ft.FontWeight.W_600
        else:
            assert cell.bgcolor is None
            assert label.color == theme.MUTED
            assert label.weight == ft.FontWeight.NORMAL


def test_segmented_strip_selected_thumb_reads_lighter_than_the_track() -> None:
    """选中往浅里走、悬停往深里走，两个方向相反才不会看混。"""
    assert theme.SURFACE != theme.PRIMARY_TINT
    assert theme.SURFACE_HOVER != theme.PRIMARY_TINT


def test_segmented_strip_hides_the_splits_beside_the_selection() -> None:
    """滑块自己的边界已经把那里分开了，再画一道就是两条线叠在一起。"""
    strip = segmented_strip(["一", "二", "三"], lambda _: None)
    splits = _splits(strip)
    assert [s.visible for s in splits] == [False, True]

    _click(strip, 1)
    assert [s.visible for s in splits] == [False, False]

    _click(strip, 2)
    assert [s.visible for s in splits] == [True, False]


def test_segmented_strip_moves_the_selection_and_reports_the_index() -> None:
    picked: list[int] = []
    strip = segmented_strip(["一", "二", "三"], picked.append)
    cells = _cells(strip)

    _click(strip, 2)

    assert picked == [2]
    assert cells[0].bgcolor is None
    assert cells[2].bgcolor == theme.SURFACE
    assert _label(cells[2]).color == theme.PRIMARY


def test_segmented_strip_hover_does_not_erase_the_selection() -> None:
    """指针扫过别的段再移开，已选中那段必须原样留着 —— 这是 rest 取值器存在
    的理由。"""
    strip = segmented_strip(["一", "二", "三"], lambda _: None)
    cells = _cells(strip)
    _click(strip, 2)

    _fire(_gestures(strip)[0].on_enter)
    assert cells[0].bgcolor == theme.SURFACE_HOVER
    assert _label(cells[0]).color == theme.TEXT_PRIMARY

    _fire(_gestures(strip)[0].on_exit)
    assert cells[0].bgcolor is None
    assert _label(cells[0]).color == theme.MUTED
    assert cells[2].bgcolor == theme.SURFACE


def test_segmented_strip_hovering_the_selected_segment_keeps_the_thumb() -> None:
    """把滑块涂灰会让当前选中的那段看起来反而没被选中。"""
    strip = segmented_strip(["一", "二", "三"], lambda _: None)
    cells = _cells(strip)

    _fire(_gestures(strip)[0].on_enter)
    assert cells[0].bgcolor == theme.SURFACE
    assert _label(cells[0]).color == theme.PRIMARY


def test_hoverable_without_a_provider_restores_the_build_time_color() -> None:
    inner = ft.Container(bgcolor=theme.PRIMARY_TINT)
    wrapper = hoverable(inner)

    _fire(wrapper.on_enter)
    _fire(wrapper.on_exit)

    assert inner.bgcolor == theme.PRIMARY_TINT


# ── swap_slot ─────────────────────────────────────────────────────


def test_swap_slot_holds_one_child_at_a_time() -> None:
    """整份改动的要害。``ft.AnimatedSwitcher`` 会把新旧两份同时挂进一个居中
    对齐的 Stack，两份高度不一样时新内容先悬在半空、等旧的卸载完再弹回顶部
    —— 换 tab 和 settings 子页正是这种。这里必须是个普通 Container：同一时刻
    只有一份内容，高度在完全透明的那一刻变。
    """
    slot, _ = swap_slot(_FakePage(), ft.Column())
    assert isinstance(slot, ft.Container)
    assert not isinstance(slot, ft.AnimatedSwitcher)


def test_swap_slot_only_fades() -> None:
    """常驻容器 + 已经画出来的值改成新值，是唯一不会静默失效的补间路径。

    这一档只淡不动：横向推拉是 push_track 的事，一个容器只有一个 offset，
    做不出两页各走各的方向。"""
    slot, _ = swap_slot(_FakePage(), ft.Column())
    assert slot.animate_opacity is not None
    assert slot.animate_offset is None


def test_swap_slot_fades_out_before_it_swaps() -> None:
    """先把旧的抹掉，别把新内容直接怼上去。"""
    page = _FakePage()
    slot, show = swap_slot(page, ft.Column())
    show(ft.Text("新的"))

    assert slot.opacity == 0
    assert isinstance(slot.content, ft.Column)  # 还没换
    assert page.updates == 1


def test_swap_slot_splits_the_duration_between_out_and_in() -> None:
    """两段加起来就是这一档的时长 —— 否则接了 FAST 的地方实际比 BASE 还慢。"""
    out_ms = int(theme.DURATION_BASE * _FADE_OUT_SHARE)
    assert 0 < out_ms < theme.DURATION_BASE - out_ms


# ── push_track ────────────────────────────────────────────────────


def _panes(track: ft.Container) -> list[ft.Container]:
    """格子在裁剪层里面 —— 裁剪必须包在会动的东西**外面**。"""
    stack = track.content
    assert isinstance(stack, ft.Stack)
    return list(stack.controls)  # type: ignore[arg-type]


def _stack(track: ft.Container) -> ft.Stack:
    assert isinstance(track.content, ft.Stack)
    return track.content


def test_push_track_clip_needs_a_decoration_to_exist() -> None:
    """``clip_behavior`` 单独设是一句空话：Flet 把 bgcolor / border /
    border_radius 合成 BoxDecoration 交给 Flutter 的 Container，而 Container
    只在有 decoration 时才插 ClipPath。三者都不设就不报错也不裁，滑出去的那
    一格照样画到导航栏上 —— 这条静默失效过两轮。

    Stack 自带的 clip_behavior 顶不上：Flutter 的 Stack 只在**布局**溢出时裁，
    而 offset 是画的时候平移的，布局上每格都严丝合缝。
    """
    track, _ = push_track(_FakePage(), 2, ft.Text("a"))
    assert track.clip_behavior == ft.ClipBehavior.HARD_EDGE
    assert track.bgcolor is not None
    # 裁剪层自己不能动，否则窗口跟着内容一起走。
    assert track.offset is None
    assert track.animate_offset is None


def test_push_track_parks_panes_by_index() -> None:
    """靠前的在左边一格、当前那格在原位、靠后的在右边一格。落点只由先后决定，
    所以每格永远是从自己上一次的位置动到新位置 —— 不需要瞬移。"""
    track, _ = push_track(_FakePage(), 3, ft.Text("a"))
    assert [p.offset.x for p in _panes(track)] == [0, 1, 1]
    assert [p.opacity for p in _panes(track)] == [1.0, 0.0, 0.0]


def test_push_track_moves_both_pages_the_same_way() -> None:
    """整份改动的要害：一个容器只有一个 offset，新页进场那一侧必然是旧页退场
    那一侧，两页对着走。分成两格之后，往后一格切时旧的往左、新的也往左。"""
    track, show = push_track(_FakePage(), 3, ft.Text("a"))
    show(2, ft.Text("c"))
    left, middle, right = _panes(track)
    assert left.offset.x == -1      # 旧的往左出去
    assert middle.offset.x == -1    # 越过的那格也往左
    assert right.offset.x == 0      # 新的从右边推到原位
    assert [p.opacity for p in _panes(track)] == [0.0, 0.0, 1.0]


def test_push_track_mirrors_going_back() -> None:
    track, show = push_track(_FakePage(), 3, ft.Text("a"))
    show(2, ft.Text("c"))
    show(0, ft.Text("a"))
    assert [p.offset.x for p in _panes(track)] == [0, 1, 1]


def test_push_track_hides_the_panes_it_flies_past() -> None:
    """三格以上时中间那格会横穿整个视口，不透明就是一道闪。"""
    track, show = push_track(_FakePage(), 3, ft.Text("a"))
    show(2, ft.Text("c"))
    assert _panes(track)[1].opacity == 0.0


def test_push_track_is_top_aligned() -> None:
    """居中对齐正是 AnimatedSwitcher 让矮的那页先悬在半空的毛病。"""
    track, _ = push_track(_FakePage(), 2, ft.Text("a"))
    assert _stack(track).alignment == ft.Alignment.TOP_LEFT


def test_push_track_fills_its_box_only_when_asked() -> None:
    """定高的视口要撑满，否则格子缩到内容的固有高度，子页的 expand 和内部滚动
    就不成立了。高度无界的地方撑满则是向无穷大要尺寸。"""
    loose, _ = push_track(_FakePage(), 2, ft.Text("a"))
    assert _stack(loose).fit == ft.StackFit.LOOSE

    filled, _ = push_track(_FakePage(), 2, ft.Text("a"), fill=True)
    assert _stack(filled).fit == ft.StackFit.EXPAND


def test_push_track_puts_the_page_margin_on_the_panes() -> None:
    """边距套在轨道**外面**的话，裁剪边界就退到边距内侧，滑动的子页会在离导航栏
    还有一段的地方凭空出现和消失，中间留一条什么都不发生的白边。"""
    track, _ = push_track(
        _FakePage(), 2, ft.Text("a"), padding=theme.SPACE_XL,
    )
    assert all(p.padding == theme.SPACE_XL for p in _panes(track))


def test_push_track_seeds_the_first_pane() -> None:
    track, _ = push_track(_FakePage(), 2, ft.Text("菜单"))
    assert _panes(track)[0].content.value == "菜单"


# ── skeleton ──────────────────────────────────────────────────────


def _skeleton_rows(sk: ft.Shimmer) -> list[ft.Row]:
    assert isinstance(sk.content, ft.Column)
    rows = sk.content.controls
    assert all(isinstance(r, ft.Row) for r in rows)
    return rows  # type: ignore[return-value]


def test_skeleton_bars_use_integer_flex() -> None:
    """``expand`` 只收 bool / int：给个比例小数会在用户点下查询的那一刻才抛。"""
    for row in _skeleton_rows(skeleton()):
        for cell in row.controls:
            assert isinstance(cell.expand, int)
            assert not isinstance(cell.expand, bool)


def test_skeleton_bars_are_uneven_but_each_row_is_full() -> None:
    """长短不一才像一段真内容；每行的份数要凑满，否则唯一的 flex 子控件会一路
    撑到头，每根条都一样长。"""
    rows = _skeleton_rows(skeleton())
    assert len(rows) == 6
    for row in rows:
        assert sum(c.expand for c in row.controls) == 100  # type: ignore[misc]
    bar_widths = {row.controls[0].expand for row in rows}
    assert len(bar_widths) > 1


def test_skeleton_declares_the_colors_shimmer_requires() -> None:
    """Shimmer 没有 gradient 时必须两个颜色都给，缺一个是构造期报错。"""
    sk = skeleton()
    assert sk.base_color is not None
    assert sk.highlight_color is not None
    assert sk.base_color != sk.highlight_color


# ── 字距与行高 ────────────────────────────────────────────────────


def test_type_scale_only_sets_tracking_and_leading() -> None:
    """这几档只该覆盖两项。带上字号或颜色，接了 style 的调用点就会被反过来
    改掉它自己写的那些属性。"""
    for name in ("title_style", "section_style", "body_style", "caption_style"):
        style = getattr(theme, name)()
        assert style.letter_spacing is not None
        assert style.height is not None
        assert style.size is None
        assert style.color is None
        assert style.font_family is None


def test_tracking_runs_from_tight_at_the_top_to_loose_at_the_bottom() -> None:
    """字距的观感是相对于字号的：大字要收、小字要放。反向了同样能跑，只是每
    一档都错。"""
    assert theme.title_style().letter_spacing < 0
    assert theme.section_style().letter_spacing == 0
    assert theme.body_style().letter_spacing == 0
    assert theme.caption_style().letter_spacing > 0
    assert (
        theme.numeric_style().letter_spacing
        > theme.caption_style().letter_spacing
    )


def test_leading_is_loosest_for_running_text() -> None:
    """标题是一两行的块，正文是要读下去的段落。"""
    assert theme.body_style().height == theme.caption_style().height
    assert theme.title_style().height < theme.section_style().height
    assert theme.section_style().height < theme.body_style().height


def test_numeric_style_takes_a_size_for_slots_without_one() -> None:
    """Checkbox.label_style 这类槽位没有独立的字号属性。"""
    assert theme.numeric_style().size is None
    assert theme.numeric_style(size=theme.SUBHEAD).size == theme.SUBHEAD


def test_section_title_carries_the_page_title_metrics() -> None:
    """每个 tab 的页面标题都从这一个函数出来 —— 断在这里等于断在全部。"""
    title = section_title("下载试卷")
    assert title.size == theme.TITLE
    assert title.style is not None
    assert title.style.letter_spacing == theme.title_style().letter_spacing
    assert title.style.height == theme.title_style().height
