from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.dialogs import show_delete_dialog
from app_flet.components.widgets import data_table, section_title, status_badge
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
            ft.Text("暂无记录，请先下载试卷。", size=16, color=theme.MUTED),
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
                        show_snack("文件路径不存在", theme.DANGER)  # type: ignore[operator]
                        return
                    res = manager.open_pdf(path)
                    if not res.success:
                        show_snack(f"打开失败: {res.error}", theme.DANGER)  # type: ignore[operator]
                return handler

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(r.paper_id)),
                        ft.DataCell(status_badge(r.status)),
                        ft.DataCell(
                            ft.Text(
                                f"{r.score_raw}/{r.score_total}"
                                if r.score_raw is not None
                                else "—",
                            )
                        ),
                        ft.DataCell(
                            ft.Text(
                                f"{pct:.1f}%" if pct is not None else "—",
                            )
                        ),
                        ft.DataCell(
                            ft.Row([
                                ft.IconButton(
                                    ft.CupertinoIcons.DOC_TEXT,
                                    tooltip="打开 QP",
                                    on_click=_make_open_handler(r.qp_path),  # type: ignore[arg-type]
                                    icon_size=18,
                                ),
                                ft.IconButton(
                                    ft.CupertinoIcons.DOC_CHECKMARK,
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
            data_table(
                columns=[
                    ft.DataColumn(label=ft.Text("Paper ID")),
                    ft.DataColumn(label=ft.Text("状态")),
                    ft.DataColumn(label=ft.Text("分数")),
                    ft.DataColumn(label=ft.Text("百分比")),
                    ft.DataColumn(label=ft.Text("操作")),
                ],
                rows=rows,
            ),
        ]

    def _build_list_view() -> list[ft.Control]:
        filtered = records
        if hide_toggle.value:
            filtered = [r for r in records if r.status == "Pending"]

        if not filtered:
            return [ft.Text("没有匹配的记录。", color=theme.MUTED)]

        cards: list[ft.Control] = [hide_toggle]
        for record in filtered:
            pct = record.percentage

            def _make_actions(
                rec: PaperRecord = record,
            ) -> list[ft.Control]:
                btns: list[ft.Control] = [
                    ft.IconButton(
                        ft.CupertinoIcons.DOC_TEXT,
                        tooltip="打开 QP",
                        on_click=lambda _, p=rec.qp_path: _open_pdf(p),
                        icon_size=18,
                    ),
                    ft.IconButton(
                        ft.CupertinoIcons.DOC_CHECKMARK,
                        tooltip="打开 MS",
                        on_click=lambda _, p=rec.ms_path: _open_pdf(p),
                        icon_size=18,
                    ),
                ]
                if state.mail_config and rec.qp_path:
                    btns.append(
                        ft.IconButton(
                            ft.CupertinoIcons.PAPERPLANE,
                            tooltip="发送到 GoodNotes",
                            on_click=lambda _, rid=rec.paper_id, rqp=rec.qp_path: _send_gn(rid, rqp),  # noqa: E501
                            icon_size=18,
                        )
                    )
                btns.append(
                    ft.IconButton(
                        ft.CupertinoIcons.TRASH,
                        tooltip="删除",
                        icon_color=theme.DANGER,
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
                                        ),
                                    ], spacing=4),
                                    ft.Text(
                                        score_text,
                                        size=13,
                                    ),
                                    ft.Text(
                                        timestamp_text,
                                        size=11,
                                        color=theme.MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Row(_make_actions(record), spacing=0),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border=ft.Border.all(1, theme.HAIRLINE),
                    border_radius=8,
                    padding=ft.Padding(left=12, right=8, top=8, bottom=8),
                )
            )

        return cards

    def _open_pdf(path: str | None) -> None:
        if not path:
            show_snack("文件路径不存在", theme.DANGER)  # type: ignore[operator]
            return
        res = manager.open_pdf(path)
        if not res.success:
            show_snack(f"打开失败: {res.error}", theme.DANGER)  # type: ignore[operator]

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
            show_snack(f"已发送到 {result.recipient}", theme.SUCCESS)  # type: ignore[operator]
        else:
            show_snack(f"发送失败: {result.error}", theme.DANGER)  # type: ignore[operator]

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

    return ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        section_title("管理试卷"),
                        ft.Container(expand=True),
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
