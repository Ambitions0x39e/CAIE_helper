from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft
from pydantic import ValidationError

from app_flet import theme
from modules.manager import PaperManager, ScoreUpdate

if TYPE_CHECKING:
    from app_flet.state import AppState


def _fmt_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        field = " → ".join(str(loc) for loc in err["loc"]) if err["loc"] else "input"
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"• {field}: {msg}")
    return "\n".join(lines)


def show_score_dialog(
    page: ft.Page,
    state: AppState,
    on_submitted: ft.ControlEvent | None = None,
    refresh_cb: object = None,
) -> None:
    records = state.store.load_all()
    pending_ids = [
        r.paper_id for r in records if r.status == "Pending"
    ]

    if not pending_ids:
        _show_alert(page, "没有待提交的试卷", "所有试卷已完成! 🎉")
        return

    paper_dropdown = ft.Dropdown(
        label="选择试卷",
        label_style=theme.field_label_style(),
        options=[ft.dropdown.Option(pid) for pid in pending_ids],
        value=pending_ids[0],
    )
    raw_field = ft.TextField(
        label="得分",
        label_style=theme.field_label_style(),
        keyboard_type=ft.KeyboardType.NUMBER,
        value="0",
    )
    total_field = ft.TextField(
        label="满分",
        label_style=theme.field_label_style(),
        keyboard_type=ft.KeyboardType.NUMBER,
        value="100",
    )
    error_text = ft.Text("", color=theme.DANGER, visible=False)
    dlg: ft.AlertDialog | None = None

    def on_submit(_: ft.ControlEvent) -> None:
        try:
            update = ScoreUpdate(
                paper_id=paper_dropdown.value or "",
                score_raw=float(raw_field.value or 0),
                score_total=float(total_field.value or 0),
            )
        except (ValidationError, ValueError) as exc:
            error_text.value = (
                _fmt_validation_error(exc)
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            error_text.visible = True
            page.update()
            return

        manager = PaperManager(store=state.store)
        result = manager.submit_score(update)
        if dlg is not None:
            dlg.open = False
        page.update()

        if result.success and refresh_cb:
            refresh_cb()  # type: ignore[operator]

    dlg = ft.AlertDialog(
        title=ft.Text("提交分数"),
        content=ft.Column(
            [
                paper_dropdown,
                ft.Row([raw_field, total_field]),
                error_text,
            ],
            tight=True,
            spacing=12,
        ),
        actions=[
            ft.TextButton(
                "取消",
                on_click=lambda _: _close_dialog(page, dlg),  # type: ignore[arg-type]
            ),
            ft.Button(
                "提交",
                on_click=on_submit,  # type: ignore[arg-type]
                style=theme.filled_button(),
            ),
        ],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def show_delete_dialog(
    page: ft.Page,
    paper_id: str,
    state: AppState,
    refresh_cb: object = None,
) -> None:
    from modules.manager import DeleteRequest

    delete_files_cb = ft.Checkbox(
        label="同时删除本地文件", value=False,
    )
    dlg: ft.AlertDialog | None = None

    def on_confirm(_: ft.ControlEvent) -> None:
        try:
            req = DeleteRequest(
                paper_id=paper_id,
                delete_local_files=delete_files_cb.value or False,
            )
        except ValidationError:
            return

        manager = PaperManager(store=state.store)
        result = manager.delete(req)
        if dlg is not None:
            dlg.open = False
        page.update()

        if result.success and refresh_cb:
            refresh_cb()  # type: ignore[operator]

    dlg = ft.AlertDialog(
        title=ft.Text(f"删除 {paper_id}?"),
        content=delete_files_cb,
        actions=[
            ft.TextButton(
                "取消",
                on_click=lambda _: _close_dialog(page, dlg),  # type: ignore[arg-type]
            ),
            ft.Button(
                "确认删除",
                on_click=on_confirm,  # type: ignore[arg-type]
                style=theme.filled_button(theme.DANGER),
            ),
        ],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def _show_alert(page: ft.Page, title: str, message: str) -> None:
    dlg: ft.AlertDialog | None = None

    dlg = ft.AlertDialog(
        title=ft.Text(title),
        content=ft.Text(message),
        actions=[
            ft.TextButton(
                "确定",
                on_click=lambda _: _close_dialog(page, dlg),  # type: ignore[arg-type]
            ),
        ],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def _close_dialog(page: ft.Page, dlg: ft.AlertDialog) -> None:
    dlg.open = False
    page.update()
