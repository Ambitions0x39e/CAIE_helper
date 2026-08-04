from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app_flet import theme


def data_table(
    columns: list[ft.DataColumn],
    rows: list[ft.DataRow],
    *,
    show_checkbox_column: bool = False,
    on_select_all: Callable[..., None] | None = None,
) -> ft.Row:
    """全 app 统一的表格样式，宽度铺满窗口。

    管理页和分数线页各自写过一份 DataTable，边框、圆角、表头底色不一致；
    收成一处，改一次两处都跟着变。

    **返回的是包了一层 Row 的表格**，不是裸的 DataTable：``expand`` 是沿父容器
    的主轴生效的，而这两处表格都放在 Column 里 —— 在 Column 里 expand 会往
    **竖**向撑，横向依旧只有内容宽度。套一层 Row 之后主轴才是横向，expand
    才等于「占满窗口宽度」（同 request.py 里 ``expand=True`` 的下拉框）。

    也不要再往外面套 ``Row(scroll=AUTO)``：横向滚动的行宽度无界，expand 撑不出
    约束，表格会缩回内容宽度。
    """
    return ft.Row([
        ft.DataTable(
            columns=columns,
            rows=rows,
            show_checkbox_column=show_checkbox_column,
            on_select_all=on_select_all,
            expand=True,
            border=ft.Border.all(1, theme.HAIRLINE),
            border_radius=8,
            heading_row_color=theme.PRIMARY_TINT,
        )
    ])


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
