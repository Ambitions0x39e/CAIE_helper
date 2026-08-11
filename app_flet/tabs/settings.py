"""Settings tab — entry list that drills down into sub-pages.

Settings-app-style menu: tapping "SMTP / GoodNotes", "Grader API" or "关于"
swaps the tab's own content for the sub-page, with a back arrow + title row
(``_sub_header``) standing in for a real AppBar. This used to push a full
``ft.View`` onto ``page.views`` instead — that gave a native slide-in
transition and AppBar back button (including iOS edge-swipe-back), but a
pushed ``ft.View`` replaces the *entire* window, so the left-hand nav_rail
and header from main.py disappeared behind it too. Embedding keeps the tab
inside ``content_area`` like every other tab, at the cost of that native
transition/gesture.

Each sub-page loads its own config fresh on open and saves independently,
so no global routing is involved here — no ``page.views``, ``page.go``,
``on_route_change`` or ``on_view_pop``.

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

from app_flet import theme
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
_HAIRLINE = theme.HAIRLINE
# Below this the label and a 320pt field cannot share a line without one of
# them being squeezed to nothing, so the row stacks instead. The app ships to
# phones and iPad as well as desktop, so the side-by-side form is a
# wide-window affordance, not the only layout.
_NARROW_WIDTH = 560
#: main.py's nav_rail (84px) + its 1px VerticalDivider — this tab now renders
#: inside content_area, to the right of both, so page.width overstates the
#: room actually available here by that much (same gap analytics.py's chart
#: width had to account for).
_NAV_CHROME_W = 85


def _is_narrow(page: ft.Page) -> bool:
    return (page.width or 1024) - _NAV_CHROME_W < _NARROW_WIDTH


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
        content_padding=ft.Padding.symmetric(vertical=8, horizontal=12),
        border_radius=8,
        border_color=theme.FIELD_BORDER,
        focused_border_color=theme.PRIMARY,
    )


def _section(title: str) -> ft.Control:
    """A group heading ("Profile" / "Preferences" in the reference design)."""
    return ft.Container(
        ft.Text(
            title, size=18, weight=ft.FontWeight.BOLD,
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
        ft.Text(label, size=15),
    ]
    if description:
        left.append(ft.Text(description, size=12, color=theme.MUTED))

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


def _sub_header(title: str, on_back: Callable[[], None]) -> ft.Row:
    """Stands in for the AppBar a pushed ``ft.View`` used to give us for
    free: back arrow + bold title, same visual weight."""
    return ft.Row(
        [
            ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: on_back()),
            ft.Text(title, size=20, weight=ft.FontWeight.BOLD),
        ],
        spacing=4,
    )


# --------------------------------------------------------------------------
# Sub-page: SMTP / GoodNotes
# --------------------------------------------------------------------------

def _build_mail_view(
    page: ft.Page, state: AppState, on_back: Callable[[], None],
) -> ft.Column:
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
        hint="me.xxxx@goodnotes.com",
    )

    status_text = ft.Text("", size=13)

    def on_save(_: ft.ControlEvent) -> None:
        if not all([
            smtp_server.value, sender_email.value,
            sender_password.value, goodnotes_email.value,
        ]):
            status_text.value = "请填写完整的 SMTP 信息"
            status_text.color = theme.DANGER
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
            status_text.color = theme.DANGER
            page.update()
            return

        status_text.value = "✅ 已保存"
        status_text.color = theme.SUCCESS
        page.update()

    return ft.Column(
        [
            _sub_header("SMTP / GoodNotes", on_back),
            _section("邮件服务器"),
            *_divided(
                _row("SMTP Server", smtp_server, narrow=narrow),
                _row("SMTP Port", smtp_port, narrow=narrow),
                _row("Sender Email", sender_email, narrow=narrow),
                _row(
                    "App Password", sender_password,
                    description=(
                        "邮箱服务商生成的 IMAP/SMTP 专用密码，"
                        "非邮箱密码"
                    ),
                    narrow=narrow,
                ),
            ),
            _section("GoodNotes"),
            *_divided(
                _row(
                    "Import Email", goodnotes_email,
                    description="试卷会发送到这个邮箱对应账户",
                    narrow=narrow,
                ),
            ),
            _actions(
                status_text,
                ft.Button(
                    "保存",
                    icon=ft.Icons.SAVE,
                    on_click=on_save,  # type: ignore[arg-type]
                    style=theme.filled_button(),
                ),
            ),
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )


# --------------------------------------------------------------------------
# Sub-page: Grader API
# --------------------------------------------------------------------------

def _build_grader_view(
    page: ft.Page, state: AppState, on_back: Callable[[], None],
) -> ft.Column:
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
            status_text.color = theme.DANGER
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
            status_text.color = theme.DANGER
            page.update()
            return

        status_text.value = "✅ 已保存"
        status_text.color = theme.SUCCESS
        page.update()

    return ft.Column(
        [
            _sub_header("Grader API 设置", on_back),
            _section("模型凭证"),
            *_divided(
                _row(
                    "API Key", grader_api_key,
                    # description="",
                    narrow=narrow,
                ),
                _row("Base URL", grader_base_url, narrow=narrow),
                _row(
                    "Model", grader_model,
                    description="需支持图片输入的视觉/多模态模型",
                    narrow=narrow,
                ),
            ),
            _actions(
                status_text,
                ft.Button(
                    "保存",
                    icon=ft.Icons.SAVE,
                    on_click=on_save,  # type: ignore[arg-type]
                    style=theme.filled_button(),
                ),
            ),
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )

# --------------------------------------------------------------------------
# Sub-page: About & Feedback
# --------------------------------------------------------------------------

def _build_about_view(
    page: ft.Page, state: AppState, on_back: Callable[[], None],
) -> ft.Column:
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
            ft.Icon(ft.Icons.SCHOOL, size=48, color=theme.ON_FILLED),
            width=100,
            height=100,
            border_radius=20,
            bgcolor=theme.OVERLAY_DARK,
            alignment=ft.Alignment.CENTER,
        )
    )

    async def _launch_feedback_url() -> None:
        await page.launch_url(_ISSUES_URL)

    def open_feedback(_: ft.Event[ft.Container]) -> None:
        page.run_task(_launch_feedback_url)

    # ── Update ────────────────────────────────────────────────────────────
    #
    # Checking only happens on tap — never on startup. The network call and
    # the download both run on page.run_thread (same pattern as the Mark tab)
    # so the UI stays alive; the row's own subtitle doubles as the progress
    # indicator, and the row is disabled while anything is in flight.
    #
    # Finding an update is NOT permission to install one: we always ask
    # first. "Silent" only describes the installer wizard, not the decision.
    #
    # Imports are function-local because this feature is only allowed to
    # touch _build_about_view.
    import contextlib
    import os
    import time

    from modules.updater import (
        RELEASES_PAGE_URL,
        AppUpdater,
        DownloadProgress,
        UpdateCheckResult,
        format_progress,
        platform_asset_suffix,
    )

    update_idle_subtitle = "检查并安装最新版本"
    update_busy = [False]

    async def _launch_releases_page() -> None:
        await page.launch_url(RELEASES_PAGE_URL)

    def _set_update_subtitle(text: str) -> None:
        """Rewrite the row's subtitle in place — it IS the progress readout."""
        body = update_row.content
        if not isinstance(body, ft.Row):
            return
        labels = body.controls[1]
        if not isinstance(labels, ft.Column):
            return
        subtitle = labels.controls[1]
        if isinstance(subtitle, ft.Text):
            subtitle.value = text

    def _set_update_busy(busy: bool, subtitle: str) -> None:
        update_busy[0] = busy
        update_row.disabled = busy
        _set_update_subtitle(subtitle)
        page.update()

    def _alert(title: str, message: str) -> None:
        dlg: ft.AlertDialog | None = None
        dlg = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton(
                    "确定",
                    on_click=lambda _: _close(dlg),
                ),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _close(dlg: ft.AlertDialog | None) -> None:
        if dlg is not None:
            dlg.open = False
        page.update()

    def _quit_for_install() -> None:
        """Get out of the installer's way.

        Inno Setup cannot overwrite our own .exe while this process holds it
        open, so exiting is not optional — os._exit is deliberate: a clean
        shutdown could be blocked by a pending UI task and leave the file
        locked with the installer already running.
        """
        # Let the detached installer get going and the close command flush.
        time.sleep(0.8)
        with contextlib.suppress(Exception):
            page.window.close()  # type: ignore[no-untyped-call]
        os._exit(0)

    def _run_download(url: str) -> None:
        def _on_progress(progress: DownloadProgress) -> None:
            # The row's subtitle is the progress bar: size, percent and speed.
            # updater throttles these to ~3/second, so this is safe to push
            # straight to the page.
            _set_update_subtitle(f"下载中… {format_progress(progress)}")
            page.update()

        def _work() -> None:
            updater = AppUpdater()
            download = updater.download(url, on_progress=_on_progress)
            if not download.success or download.local_path is None:
                _set_update_busy(False, update_idle_subtitle)
                _alert("下载失败", f"下载更新失败：{download.error}")
                return

            _set_update_subtitle("正在安装…")
            page.update()
            install = updater.install(Path(download.local_path))
            if not install.success:
                _set_update_busy(False, update_idle_subtitle)
                _alert("安装失败", f"启动安装程序失败：{install.error}")
                return

            _quit_for_install()

        _set_update_busy(True, "下载中…")
        page.run_thread(_work)

    def _confirm_update(result: UpdateCheckResult) -> None:
        dlg: ft.AlertDialog | None = None

        def on_update_now(_: ft.ControlEvent) -> None:
            _close(dlg)
            _run_download(result.download_url or "")

        dlg = ft.AlertDialog(
            title=ft.Text(
                f"发现新版本 {result.latest_version}",
            ),
            content=ft.Column(
                [
                    ft.Text(
                        f"当前 {version or '未知'} → 新版本 "
                        f"{result.latest_version}",
                        size=13,
                        color=theme.MUTED,
                    ),
                    ft.Text(
                        result.release_notes or "（本次发布没有填写更新说明）",
                        size=13,
                    ),
                    ft.Text(
                        "下载完成后会自动安装。安装时应用会自动退出，"
                        "装好后会自己重新打开。",
                        size=12,
                        color=theme.MUTED,
                    ),
                ],
                tight=True,
                spacing=12,
                width=420,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(
                    "取消",
                    on_click=lambda _: _close(dlg),
                ),
                ft.Button(
                    "立即更新",
                    on_click=on_update_now,  # type: ignore[arg-type]
                    style=theme.filled_button(),
                ),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def on_update(_: ft.Event[ft.Container]) -> None:
        # Platforms with no installer we know how to run (Linux, iOS, …) get
        # the releases page in a browser — never an error, never a crash.
        if platform_asset_suffix() is None:
            page.run_task(_launch_releases_page)
            return
        if update_busy[0]:
            return

        def _work() -> None:
            result = AppUpdater().check()
            _set_update_busy(False, update_idle_subtitle)
            if not result.success:
                _alert("检查更新失败", f"检查更新失败：{result.error}")
                return
            if not result.update_available:
                _alert("已是最新版本", f"已是最新版本（{version or '未知'}）")
                return
            _confirm_update(result)

        _set_update_busy(True, "检查中…")
        page.run_thread(_work)

    update_row = _menu_row(
        "更新", update_idle_subtitle,
        ft.Icons.SYSTEM_UPDATE_OUTLINED, on_update,
    )

    return ft.Column(
        [
            _sub_header("关于", on_back),
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
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                f"Version {version}" if version else "",
                size=13,
                color=theme.MUTED,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(height=20),
            ft.Divider(height=1, thickness=1, color=_HAIRLINE),
            *_divided(
                update_row,
                _menu_row(
                    "反馈", "在 GitHub 提交问题或建议",
                    ft.Icons.FEEDBACK_OUTLINED, open_feedback,
                ),
            ),
        ],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        scroll=ft.ScrollMode.AUTO,
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
                ft.Icon(icon, color=theme.PRIMARY, size=20),
                ft.Column(
                    [
                        ft.Text(title, size=15),
                        ft.Text(subtitle, size=12, color=theme.MUTED),
                    ],
                    spacing=3,
                    expand=True,
                ),
                ft.Icon(
                    ft.Icons.CHEVRON_RIGHT, color=theme.MUTED, size=20,
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
    # Swappable slot: menu vs. whichever sub-page is open, so this tab stays
    # embedded in content_area (nav_rail visible) instead of pushing a
    # separate ft.View that would cover the whole window — see module
    # docstring.
    content = ft.Column(expand=True)

    def show_menu() -> None:
        content.controls.clear()
        content.controls.append(menu)
        page.update()

    # Typed as the Container event rather than the looser ft.ControlEvent so
    # the handlers match Container.on_click exactly and need no type: ignore.
    def open_mail(_: ft.Event[ft.Container]) -> None:
        content.controls.clear()
        content.controls.append(_build_mail_view(page, state, show_menu))
        page.update()

    def open_grader(_: ft.Event[ft.Container]) -> None:
        content.controls.clear()
        content.controls.append(_build_grader_view(page, state, show_menu))
        page.update()

    def open_about(_: ft.Event[ft.Container]) -> None:
        content.controls.clear()
        content.controls.append(_build_about_view(page, state, show_menu))
        page.update()

    menu = ft.Column(
        [
            ft.Text(
                "设置", size=24,
                weight=ft.FontWeight.BOLD,
            ),
            # ft.Text(
            #     "邮件与批改 API 凭证，保存到本地 ~/.cie_helper/.env",
            #     size=13, color=theme.MUTED,
            # ),
            ft.Container(height=10),
            *_divided(
                _menu_row(
                    "SMTP / GoodNotes", "邮件发送与 GoodNotes 导入地址",
                    ft.Icons.MAIL_OUTLINE, open_mail,
                ),
                _menu_row(
                    "Grader API 设置", "批改用的多模态模型凭证",
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
    content.controls.append(menu)

    # 20 on all four sides, same as every other tab — horizontal used to be
    # 24, which pushed this page's title 4px right of the others'. No
    # explicit bgcolor: this Container (and every sub-page's) inherits
    # content_area's — i.e. page.bgcolor — same as the rest of the app,
    # instead of whatever default a pushed ft.View used to render with.
    return ft.Container(content, padding=20)