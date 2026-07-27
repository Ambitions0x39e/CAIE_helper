"""Settings tab — entry list that drills down into sub-pages.

Was a single flat inline form listing every credential at once; now it's a
Settings-app-style menu: tapping "SMTP / GoodNotes", "Grader API" or "关于"
pushes a full ``ft.View`` onto ``page.views``, which gives a native
slide-in transition and AppBar back button on every platform (including
iOS edge-swipe-back).

Each sub-page loads its own config fresh on open and saves independently,
so no global routing is involved: we push/pop ``page.views`` directly and
never call ``page.go`` or touch ``on_route_change`` / ``on_view_pop``.

Within a sub-page every setting is one row — label flush left, its control
flush right, hairline between rows — collapsing to a stacked layout below
``_NARROW_WIDTH`` so the form still works on a phone.
"""
from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft
from pydantic import ValidationError

from core.settings import GraderConfig, MailConfig

if TYPE_CHECKING:
    from app_flet.state import AppState

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_APP_NAME = "CIE Helper"
_ISSUES_URL = "https://github.com/Ambitions0x39e/CAIE_helper/issues"


def _app_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return ""


def _app_icon_bytes() -> bytes | None:
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
    try:
        return icon_path.read_bytes()
    except OSError:
        return None


# ── Settings-row layout primitives ────────────────────────────────────────
#
# One visual language for the whole page: the label sits flush left, the
# control it drives sits flush right, and a hairline separates each pair.
# The field carries no floating label of its own — the row's left column IS
# the label, so repeating it inside the box would say the same thing twice.

_FIELD_WIDTH = 320
_HAIRLINE = ft.Colors.GREY_300
# Below this the label and a 320pt field cannot share a line without one of
# them being squeezed to nothing, so the row stacks instead. The app ships to
# phones and iPad as well as desktop, so the side-by-side form is a
# wide-window affordance, not the only layout.
_NARROW_WIDTH = 560


def _is_narrow(page: ft.Page) -> bool:
    return (page.width or 1024) < _NARROW_WIDTH


def _tf(
    value: str = "", *, password: bool = False,
    number: bool = False, hint: str = "",
) -> ft.TextField:
    """The right-hand input of a settings row."""
    return ft.TextField(
        value=value,
        hint_text=hint,
        password=password,
        can_reveal_password=password,
        keyboard_type=(
            ft.KeyboardType.NUMBER if number else ft.KeyboardType.TEXT
        ),
        width=_FIELD_WIDTH,
        height=42,
        text_size=14,
        color=ft.Colors.BLACK,
        content_padding=ft.Padding.symmetric(vertical=8, horizontal=12),
        border_radius=8,
        border_color=ft.Colors.GREY_400,
        focused_border_color=ft.Colors.BLUE,
    )


def _section(title: str) -> ft.Control:
    """A group heading ("Profile" / "Preferences" in the reference design)."""
    return ft.Container(
        ft.Text(
            title, size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
        ),
        padding=ft.Padding.only(top=24, bottom=6),
    )


