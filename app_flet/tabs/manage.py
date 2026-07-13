from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from app_flet.components.dialogs import (
    show_delete_dialog,
    show_score_dialog,
)
from app_flet.components.widgets import status_badge
from core.models import PaperRecord
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import PaperManager

if TYPE_CHECKING:
    from app_flet.state import AppState


def build_manage_tab(
    page: ft.Page,
    state: AppState,
    show_snack: object,
    refresh_cb: object,
) -> ft.Container:
    records = state.store.load_all()
    if not records:
        return ft.Container(
            ft.Text("暂无记录，请先下载试卷。", size=16, color=ft.Colors.GREY),
            padding=40,
        )

    manager = PaperManager(store=state.store)

    view_selector = ft.SegmentedButton(
        segments=[
            ft.Segment(value="Database", label=ft.Text("数据库")),
            ft.Segment(value="List", label=ft.Text("列表")),
        ],
        selected=[state.manage_view],
        allow_multiple_selection=False,
    )
    content_area = ft.Column()
    hide_toggle = ft.Switch(
        label="隐藏已完成",
        value=state.hide_completed,
        label_text_style=ft.TextStyle(color=ft.Colors.BLACK),
    )

    def _build_database_view() -> list[ft.Control]:
        rows: list[ft.DataRow] = []
        for r in records:
            pct = r.percentage

            def _make_open_handler(
                path: str | None,
            ) -> object:
                def handler(
                    _: ft.ControlEvent,
                ) -> None:
                    if not path:
                        show_snack("文件路径不存在", ft.Colors.RED)  # type: ignore[operator]
                        return
                    res = manager.open_pdf(path)
                    if not res.success:
                        show_snack(f"打开失败: {res.error}", ft.Colors.RED)  # type: ignore[operator]
                return handler

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(r.paper_id, color=ft.Colors.BLACK)),
                        ft.DataCell(status_badge(r.status)),
                        ft.DataCell(
                            ft.Text(
                                f"{r.score_raw}/{r.score_total}"
                                if r.score_raw is not None
                                else "—",
                                color=ft.Colors.BLACK,
                            )
                        ),
                        ft.DataCell(
                            ft.Text(
                                f"{pct:.1f}%" if pct is not None else "—",
                                color=ft.Colors.BLACK,
                            )
                        ),
                        ft.DataCell(
                            ft.Row([
                                ft.IconButton(
                                    ft.Icons.DESCRIPTION,
                                    tooltip="打开 QP",
                                    on_click=_make_open_handler(r.qp_path),  # type: ignore[arg-type]
                                    icon_size=18,
                                ),
                                ft.IconButton(
                                    ft.Icons.FACT_CHECK,
                                    tooltip="打开 MS",
                                    on_click=_make_open_handler(r.ms_path),  # type: ignore[arg-type]
                                    icon_size=18,
                                ),
                            ], spacing=0)
                        ),
                    ]
                )
            )

        return [
            ft.Row(
                [
                    ft.DataTable(
                        columns=[
                            ft.DataColumn(
                                label=ft.Text("Paper ID", color=ft.Colors.BLACK),
                            ),
                            ft.DataColumn(
                                label=ft.Text("状态", color=ft.Colors.BLACK),
                            ),
                            ft.DataColumn(
                                label=ft.Text("分数", color=ft.Colors.BLACK),
                            ),
                            ft.DataColumn(
                                label=ft.Text("百分比", color=ft.Colors.BLACK),
                            ),
                            ft.DataColumn(
                                label=ft.Text("操作", color=ft.Colors.BLACK),
                            ),
                        ],
                        rows=rows,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        border_radius=8,
                        heading_row_color=ft.Colors.BLUE_50,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
        ]

    def _build_list_view() -> list[ft.Control]:
        filtered = records
        if hide_toggle.value:
            filtered = [r for r in records if r.status == "Pending"]

        if not filtered:
            return [ft.Text("没有匹配的记录。", color=ft.Colors.GREY)]

        cards: list[ft.Control] = [hide_toggle]
        for record in filtered:
            pct = record.percentage

            def _make_actions(
                rec: PaperRecord = record,
            ) -> list[ft.Control]:
                btns: list[ft.Control] = [
                    ft.IconButton(
                        ft.Icons.DESCRIPTION,
                        tooltip="打开 QP",
                        on_click=lambda _, p=rec.qp_path: _open_pdf(p),
                        icon_size=18,
                    ),
                    ft.IconButton(
                        ft.Icons.FACT_CHECK,
                        tooltip="打开 MS",
                        on_click=lambda _, p=rec.ms_path: _open_pdf(p),
                        icon_size=18,
                    ),
                ]
                if state.mail_config and rec.qp_path:
                    btns.append(
                        ft.IconButton(
                            ft.Icons.SEND,
                            tooltip="发送到 GoodNotes",
                            on_click=lambda _, rid=rec.paper_id, rqp=rec.qp_path: _send_gn(rid, rqp),  # noqa: E501
                            icon_size=18,
                        )
                    )
                btns.append(
                    ft.IconButton(
                        ft.Icons.DELETE,
                        tooltip="删除",
                        icon_color=ft.Colors.RED,
                        on_click=lambda _, rid=rec.paper_id: show_delete_dialog(
                            page, rid, state, refresh_cb=refresh_cb
                        ),
                        icon_size=18,
                    )
                )
                return btns

            score_text = (
                f"{record.score_raw}/{record.score_total} ({pct:.1f}%)"
                if record.score_raw is not None and pct is not None
                else "待完成"
            )

            timestamp_text = (
                record.timestamp.strftime("%Y-%m-%d %H:%M")
                if record.timestamp
                else ""
            )

            cards.append(
                ft.Container(
                    ft.Row(
                        [
                            # Left meta column flexes and keeps the score with
                            # it, so only the fixed-width action buttons sit on
                            # the right — the row can't overflow on a phone.
                            ft.Column(
                                [
                                    ft.Row([
                                        ft.Text(
                                            "✅"
                                            if record.status == "Completed"
                                            else "⏳",
                                            size=14,
                                        ),
                                        ft.Text(
                                            record.paper_id,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.BLACK,
                                        ),
                                    ], spacing=4),
                                    ft.Text(
                                        score_text,
                                        size=13,
                                        color=ft.Colors.BLACK,
                                    ),
                                    ft.Text(
                                        timestamp_text,
                                        size=11,
                                        color=ft.Colors.GREY,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Row(_make_actions(record), spacing=0),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=8,
                    padding=ft.Padding(left=12, right=8, top=8, bottom=8),
                )
            )

        return cards

    def _open_pdf(path: str | None) -> None:
        if not path:
            show_snack("文件路径不存在", ft.Colors.RED)  # type: ignore[operator]
            return
        res = manager.open_pdf(path)
        if not res.success:
            show_snack(f"打开失败: {res.error}", ft.Colors.RED)  # type: ignore[operator]

    def _send_gn(paper_id: str, qp_path: str) -> None:
        if not state.mail_config:
            return
        try:
            mail_req = MailRequest(paper_id=paper_id, qp_path=qp_path)
        except Exception:  # noqa: BLE001
            return
        mailer = GoodNotesMailer(config=state.mail_config, store=state.store)
        result = mailer.send(mail_req)
        if result.success:
            show_snack(f"已发送到 {result.recipient}", ft.Colors.GREEN)  # type: ignore[operator]
        else:
            show_snack(f"发送失败: {result.error}", ft.Colors.RED)  # type: ignore[operator]

    def _rebuild_content() -> None:
        content_area.controls.clear()
        selected = view_selector.selected[0] if view_selector.selected else "Database"
        state.manage_view = selected
        if selected == "Database":
            content_area.controls.extend(_build_database_view())
        else:
            content_area.controls.extend(_build_list_view())
        page.update()

    def on_view_change(_: ft.ControlEvent) -> None:
        _rebuild_content()

    def on_hide_toggle(_: ft.ControlEvent) -> None:
        state.hide_completed = hide_toggle.value or False
        _rebuild_content()

    view_selector.on_change = on_view_change  # type: ignore[assignment]
    hide_toggle.on_change = on_hide_toggle  # type: ignore[assignment]

    # Initial build
    _rebuild_content()

    submit_btn = ft.Button(
        "提交分数",
        icon=ft.Icons.EDIT,
        on_click=lambda _: show_score_dialog(
            page, state, refresh_cb=refresh_cb,
        ),
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
        ),
    )

    return ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            "管理试卷",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLACK,
                        ),
                        ft.Container(expand=True),
                        submit_btn,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=4),
                view_selector,
                ft.Container(height=8),
                content_area,
            ]
        ),
        padding=20,
    )
