from __future__ import annotations

import flet as ft

from app_flet import theme


def metric_card(label: str, value: str, color: str) -> ft.Container:
    # No fixed height — it auto-sizes to the content so a wide value (e.g.
    # "123/150", "100.0%") wraps within the card instead of overflowing the
    # old fixed 110x85 box. Width is comfortable for a 7-char value at size 24.
    return ft.Container(
        ft.Column(
            [
                ft.Text(label, size=12, color=theme.MUTED),
                ft.Text(
                    value,
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        width=132,
        border_radius=12,
        border=ft.Border.all(1, theme.HAIRLINE),
        padding=12,
        alignment=ft.Alignment(0, 0),
    )


def status_badge(status: str) -> ft.Container:
    return ft.Container(
        ft.Text(status, size=12, color=theme.ON_FILLED),
        bgcolor=theme.SUCCESS if status == "Completed" else theme.WARNING,
        border_radius=12,
        padding=ft.Padding(left=8, right=8, top=2, bottom=2),
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(
        text,
        size=24,
        weight=ft.FontWeight.BOLD,
    )


def success_banner(message: str, details: list[str] | None = None) -> ft.Container:
    controls: list[ft.Control] = [
        ft.Row([
            ft.Icon(ft.Icons.CHECK_CIRCLE, color=theme.SUCCESS),
            ft.Text(message, weight=ft.FontWeight.BOLD),
        ]),
    ]
    for d in details or []:
        controls.append(ft.Text(d, size=12, color=theme.MUTED))
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=theme.SUCCESS_TINT,
        border_radius=8,
        padding=16,
    )


def error_banner(message: str) -> ft.Container:
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ERROR, color=theme.DANGER),
            ft.Text(message),
        ]),
        bgcolor=theme.DANGER_TINT,
        border_radius=8,
        padding=16,
    )