def _row(
    label: str,
    control: ft.Control,
    *,
    description: str | None = None,
    narrow: bool = False,
) -> ft.Control:
    """Label (+ optional hint) on the left, its control hard right.

    On a narrow window the pair stacks — label above, control full width —
    rather than letting the fixed-width field crush the label.
    """
    left: list[ft.Control] = [
        ft.Text(label, size=15, color=ft.Colors.BLACK),
    ]
    if description:
        left.append(ft.Text(description, size=12, color=ft.Colors.GREY))

    if narrow:
        if isinstance(control, ft.TextField):
            control.width = None  # fill the column instead
        body: ft.Control = ft.Column(
            [*left, control], spacing=8,
        )
    else:
        body = ft.Row(
            [
                ft.Column(left, spacing=3, expand=True),
                control,
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    return ft.Container(body, padding=ft.Padding.symmetric(vertical=12))


def _divided(*rows: ft.Control) -> list[ft.Control]:
    """Interleave hairlines between rows — never leading or trailing."""
    out: list[ft.Control] = []
    for i, row in enumerate(rows):
        if i:
            out.append(
                ft.Divider(height=1, thickness=1, color=_HAIRLINE),
            )
        out.append(row)
    return out


def _actions(*controls: ft.Control) -> ft.Control:
    """Bottom action strip, right-aligned to match the field column."""
    return ft.Container(
        ft.Row(
            list(controls),
            spacing=16,
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.only(top=20),
    )


def _push(page: ft.Page, view: ft.View) -> None:
    page.views.append(view)
    page.update()


def _pop(page: ft.Page) -> None:
    if len(page.views) > 1:
        page.views.pop()
        page.update()


# --------------------------------------------------------------------------
# Sub-page: SMTP / GoodNotes
# --------------------------------------------------------------------------

def _build_mail_view(page: ft.Page, state: AppState) -> ft.View:
    saved_mail = MailConfig.try_load()
    narrow = _is_narrow(page)

    smtp_server = _tf(
        (saved_mail.smtp_server if saved_mail else "smtp.gmail.com")
        or "smtp.gmail.com",
        hint="smtp.gmail.com",
    )
    smtp_port = _tf(
        str(saved_mail.smtp_port if saved_mail else 465),
        number=True,
        hint="465",
    )
    sender_email = _tf(
        str(saved_mail.sender_email) if saved_mail else "",
        hint="you@example.com",
    )
    sender_password = _tf(
        (
            saved_mail.sender_app_password.get_secret_value()
            if saved_mail and saved_mail.sender_app_password
            else ""
        ),
        password=True,
    )
    goodnotes_email = _tf(
        str(saved_mail.goodnotes_email) if saved_mail else "",
        hint="xxxx@goodnotes.com",
    )

    status_text = ft.Text("", size=13)

    def on_save(_: ft.ControlEvent) -> None:
        if not all([
            smtp_server.value, sender_email.value,
            sender_password.value, goodnotes_email.value,
        ]):
            status_text.value = "请填写完整的 SMTP 信息"
            status_text.color = ft.Colors.RED
            page.update()
            return
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

        status_text.value = "✅ 已保存"
        status_text.color = ft.Colors.GREEN
        page.update()

    return ft.View(
        route="/settings/mail",
        appbar=ft.AppBar(
            title=ft.Text("SMTP / GoodNotes"),
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK, on_click=lambda e: _pop(page),
            ),
        ),
        controls=[
            ft.Container(
                ft.Column(
                    [
                        _section("邮件服务器"),
                        *_divided(
                            _row("SMTP Server", smtp_server, narrow=narrow),
                            _row("SMTP Port", smtp_port, narrow=narrow),
                            _row("Sender Email", sender_email, narrow=narrow),
                            _row(
                                "App Password", sender_password,
                                description="邮箱服务商生成的应用专用密码，非登录密码",
                                narrow=narrow,
                            ),
                        ),
                        _section("GoodNotes"),
                        *_divided(
                            _row(
                                "Import Email", goodnotes_email,
                                description="试卷会发送到这个地址导入 GoodNotes",
                                narrow=narrow,
                            ),
                        ),
                        _actions(
                            status_text,
                            ft.Button(
                                "保存",
                                icon=ft.Icons.SAVE,
                                on_click=on_save,  # type: ignore[arg-type]
                                style=ft.ButtonStyle(
                                    bgcolor=ft.Colors.BLUE,
                                    color=ft.Colors.WHITE,
                                ),
                            ),
                        ),
                    ],
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                ),
                padding=ft.Padding.symmetric(vertical=8, horizontal=24),
            ),
        ],
    )


# --------------------------------------------------------------------------
# Sub-page: Grader API
# --------------------------------------------------------------------------

def _build_grader_view(page: ft.Page, state: AppState) -> ft.View:
    saved_grader = GraderConfig.try_load()
    narrow = _is_narrow(page)

    grader_api_key = _tf(
        saved_grader.api_key.get_secret_value() if saved_grader else "",
        password=True,
        hint="sk-…",
    )
    grader_base_url = _tf(
        saved_grader.base_url if saved_grader else _DEFAULT_BASE_URL,
        hint=_DEFAULT_BASE_URL,
    )
    grader_model = _tf(
        saved_grader.model if saved_grader else "qwen3-vl-flash",
        hint="qwen3-vl-flash",
    )

    status_text = ft.Text("", size=13)

    def on_save(_: ft.ControlEvent) -> None:
        if not grader_api_key.value:
            status_text.value = "请填写 API Key"
            status_text.color = ft.Colors.RED
            page.update()
            return
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

    return ft.View(
        route="/settings/grader",
        appbar=ft.AppBar(
            title=ft.Text("Grader API (Qwen-VL)"),
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK, on_click=lambda e: _pop(page),
            ),
        ),
        controls=[
            ft.Container(
                ft.Column(
                    [
                        _section("模型凭证"),
                        *_divided(
                            _row(
                                "API Key", grader_api_key,
                                description="保存在本地 ~/.cie_helper/.env，不会上传",
                                narrow=narrow,
                            ),
                            _row("Base URL", grader_base_url, narrow=narrow),
                            _row(
                                "Model", grader_model,
                                description="需支持图片输入的多模态模型",
                                narrow=narrow,
                            ),
                        ),
                        _actions(
                            status_text,
                            ft.Button(
                                "保存",
                                icon=ft.Icons.SAVE,
                                on_click=on_save,  # type: ignore[arg-type]
                                style=ft.ButtonStyle(
                                    bgcolor=ft.Colors.BLUE,
                                    color=ft.Colors.WHITE,
                                ),
                            ),
                        ),
                    ],
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                ),
                padding=ft.Padding.symmetric(vertical=8, horizontal=24),
            ),
        ],
    )

# --------------------------------------------------------------------------
# Sub-page: About & Feedback
# --------------------------------------------------------------------------

def _build_about_view(page: ft.Page, state: AppState) -> ft.View:
    version = _app_version()
    icon_bytes = _app_icon_bytes()
    icon_control: ft.Control = (
        ft.Image(
            src=icon_bytes,
            width=100,
            height=100,
            border_radius=20,
            fit=ft.BoxFit.COVER,
        )
        if icon_bytes is not None
        else ft.Container(
            ft.Icon(ft.Icons.SCHOOL, size=48, color=ft.Colors.WHITE),
            width=100,
            height=100,
            border_radius=20,
            bgcolor=ft.Colors.BLUE_GREY_800,
            alignment=ft.Alignment.CENTER,
        )
    )

    async def _launch_feedback_url() -> None:
        await page.launch_url(_ISSUES_URL)

    def open_feedback(_: ft.Event[ft.Container]) -> None:
        page.run_task(_launch_feedback_url)

    return ft.View(
        route="/settings/about",
        appbar=ft.AppBar(
            title=ft.Text("关于"),
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK, on_click=lambda e: _pop(page),
            ),
        ),
        controls=[
            ft.Container(
                ft.Column(
                    [
                        # Identity block stays centred; the rows below follow
                        # the same left/right rhythm as the other sub-pages, so
                        # the column must STRETCH rather than centre them.
                        ft.Container(height=24),
                        ft.Container(
                            icon_control, alignment=ft.Alignment.CENTER,
                        ),
                        ft.Container(height=14),
                        ft.Text(
                            _APP_NAME,
                            size=20,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLACK,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            f"Version {version}" if version else "",
                            size=13,
                            color=ft.Colors.GREY,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(height=20),
                        ft.Divider(height=1, thickness=1, color=_HAIRLINE),
                        _menu_row(
                            "反馈", "在 GitHub 提交问题或建议",
                            ft.Icons.FEEDBACK_OUTLINED, open_feedback,
                        ),
                    ],
                    spacing=0,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    scroll=ft.ScrollMode.AUTO,
                ),
                padding=ft.Padding.symmetric(vertical=8, horizontal=24),
            ),
        ],
    )


# --------------------------------------------------------------------------
# Menu row helper + entry point (this is what gets embedded as the "设置" tab)
# --------------------------------------------------------------------------

def _menu_row(
    title: str,
    subtitle: str,
    icon: ft.IconData,
    on_click: Callable[[ft.Event[ft.Container]], None],
) -> ft.Container:
    """A drill-down row: same left/right rhythm as _row, chevron on the right."""
    return ft.Container(
        ft.Row(
            [
                ft.Icon(icon, color=ft.Colors.BLUE, size=20),
                ft.Column(
                    [
                        ft.Text(title, size=15, color=ft.Colors.BLACK),
                        ft.Text(subtitle, size=12, color=ft.Colors.GREY),
                    ],
                    spacing=3,
                    expand=True,
                ),
                ft.Icon(
                    ft.Icons.CHEVRON_RIGHT, color=ft.Colors.GREY, size=20,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(vertical=12, horizontal=8),
        border_radius=8,
        ink=True,
        on_click=on_click,
    )


def build_settings_tab(page: ft.Page, state: AppState) -> ft.Container:
    # Typed as the Container event rather than the looser ft.ControlEvent so
    # the handlers match Container.on_click exactly and need no type: ignore.
    def open_mail(_: ft.Event[ft.Container]) -> None:
        _push(page, _build_mail_view(page, state))

    def open_grader(_: ft.Event[ft.Container]) -> None:
        _push(page, _build_grader_view(page, state))

    def open_about(_: ft.Event[ft.Container]) -> None:
        _push(page, _build_about_view(page, state))

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
            ft.Container(height=10),
            *_divided(
                _menu_row(
                    "SMTP / GoodNotes", "邮件发送与 GoodNotes 导入地址",
                    ft.Icons.MAIL_OUTLINE, open_mail,
                ),
                _menu_row(
                    "Grader API (Qwen-VL)", "批改用的多模态模型凭证",
                    ft.Icons.SMART_TOY_OUTLINED, open_grader,
                ),
                _menu_row(
                    "关于", "版本信息与反馈",
                    ft.Icons.INFO_OUTLINE, open_about,
                ),
            ),
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )

    return ft.Container(
        body, padding=ft.Padding.symmetric(vertical=20, horizontal=24),
    )