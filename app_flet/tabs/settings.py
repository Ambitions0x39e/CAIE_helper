"""Settings tab — SMTP / GoodNotes + Grader API credentials.

Inline form (was previously an AlertDialog opened from the header gear).
Reads current values from the saved config and writes them back to
``~/.cie_helper/.env`` on save, updating the shared AppState.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft
from pydantic import ValidationError

from core.settings import GraderConfig, MailConfig

if TYPE_CHECKING:
    from app_flet.state import AppState

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def build_settings_tab(page: ft.Page, state: AppState) -> ft.Container:
    saved_mail = MailConfig.try_load()
    saved_grader = GraderConfig.try_load()

    def _tf(
        label: str, value: str = "", *, password: bool = False,
        number: bool = False,
    ) -> ft.TextField:
        return ft.TextField(
            label=label,
            label_style=ft.TextStyle(color=ft.Colors.BLACK),
            value=value,
            password=password,
            can_reveal_password=password,
            keyboard_type=(
                ft.KeyboardType.NUMBER if number else ft.KeyboardType.TEXT
            ),
            color=ft.Colors.BLACK,
        )

    smtp_server = _tf(
        "SMTP Server",
        (saved_mail.smtp_server if saved_mail else "smtp.gmail.com")
        or "smtp.gmail.com",
    )
    smtp_port = _tf(
        "SMTP Port",
        str(saved_mail.smtp_port if saved_mail else 465),
        number=True,
    )
    sender_email = _tf(
        "Sender Email",
        str(saved_mail.sender_email) if saved_mail else "",
    )
    sender_password = _tf(
        "App Password",
        (
            saved_mail.sender_app_password.get_secret_value()
            if saved_mail and saved_mail.sender_app_password
            else ""
        ),
        password=True,
    )
    goodnotes_email = _tf(
        "GoodNotes Import Email",
        str(saved_mail.goodnotes_email) if saved_mail else "",
    )

    grader_api_key = _tf(
        "API Key",
        saved_grader.api_key.get_secret_value() if saved_grader else "",
        password=True,
    )
    grader_base_url = _tf(
        "Base URL",
        saved_grader.base_url if saved_grader else _DEFAULT_BASE_URL,
    )
    grader_model = _tf(
        "Model",
        saved_grader.model if saved_grader else "qwen3-vl-flash",
    )

    status_text = ft.Text("", size=13)

    def on_save(_: ft.ControlEvent) -> None:
        # Save mail config only when the required fields are all present.
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
            except (ValidationError, OSError, ValueError) as exc:
                status_text.value = f"SMTP 保存失败: {exc}"
                status_text.color = ft.Colors.RED
                page.update()
                return

        if grader_api_key.value:
            try:
                gc = GraderConfig(
                    api_key=grader_api_key.value or "",
                    base_url=grader_base_url.value or _DEFAULT_BASE_URL,
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

    def _section(title: str) -> ft.Text:
        return ft.Text(
            title, size=16,
            weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
        )

    body = ft.Column(
        [
            ft.Text(
                "设置", size=24,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
            ft.Text(
                "邮件与批改 API 凭证，保存到本地 ~/.cie_helper/.env",
                size=13, color=ft.Colors.GREY,
            ),
            ft.Divider(),
            _section("SMTP / GoodNotes"),
            smtp_server,
            smtp_port,
            sender_email,
            sender_password,
            goodnotes_email,
            ft.Divider(),
            _section("Grader API (Qwen-VL)"),
            grader_api_key,
            grader_base_url,
            grader_model,
            ft.Container(height=4),
            ft.Row([
                ft.Button(
                    "保存",
                    icon=ft.Icons.SAVE,
                    on_click=on_save,  # type: ignore[arg-type]
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
                    ),
                ),
                status_text,
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
    )

    return ft.Container(body, padding=20)
