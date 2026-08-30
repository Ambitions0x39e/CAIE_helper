from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.dialogs import show_delete_dialog
from app_flet.components.widgets import (
    data_table,
    push_track,
    section_title,
    segmented_strip,
    status_badge,
)
from core.models import PaperRecord
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import PaperManager

if TYPE_CHECKING:
    from app_flet.state import AppState

#: 两个视图在分段条上的先后。序号即推拉的方向，也是 state.manage_view 存的值。
_DATABASE = "Database"
_LIST = "List"
_VIEWS = (_DATABASE, _LIST)


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

    view_index = _VIEWS.index(state.manage_view) if state.manage_view in _VIEWS else 0
    content_area, show_view = push_track(
        page, len(_VIEWS), ft.Column(), start=view_index,
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
                        ft.DataCell(
                            ft.Text(r.paper_id, style=theme.numeric_style())
                        ),
                        ft.DataCell(status_badge(r.status)),
                        ft.DataCell(
                            ft.Text(
                                f"{r.score_raw}/{r.score_total}"
                                if r.score_raw is not None
                                else "—",
                                style=theme.numeric_style(),
                            )
                        ),
                        ft.DataCell(
                            ft.Text(
                                f"{pct:.1f}%" if pct is not None else "—",
                                style=theme.numeric_style(),
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
        # 开关每次重建。旧视图在过渡期间还挂在客户端上，复用同一个控件对象
        # 会让它同时出现在新旧两棵树里 —— 状态存在 state 里，重建不丢。
        hide_toggle = ft.Switch(
            label="隐藏已完成",
            value=state.hide_completed,
            on_change=on_hide_toggle,
        )
        filtered = records
        if state.hide_completed:
            filtered = [r for r in records if r.status == "Pending"]

        if not filtered:
            return [hide_toggle, ft.Text("没有匹配的记录。", color=theme.MUTED)]

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
                                            style=theme.numeric_style(),
                                        ),
                                    ], spacing=4),
                                    ft.Text(
                                        score_text,
                                        size=theme.BODY,
                                    ),
                                    ft.Text(
                                        timestamp_text,
                                        size=theme.MICRO,
                                        color=theme.MUTED,
                                        style=theme.caption_style(),
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
        index = _VIEWS.index(state.manage_view)
        # 每次给一个**新的** Column：换的是格子里挂的是谁，原地 clear +
        # extend 会把旧树销毁掉，Flutter 侧就没有可供补间的东西。
        #
        # 序号没变时 push_track 只换内容不推 —— 勾「隐藏已完成」走的就是这条，
        # 同一个视图重新过滤一遍，推一下会读成换了页。
        show_view(index, ft.Column(
            _build_database_view() if state.manage_view == _DATABASE
            else _build_list_view()
        ))

    def on_view_change(index: int) -> None:
        state.manage_view = _VIEWS[index]
        _rebuild_content()

    def on_hide_toggle(e: ft.Event[ft.Switch]) -> None:
        state.hide_completed = e.control.value or False
        _rebuild_content()

    view_selector = segmented_strip(
        ["数据库", "列表"], on_view_change, selected=view_index,
    )

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
