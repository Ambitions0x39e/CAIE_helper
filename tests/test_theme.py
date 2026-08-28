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
    PILL_RADIUS,
    SEGMENTED_STRIP_H,
    hoverable,
    segmented_strip,
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
