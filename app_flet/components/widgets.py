from __future__ import annotations

import flet as ft


def metric_card(label: str, value: str, color: str) -> ft.Container:
    return ft.Container(
        ft.Column(
            [
                ft.Text(label, size=12, color=ft.Colors.GREY),
                ft.Text(
                    value,
                    size=28,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        width=110,
        height=85,
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.GREY_300),
        padding=16,
        alignment=ft.Alignment(0, 0),
    )


def status_badge(status: str) -> ft.Container:
    return ft.Container(
        ft.Text(status, size=12, color=ft.Colors.WHITE),
        bgcolor=ft.Colors.GREEN if status == "Completed" else ft.Colors.ORANGE,
        border_radius=12,
        padding=ft.Padding(left=8, right=8, top=2, bottom=2),
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(
        text,
        size=24,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.BLACK,
    )


def success_banner(message: str, details: list[str] | None = None) -> ft.Container:
    controls: list[ft.Control] = [
        ft.Row([
            ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN),
            ft.Text(message, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
        ]),
    ]
    for d in details or []:
        controls.append(ft.Text(d, size=12, color=ft.Colors.GREY))
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=ft.Colors.GREEN_50,
        border_radius=8,
        padding=16,
    )


def error_banner(message: str) -> ft.Container:
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED),
            ft.Text(message, color=ft.Colors.BLACK),
        ]),
        bgcolor=ft.Colors.RED_50,
        border_radius=8,
        padding=16,
    )
