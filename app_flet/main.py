"""CIE Helper — Flet cross-platform app.

Run with:  uv run flet run app_flet
"""
from __future__ import annotations

import logging

import flet as ft
from flet_pdf_render import PdfRenderer

from app_flet.components.dialogs import show_score_dialog
from app_flet.state import AppState
from app_flet.tabs.analytics import build_analytics_tab
from app_flet.tabs.download import build_download_tab
from app_flet.tabs.manage import build_manage_tab
from app_flet.tabs.mark import build_mark_tab
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
        on_surface=ft.Colors.BLACK,
        primary=ft.Colors.BLUE,
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
            color=ft.Colors.BLACK,
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
    page.window.width = 960
    page.window.height = 700
    page.bgcolor = ft.Colors.WHITE
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
    pdf_renderer = PdfRenderer()  # native pdfrx renderer (iOS-safe)
    page.services.extend([ms_picker, answer_picker, pdf_renderer])
    state.pdf_renderer = pdf_renderer

    def show_snack(msg: str, color: str = ft.Colors.AMBER) -> None:
        snackbar.content = ft.Text(msg)
        snackbar.bgcolor = color
        snackbar.open = True
        page.update()

    # ── Content area ────────────────────────────────────────────────
    content_area = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def refresh_current_tab() -> None:
        idx = navbar.selected_index
        _switch_tab(idx)

    def _switch_tab(idx: int) -> None:
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
                    page, state, show_snack,
                    ms_picker, answer_picker,
                    refresh_cb=refresh_current_tab,
                )
            )
        elif idx == 4:
            content_area.controls.append(
                build_settings_tab(page, state)
            )
        page.update()

    def on_nav_change(e: ft.ControlEvent) -> None:
        _switch_tab(e.control.selected_index)  # type: ignore[attr-defined]

    navbar = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.DOWNLOAD, label="下载"),
            ft.NavigationBarDestination(icon=ft.Icons.LIST_ALT, label="管理"),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART, label="统计"),
            ft.NavigationBarDestination(icon=ft.Icons.EDIT, label="批改"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="设置"),
        ],
        selected_index=0,
        on_change=on_nav_change,  # type: ignore[arg-type]
    )

    # ── Header bar ──────────────────────────────────────────────────
    header = ft.Container(
        ft.Row(
            [
                ft.Icon(ft.Icons.SCHOOL, color=ft.Colors.BLUE),
                ft.Text(
                    "CIE Helper",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLACK,
                ),
                ft.Container(expand=True),
                ft.Button(
                    "登记成绩",
                    icon=ft.Icons.PLAYLIST_ADD_CHECK,
                    tooltip="为待完成的试卷登记分数",
                    on_click=lambda _: show_score_dialog(
                        page, state, refresh_cb=refresh_current_tab,
                    ),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
                    ),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=20, right=12, top=12, bottom=12),
        bgcolor=ft.Colors.BLUE_50,
    )

    # ── Layout ──────────────────────────────────────────────────────
    page.navigation_bar = navbar

    # Initial tab
    content_area.controls.append(build_download_tab(page, state, show_snack))

    page.add(
        ft.SafeArea(
            ft.Column(
                [header, content_area],
                expand=True,
                spacing=0,
            ),
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.run(main)
