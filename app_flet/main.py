"""CIE Helper — Flet cross-platform app.

Run with:  uv run flet run app_flet
"""
from __future__ import annotations

import flet as ft

from app_flet.components.dialogs import show_settings_dialog
from app_flet.state import AppState
from app_flet.tabs.analytics import build_analytics_tab
from app_flet.tabs.download import build_download_tab
from app_flet.tabs.manage import build_manage_tab
from app_flet.tabs.mark import build_mark_tab
from core.settings import GraderConfig, MailConfig, app_settings


def main(page: ft.Page) -> None:
    page.title = "CIE Helper"
    page.theme_mode = ft.ThemeMode.LIGHT
    _color_scheme = ft.ColorScheme(
        on_surface=ft.Colors.BLACK,
        primary=ft.Colors.BLUE,
    )
    page.theme = ft.Theme(
        font_family="PingFang SC",
        color_scheme=_color_scheme,
        text_theme=ft.TextTheme(
            body_medium=ft.TextStyle(
                font_family="PingFang SC",
                color=ft.Colors.BLACK,
                font_family_fallback=[
                    "Microsoft YaHei",
                    "Noto Sans SC",
                    "sans-serif",
                ],
            ),
            body_large=ft.TextStyle(color=ft.Colors.BLACK),
            body_small=ft.TextStyle(color=ft.Colors.BLACK),
            label_large=ft.TextStyle(color=ft.Colors.BLACK),
            label_medium=ft.TextStyle(color=ft.Colors.BLACK),
            label_small=ft.TextStyle(color=ft.Colors.BLACK),
            title_medium=ft.TextStyle(color=ft.Colors.BLACK),
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

    # ── Shared file pickers (services — created once, reused) ───────
    ms_picker = ft.FilePicker()
    answer_picker = ft.FilePicker()
    page.services.extend([ms_picker, answer_picker])

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
        page.update()

    def on_nav_change(e: ft.ControlEvent) -> None:
        _switch_tab(e.control.selected_index)  # type: ignore[attr-defined]

    navbar = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.DOWNLOAD, label="下载"),
            ft.NavigationBarDestination(icon=ft.Icons.LIST_ALT, label="管理"),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART, label="统计"),
            ft.NavigationBarDestination(icon=ft.Icons.EDIT, label="批改"),
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
                ft.IconButton(
                    ft.Icons.SETTINGS,
                    tooltip="设置",
                    on_click=lambda _: show_settings_dialog(page, state),
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
