from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft
from pydantic import ValidationError

from core.settings import GraderConfig, MailConfig
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
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        options=[ft.dropdown.Option(pid) for pid in pending_ids],
        value=pending_ids[0],
        color=ft.Colors.BLACK,
    )
    raw_field = ft.TextField(
        label="得分",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        keyboard_type=ft.KeyboardType.NUMBER,
        value="0",
        color=ft.Colors.BLACK,
    )
    total_field = ft.TextField(
        label="满分",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        keyboard_type=ft.KeyboardType.NUMBER,
        value="100",
        color=ft.Colors.BLACK,
    )
    error_text = ft.Text("", color=ft.Colors.RED, visible=False)
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
        title=ft.Text("提交分数", color=ft.Colors.BLACK),
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
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
                ),
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
        title=ft.Text(f"删除 {paper_id}?", color=ft.Colors.BLACK),
        content=delete_files_cb,
        actions=[
            ft.TextButton(
                "取消",
                on_click=lambda _: _close_dialog(page, dlg),  # type: ignore[arg-type]
            ),
            ft.Button(
                "确认删除",
                on_click=on_confirm,  # type: ignore[arg-type]
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.RED,
                    color=ft.Colors.WHITE,
                ),
            ),
        ],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def show_settings_dialog(page: ft.Page, state: AppState) -> None:
    saved_mail = MailConfig.try_load()
    saved_grader = GraderConfig.try_load()

    smtp_server = ft.TextField(
        label="SMTP Server",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        value=(
            (saved_mail.smtp_server if saved_mail else "smtp.gmail.com")
            or "smtp.gmail.com"
        ),
        color=ft.Colors.BLACK,
    )
    smtp_port = ft.TextField(
        label="SMTP Port",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        value=str(saved_mail.smtp_port if saved_mail else 465),
        keyboard_type=ft.KeyboardType.NUMBER,
        color=ft.Colors.BLACK,
    )
    sender_email = ft.TextField(
        label="Sender Email",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        value=str(saved_mail.sender_email) if saved_mail else "",
        color=ft.Colors.BLACK,
    )
    sender_password = ft.TextField(
        label="App Password",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        password=True,
        can_reveal_password=True,
        value=(
            saved_mail.sender_app_password.get_secret_value()
            if saved_mail and saved_mail.sender_app_password
            else ""
        ),
        color=ft.Colors.BLACK,
    )
    goodnotes_email = ft.TextField(
        label="GoodNotes Import Email",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        value=str(saved_mail.goodnotes_email) if saved_mail else "",
        color=ft.Colors.BLACK,
    )

    grader_api_key = ft.TextField(
        label="API Key",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        password=True,
        can_reveal_password=True,
        value=(
            saved_grader.api_key.get_secret_value() if saved_grader else ""
        ),
        color=ft.Colors.BLACK,
    )
    grader_base_url = ft.TextField(
        label="Base URL",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        value=(
            saved_grader.base_url
            if saved_grader
            else "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        color=ft.Colors.BLACK,
    )
    grader_model = ft.TextField(
        label="Model",
        label_style=ft.TextStyle(color=ft.Colors.BLACK),
        value=saved_grader.model if saved_grader else "qwen3-vl-flash",
        color=ft.Colors.BLACK,
    )
    status_text = ft.Text("", size=12)
    dlg: ft.AlertDialog | None = None

    def on_save(_: ft.ControlEvent) -> None:
        # Save mail config
        if all([
            smtp_server.value,
            sender_email.value,
            sender_password.value,
            goodnotes_email.value,
        ]):
            try:
                mc = MailConfig(
                    smtp_server=smtp_server.value or "",
                    smtp_port=int(smtp_port.value or 465),
                    sender_email=sender_email.value or "",
                    sender_app_password=sender_password.value or "",
                    goodnotes_email=goodnotes_email.value or "",
                )
                mc.save_to_env()
                state.mail_config = mc
            except (ValidationError, OSError) as exc:
                status_text.value = f"SMTP 保存失败: {exc}"
                status_text.color = ft.Colors.RED
                page.update()
                return

        # Save grader config
        if grader_api_key.value:
            try:
                gc = GraderConfig(
                    api_key=grader_api_key.value or "",
                    base_url=grader_base_url.value
                    or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    model=grader_model.value or "qwen3-vl-flash",
                )
                gc.save_to_env()
                state.grader_config = gc
            except (ValidationError, OSError) as exc:
                status_text.value = f"Grader 保存失败: {exc}"
                status_text.color = ft.Colors.RED
                page.update()
                return

        status_text.value = "✅ 已保存"
        status_text.color = ft.Colors.GREEN
        page.update()

    dlg = ft.AlertDialog(
        title=ft.Text("设置", color=ft.Colors.BLACK),
        content=ft.Column(
            [
                ft.Text(
                    "SMTP / GoodNotes",
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLACK,
                ),
                smtp_server,
                smtp_port,
                sender_email,
                sender_password,
                goodnotes_email,
                ft.Divider(),
                ft.Text(
                    "Grader API (Qwen-VL)",
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLACK,
                ),
                grader_api_key,
                grader_base_url,
                grader_model,
                status_text,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            width=400,
            height=500,
        ),
        actions=[
            ft.TextButton(
                "关闭",
                on_click=lambda _: _close_dialog(page, dlg),  # type: ignore[arg-type]
            ),
            ft.Button(
                "保存",
                on_click=on_save,  # type: ignore[arg-type]
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE,
                    color=ft.Colors.WHITE,
                ),
            ),
        ],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def _show_alert(page: ft.Page, title: str, message: str) -> None:
    dlg: ft.AlertDialog | None = None

    dlg = ft.AlertDialog(
        title=ft.Text(title, color=ft.Colors.BLACK),
        content=ft.Text(message, color=ft.Colors.BLACK),
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
