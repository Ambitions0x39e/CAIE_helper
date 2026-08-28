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
    row_height: float | None = None,
    compact: bool = False,
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

    ``row_height`` 只给单元格里放了控件（下拉框、按钮）的表用 —— 默认行高按纯
    文本算，塞进一个下拉框会被裁掉。不传就沿用 Flet 的默认，既有调用方不受影响。

    ``compact=True`` 收紧行高、列距，并补上竖分隔线：给单元格只有一两个字符的
    密集表格用（批改页的 MCQ 答题卡，一屏要放 40 题），列一多就必须有竖线才对得
    上题号。两个都传时 ``row_height`` 说了算 —— 它是调用方给出的确切数值，
    compact 那档只是默认值。默认那档是给管理页那种整行文字的表格用的，不要动。
    """
    compact_min, compact_max = (30, 34) if compact else (None, None)
    return ft.Row([
        ft.DataTable(
            columns=columns,
            rows=rows,
            show_checkbox_column=show_checkbox_column,
            on_select_all=on_select_all,
            data_row_min_height=row_height if row_height else compact_min,
            data_row_max_height=row_height if row_height else compact_max,
            expand=True,
            border=ft.Border.all(1, theme.HAIRLINE),
            border_radius=theme.CARD_RADIUS,
            heading_row_color=theme.PRIMARY_TINT,
            heading_row_height=32 if compact else None,
            column_spacing=8 if compact else None,
            horizontal_margin=10 if compact else None,
            vertical_lines=(
                ft.BorderSide(1, theme.HAIRLINE_FAINT) if compact else None
            ),
        )
    ])


def metric_card(label: str, value: str, color: str) -> ft.Container:
    # No fixed height — it auto-sizes to the content so a wide value (e.g.
    # "123/150", "100.0%") wraps within the card instead of overflowing the
    # old fixed 110x85 box. Width is comfortable for a 7-char value at size 24.
    return ft.Container(
        ft.Column(
            [
                ft.Text(label, size=theme.CAPTION, color=theme.MUTED),
                ft.Text(
                    value,
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=theme.SPACE_XS,
        ),
        width=132,
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.card_shadow(),
        padding=theme.SPACE_MD,
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
            ft.Icon(ft.CupertinoIcons.CHECKMARK_CIRCLE_FILL, color=theme.SUCCESS),
            ft.Text(message, weight=ft.FontWeight.BOLD),
        ]),
    ]
    for d in details or []:
        controls.append(ft.Text(d, size=12, color=theme.MUTED))
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=theme.SUCCESS_TINT,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def error_banner(message: str) -> ft.Container:
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.CupertinoIcons.XMARK_CIRCLE_FILL, color=theme.DANGER),
            ft.Text(message),
        ]),
        bgcolor=theme.DANGER_TINT,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def warning_banner(message: str, details: list[str] | None = None) -> ft.Container:
    controls: list[ft.Control] = [
        ft.Row([
            ft.Icon(ft.CupertinoIcons.EXCLAMATIONMARK_CIRCLE_FILL, color=theme.WARNING),
            ft.Text(message, weight=ft.FontWeight.BOLD),
        ]),
    ]
    for d in details or []:
        controls.append(ft.Text(d, size=12, color=theme.MUTED))
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=theme.WARNING_TINT,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def loading_row(label: str) -> ft.Row:
    return ft.Row(
        [
            ft.ProgressRing(width=20, height=20),
            ft.Text(label, size=theme.CAPTION, color=theme.MUTED),
        ],
        spacing=theme.SPACE_SM,
    )
