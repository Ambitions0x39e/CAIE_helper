"""CIE Helper — Flet cross-platform app.

Run with:  uv run flet run app_flet
"""
from __future__ import annotations

import logging

import flet as ft
from flet_pdf_render import PdfRenderer

from app_flet import theme
from app_flet.components.dialogs import show_score_dialog
from app_flet.components.widgets import hoverable
from app_flet.state import AppState
from app_flet.tabs.analytics import build_analytics_tab
from app_flet.tabs.download import build_download_tab
from app_flet.tabs.manage import build_manage_tab
from app_flet.tabs.mark import build_mark_tab
from app_flet.tabs.mistakes import build_mistakes_tab
from app_flet.tabs.settings import build_settings_tab
from core.settings import GraderConfig, MailConfig, app_settings


def _setup_logging() -> None:
    """Route the app's own loggers to the console at INFO.

    Scoped to the ``cie_helper`` namespace so render payload sizes / timing
    show up when debugging a stuck grading run, without turning on every
    third-party library's chatter.
    """
    logger = logging.getLogger("cie_helper")
    if logger.handlers:  # already configured (hot reload)
        return
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)


def main(page: ft.Page) -> None:
    _setup_logging()
    page.title = "CIE Helper"
    page.theme_mode = ft.ThemeMode.LIGHT
    _color_scheme = ft.ColorScheme(
        on_surface=theme.TEXT_PRIMARY,
        primary=theme.PRIMARY,
    )
    # Pick a Simplified-Chinese font that actually exists on this platform.
    # "PingFang SC" is Apple-only; on Windows it's missing, so Flutter fell
    # back to a Japanese-preferring CJK font and rendered Han characters with
    # the wrong (JP/KR) glyph forms. Lead with each platform's native zh-CN
    # font; the fallback chain covers the rest. No bundled font needed —
    # every target ships a Simplified-Chinese system font.
    _zh_fallback = [
        "Microsoft YaHei", "PingFang SC",
        "Noto Sans SC", "Noto Sans CJK SC", "sans-serif",
    ]
    if page.platform == ft.PagePlatform.WINDOWS:
        _zh_font = "Microsoft YaHei"
    elif page.platform in (ft.PagePlatform.MACOS, ft.PagePlatform.IOS):
        _zh_font = "PingFang SC"
    else:  # Linux / Android
        _zh_font = "Noto Sans CJK SC"

    def _zh_style(**kw: object) -> ft.TextStyle:
        return ft.TextStyle(
            font_family=_zh_font,
            font_family_fallback=_zh_fallback,
            color=theme.TEXT_PRIMARY,
            **kw,  # type: ignore[arg-type]
        )

    page.theme = ft.Theme(
        font_family=_zh_font,
        color_scheme=_color_scheme,
        text_theme=ft.TextTheme(
            body_medium=_zh_style(),
            body_large=_zh_style(),
            body_small=_zh_style(),
            label_large=_zh_style(),
            label_medium=_zh_style(),
            label_small=_zh_style(),
            title_medium=_zh_style(),
            title_large=_zh_style(),
            title_small=_zh_style(),
        ),
    )
    page.padding = 0
    # 逻辑像素（dp），不是物理像素 —— 150% 缩放下 1280 dp 已经占掉 1920 物理
    # 像素。按物理分辨率填这两个数，窗口会被系统按到屏幕上，开起来就是满屏。
    page.window.width = 1280
    page.window.height = 800
    page.bgcolor = theme.PAGE_BG
    page.adaptive = False

    # ── Initialise ──────────────────────────────────────────────────
    app_settings.init_dirs()
    state = AppState()
    state.mail_config = MailConfig.try_load()
    state.grader_config = GraderConfig.try_load()

    # ── Shared snackbar ─────────────────────────────────────────────
    snackbar = ft.SnackBar(ft.Text(""))
    page.overlay.append(snackbar)

    # ── Shared services (created once, reused) ──────────────────────
    ms_picker = ft.FilePicker()
    answer_picker = ft.FilePicker()
    # Save-dialog for the 错题本's CSV export. Created here, once, like the
    # other pickers — building one per tab visit would stack up services.
    mistake_export_picker = ft.FilePicker()
    pdf_renderer = PdfRenderer()  # native pdfrx renderer (iOS-safe)
    page.services.extend(
        [ms_picker, answer_picker, mistake_export_picker, pdf_renderer]
    )
    state.pdf_renderer = pdf_renderer

    def show_snack(msg: str, color: str = theme.ACCENT) -> None:
        snackbar.content = ft.Text(msg)
        snackbar.bgcolor = color
        snackbar.open = True
        page.update()

    # ── Content area ────────────────────────────────────────────────
    content_area = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
    selected_index = 0

    def refresh_current_tab() -> None:
        _switch_tab(selected_index)

    def _switch_tab(idx: int) -> None:
        nonlocal selected_index
        selected_index = idx
        # Flush the rail on its own, before the tab is built. Building costs
        # single-digit milliseconds, but shipping a whole tab's control tree
        # across to Flutter and laying it out does not — and until that lands
        # the click has produced nothing on screen. This update carries a few
        # colours, so it paints immediately; the old tab stays up meanwhile,
        # which is why the rail is repainted before the content is cleared.
        _apply_nav_selection()
        page.update()
        content_area.controls.clear()
        if idx == 0:
            content_area.controls.append(
                build_download_tab(page, state, show_snack)
            )
        elif idx == 1:
            content_area.controls.append(
                build_manage_tab(
                    page, state, show_snack, refresh_cb=refresh_current_tab,
                )
            )
        elif idx == 2:
            content_area.controls.append(
                build_analytics_tab(page, state)
            )
        elif idx == 3:
            content_area.controls.append(
                build_mark_tab(
                    page, state, show_snack, ms_picker, answer_picker,
                )
            )
        elif idx == 4:
            content_area.controls.append(
                build_mistakes_tab(
                    page, state, show_snack, mistake_export_picker,
                )
            )
        elif idx == 5:
            content_area.controls.append(
                build_settings_tab(page, state)
            )
        page.update()

    # ── Side navigation ─────────────────────────────────────────────
    # A hand-rolled rail rather than ft.NavigationRail: the destinations have
    # to cluster at the top with 设置 pinned to the bottom, and the built-in
    # rail spreads / groups them on its own terms.
    #: 每个入口是一个圆角正方形：图标+文字打包成一组，整组在方形里居中。
    #: 拆成上 2/3/下 1/3 两条带会让图标和文字分别对齐，组合起来反而不居中。
    _NAV_BUTTON_SIZE = 64
    _NAV_RADIUS = round(_NAV_BUTTON_SIZE * theme.SQUIRCLE_RADIUS_RATIO, 2)
    nav_icons: list[ft.Icon] = []
    nav_labels: list[ft.Text] = []
    nav_buttons: list[ft.Container] = []

    def _make_nav_button(
        idx: int, icon: ft.IconData, label: str,
    ) -> ft.GestureDetector:
        icon_ctl = ft.Icon(icon, size=26)
        label_ctl = ft.Text(label, size=12, no_wrap=True)
        button = ft.Container(
            ft.Column(
                [icon_ctl, label_ctl],
                spacing=theme.SPACE_XS // 2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=_NAV_BUTTON_SIZE,
            height=_NAV_BUTTON_SIZE,
            border_radius=_NAV_RADIUS,
            alignment=ft.Alignment.CENTER,
            # Covers every property _apply_nav_selection() mutates on this
            # container — bgcolor, border, shadow — plus the hover wash.
            animate=ft.Animation(theme.DURATION_INSTANT, theme.CURVE_IN),
            on_click=lambda _: _switch_tab(idx),
        )
        nav_icons.append(icon_ctl)
        nav_labels.append(label_ctl)
        nav_buttons.append(button)
        return hoverable(
            button,
            tinted=[icon_ctl, label_ctl],
            rest_bgcolor=lambda: theme.SURFACE if idx == selected_index else None,
            rest_color=lambda: (
                theme.PRIMARY if idx == selected_index else theme.MUTED
            ),
        )

    def _apply_nav_selection() -> None:
        # The container's three properties fade — it carries `animate`. The
        # icon and label colours snap: in Flet 0.86.4 `animate` is
        # Container-only, and Icon/Text expose no colour tween at all.
        #
        # Icon and label share one resting colour: an entry is one object, and
        # hoverable() restores both from a single provider.
        for i, button in enumerate(nav_buttons):
            active = i == selected_index
            button.bgcolor = theme.SURFACE if active else None
            button.border = ft.Border.all(1, theme.HAIRLINE) if active else None
            button.shadow = (
                theme.row_shadow() if active else theme.row_shadow(opacity=0)
            )
            resting = theme.PRIMARY if active else theme.MUTED
            nav_icons[i].color = resting
            nav_labels[i].color = resting
            nav_labels[i].weight = (
                ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL
            )

    _main_nav = [
        _make_nav_button(0, ft.CupertinoIcons.TRAY_ARROW_DOWN, "下载"),
        _make_nav_button(1, ft.CupertinoIcons.LIST_BULLET, "管理"),
        _make_nav_button(2, ft.CupertinoIcons.CHART_BAR, "统计"),
        _make_nav_button(3, ft.CupertinoIcons.PENCIL, "批改"),
        _make_nav_button(4, ft.CupertinoIcons.BOOK, "错题本"),
    ]
    _settings_nav = _make_nav_button(5, ft.CupertinoIcons.SETTINGS, "设置")
    _apply_nav_selection()

    nav_rail = ft.Container(
        ft.Column(
            [*_main_nav, ft.Container(expand=True), _settings_nav],
            spacing=8,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=_NAV_BUTTON_SIZE + 20,
        padding=ft.Padding(left=10, right=10, top=12, bottom=12),
    )

    # ── Header bar ──────────────────────────────────────────────────
    header = ft.Container(
        ft.Row(
            [
                ft.Icon(ft.CupertinoIcons.BOOK_FILL, color=theme.PRIMARY),
                ft.Text(
                    "CIE Helper",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Container(expand=True),
                ft.Button(
                    "登记成绩",
                    icon=ft.CupertinoIcons.TEXT_BADGE_CHECKMARK,
                    tooltip="为待完成的试卷登记分数",
                    on_click=lambda _: show_score_dialog(
                        page, state, refresh_cb=refresh_current_tab,
                    ),
                    style=theme.filled_button(),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=20, right=12, top=12, bottom=12),
        bgcolor=theme.PAGE_BG,
        border=ft.Border(bottom=ft.BorderSide(1, theme.HAIRLINE)),
    )

    # ── Layout ──────────────────────────────────────────────────────
    # Initial tab
    content_area.controls.append(build_download_tab(page, state, show_snack))

    page.add(
        ft.SafeArea(
            ft.Column(
                [
                    header,
                    ft.Row(
                        [
                            nav_rail,
                            ft.VerticalDivider(width=1, color=theme.HAIRLINE),
                            content_area,
                        ],
                        expand=True,
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ],
                expand=True,
                spacing=0,
            ),
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.run(main)
