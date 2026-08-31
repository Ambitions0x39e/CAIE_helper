"""Settings tab — entry list that drills down into sub-pages.

Settings-app-style menu: tapping "SMTP / GoodNotes", "Grader API" or "关于"
swaps the tab's own content for the sub-page, with a back arrow + title row
(``_sub_header``) standing in for a real AppBar. A pushed ``ft.View`` would
give a native slide-in transition and AppBar back button, but it replaces the
*entire* window, taking the left-hand nav_rail and header from main.py down
with it. Embedding keeps the tab inside ``content_area`` like every other tab;
the slide-in is hand-rolled (``swap_slot``).

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
from app_flet.components.widgets import hoverable, push_track, section_title
from core.settings import GraderConfig, MailConfig
from modules.marking.syllabus_parser import (
    delete_syllabus,
    stored_syllabuses,
    syllabus_path,
)

if TYPE_CHECKING:
    from app_flet.state import AppState
    from modules.marking.syllabus_parser import SyllabusInfo

#: Drill-down rows' corner radius. Also the inset their dividers need, so the
#: two can't drift apart.
_MENU_ROW_RADIUS = 8

#: 抽屉的两格：菜单在左、子页在右。序号就是它们在轨道上的先后，推拉的方向
#: 由它决定。
_MENU_PANE = 0
_SUB_PANE = 1

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
# them being squeezed to nothing, so the row stacks instead. A desktop window
# can be dragged this narrow, so the side-by-side form is a wide-window
# affordance, not the only layout.
_NARROW_WIDTH = 560


def _is_narrow(page: ft.Page) -> bool:
    return (page.width or 1024) - theme.NAV_CHROME_W < _NARROW_WIDTH


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
            title, size=theme.SECTION, weight=ft.FontWeight.BOLD,
            style=theme.section_style(),
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
        left.append(ft.Text(
            description,
            size=theme.CAPTION,
            color=theme.MUTED,
            style=theme.caption_style(),
        ))

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


def _divided(*rows: ft.Control, indent: float = 0) -> list[ft.Control]:
    """Interleave hairlines between rows — never leading or trailing.

    ``indent`` pulls both ends of the line in, for rows that paint a rounded
    background on hover: the block's corners curve inward over the radius, so
    a line running the full width overshoots the thing it is dividing at
    exactly the height where the two meet. Pass the row's corner radius.
    """
    out: list[ft.Control] = []
    for i, row in enumerate(rows):
        if i:
            out.append(_hairline(indent))
        out.append(row)
    return out


def _hairline(indent: float = 0) -> ft.Divider:
    return ft.Divider(
        height=1,
        thickness=1,
        color=_HAIRLINE,
        leading_indent=indent,
        trailing_indent=indent,
    )


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
    """Stands in for a native AppBar: back arrow + bold title, same visual
    weight."""
    return ft.Row(
        [
            ft.IconButton(ft.CupertinoIcons.BACK, on_click=lambda e: on_back()),
            ft.Text(
                title, size=20, weight=ft.FontWeight.BOLD,
                style=theme.title_style(),
            ),
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
                    icon=ft.CupertinoIcons.FLOPPY_DISK,
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
        saved_grader.model if saved_grader else "qwen3.6-flash",
        hint="qwen3.6-flash",
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
                model=grader_model.value or "qwen3.6-flash",
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
                    icon=ft.CupertinoIcons.FLOPPY_DISK,
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
            ft.Icon(ft.CupertinoIcons.BOOK_FILL, size=48, color=theme.ON_FILLED),
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
        row = update_row.content
        if not isinstance(row, ft.Container):
            return
        body = row.content
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

        Nothing can replace an app that is still running — Inno Setup cannot
        overwrite our own .exe while this process holds it open, and swapping
        a live .app bundle on macOS is no safer. So exiting is not optional,
        and os._exit is deliberate: a clean shutdown could be blocked by a
        pending UI task and leave the files held with the installer already
        running.
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
                    ft.Markdown(
                        result.release_notes or "（本次发布没有填写更新说明）",
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        selectable=True,
                        md_style_sheet=ft.MarkdownStyleSheet(
                            p_text_style=ft.TextStyle(size=13),
                        ),
                    ),
                    ft.Text(
                        "下载完成后会自动安装。安装时应用会自动退出，"
                        "装好后会自己重新打开。",
                        size=theme.CAPTION,
                        color=theme.MUTED,
                        style=theme.caption_style(),
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
        # Platforms with no installer we know how to run (Linux, …) get the
        # releases page in a browser — never an error, never a crash.
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
        ft.CupertinoIcons.CLOUD_DOWNLOAD, on_update,
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
                style=theme.title_style(),
            ),
            ft.Text(
                f"Version {version}" if version else "",
                size=theme.BODY,
                color=theme.MUTED,
                text_align=ft.TextAlign.CENTER,
                style=theme.numeric_style(),
            ),
            ft.Container(height=20),
            _hairline(_MENU_ROW_RADIUS),
            *_divided(
                update_row,
                _menu_row(
                    "反馈", "在 GitHub 提交问题或建议",
                    ft.CupertinoIcons.CHAT_BUBBLE_TEXT, open_feedback,
                ),
                indent=_MENU_ROW_RADIUS,
            ),
        ],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        scroll=ft.ScrollMode.AUTO,
    )


# --------------------------------------------------------------------------
# Menu row helper + entry point (this is what gets embedded as the "设置" tab)
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Sub-page: 大纲 Topic 库
# --------------------------------------------------------------------------

def _compact_ids(ids: list[str]) -> str:
    """``1..22`` → ``"1–22"``, ``1,2,5,6,7`` → ``"1–2, 5–7"``.

    A science paper covers 22 or 37 topics; spelling every id out overflows
    the row and buries the one thing worth reading, which is the range.
    Non-numeric ids (the math family's ``N.M``) are left alone — those lists
    are short and a range over them would be a lie.
    """
    if not ids:
        return "（空）"
    if not all(i.isdigit() for i in ids):
        return ", ".join(ids)
    nums = sorted(int(i) for i in ids)
    runs: list[tuple[int, int]] = []
    start = previous = nums[0]
    for num in nums[1:]:
        if num == previous + 1:
            previous = num
            continue
        runs.append((start, previous))
        start = previous = num
    runs.append((start, previous))
    return ", ".join(
        str(lo) if lo == hi else f"{lo}–{hi}" for lo, hi in runs
    )


def _stacked(label: str, body: ft.Control) -> ft.Control:
    """Label above, content below, both full width.

    Not ``_row``: that puts the control hard right of the label on one line,
    which is right for a switch or a short value and wrong for a block. Given
    a block it squeezes the label column to nothing — literally one glyph per
    line — and lets the content run off the right edge.
    """
    return ft.Container(
        ft.Column([ft.Text(label, size=15), body], spacing=8),
        padding=ft.Padding.symmetric(vertical=12),
    )


def _syllabus_body(
    page: ft.Page, info: SyllabusInfo, on_changed: Callable[[], None],
) -> list[ft.Control]:
    """One stored syllabus: where it lives, what it maps, every topic."""
    del page  # the caller owns the refresh
    mapping = ft.Column(
        [
            ft.Text(
                f"Paper {paper} → {_compact_ids(ids)}",
                size=13, selectable=True, expand=True,
            )
            for paper, ids in sorted(info.component_topics.items())
        ] or [ft.Text("（没有 component 映射）", size=13, color=theme.MUTED)],
        spacing=4,
    )
    topics = ft.Column(
        [
            ft.Text(
                f"{topic.topic_id}  {topic.name}"
                + (f"   [{topic.category}]" if topic.category else ""),
                size=theme.CAPTION, color=theme.MUTED, selectable=True,
                expand=True, style=theme.caption_style(),
            )
            for topic in info.topics.values()
        ],
        spacing=2,
    )

    def _forget(_: ft.Event[ft.Button]) -> None:
        delete_syllabus(info.subject_id)
        on_changed()

    return [
        _section(f"{info.subject_id}"),
        *_divided(
            _stacked(
                "存储位置",
                ft.Text(
                    str(syllabus_path(info.subject_id)),
                    size=theme.CAPTION, color=theme.MUTED, selectable=True,
                    style=theme.caption_style(),
                ),
            ),
            _row(
                "规模",
                ft.Text(
                    f"{len(info.topics)} topic · "
                    f"{len(info.component_topics)} component",
                    size=13,
                ),
            ),
            _stacked("Paper → topic", mapping),
            _stacked("Topic 全表", topics),
        ),
        _actions(ft.Button(
            "删除并重新解析",
            icon=ft.CupertinoIcons.TRASH,
            on_click=_forget,
            style=theme.filled_button(theme.DANGER),
            tooltip="删掉这份记录，下次在批改页重新上传大纲 PDF 时会重新解析",
        )),
    ]


def _build_syllabus_view(
    page: ft.Page, state: AppState, on_back: Callable[[], None],
) -> ft.Control:
    """Read-only dump of every parsed syllabus — the debug surface for it.

    The parse runs once per subject and its result then silently steers every
    graded question's topic tag, so there has to be somewhere to look at what
    it actually produced.
    """
    del state  # every sub-page takes it; this one reads only the store
    body = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    def _render() -> None:
        body.controls.clear()
        stored = stored_syllabuses()
        if not stored:
            body.controls.append(ft.Text(
                "还没有解析过任何大纲。在「批改」页选好科目后上传大纲 PDF，"
                "解析结果会存到 ~/.cie_helper/syllabus/ 并在这里列出。",
                size=13, color=theme.MUTED,
            ))
        for info in stored:
            body.controls.extend(_syllabus_body(page, info, _render))
        page.update()

    _render()
    return ft.Column(
        [_sub_header("大纲 Topic 库", on_back), body],
        expand=True,
    )


def _menu_row(
    title: str,
    subtitle: str,
    icon: ft.IconData,
    on_click: Callable[[ft.Event[ft.Container]], None],
) -> ft.GestureDetector:
    """A drill-down row: same left/right rhythm as _row, chevron on the right."""
    # The chevron is what promises "this goes somewhere", so it is the part
    # that brightens on hover. The title is already at full strength and the
    # subtitle reading as loud as the title would flatten the pair.
    chevron = ft.Icon(ft.CupertinoIcons.CHEVRON_RIGHT, color=theme.MUTED, size=20)
    row = ft.Container(
        ft.Row(
            [
                ft.Icon(icon, color=theme.PRIMARY, size=20),
                ft.Column(
                    [
                        ft.Text(title, size=15),
                        ft.Text(
                            subtitle,
                            size=theme.CAPTION,
                            color=theme.MUTED,
                            style=theme.caption_style(),
                        ),
                    ],
                    spacing=3,
                    expand=True,
                ),
                chevron,
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(vertical=12, horizontal=8),
        border_radius=_MENU_ROW_RADIUS,
        animate=ft.Animation(theme.DURATION_INSTANT, theme.CURVE_IN),
        on_click=on_click,
    )
    return hoverable(row, tinted=[chevron])


def build_settings_tab(page: ft.Page, state: AppState) -> ft.Container:
    # Swappable slot: menu vs. whichever sub-page is open, so this tab stays
    # embedded in content_area (nav_rail visible) instead of pushing a
    # separate ft.View that would cover the whole window — see module
    # docstring.
    # 菜单是第 0 格、子页是第 1 格 —— _menu_row 右边那个 CHEVRON_RIGHT 承诺
    # 的就是「往右进去」，进去时菜单往左出、子页从右边推进来，两页同向。
    def show_menu() -> None:
        show(_MENU_PANE, menu)

    # Typed as the Container event rather than the looser ft.ControlEvent so
    # the handlers match Container.on_click exactly and need no type: ignore.
    def open_mail(_: ft.Event[ft.Container]) -> None:
        show(_SUB_PANE, _build_mail_view(page, state, show_menu))

    def open_grader(_: ft.Event[ft.Container]) -> None:
        show(_SUB_PANE, _build_grader_view(page, state, show_menu))

    def open_syllabus(_: ft.Event[ft.Container]) -> None:
        show(_SUB_PANE, _build_syllabus_view(page, state, show_menu))

    def open_about(_: ft.Event[ft.Container]) -> None:
        show(_SUB_PANE, _build_about_view(page, state, show_menu))

    menu = ft.Column(
        [
            section_title("设置"),
            ft.Container(height=10),
            *_divided(
                _menu_row(
                    "SMTP / GoodNotes", "邮件发送与 GoodNotes 导入地址",
                    ft.CupertinoIcons.MAIL, open_mail,
                ),
                _menu_row(
                    "Grader API 设置", "批改用的多模态模型凭证",
                    ft.CupertinoIcons.WAND_STARS, open_grader,
                ),
                _menu_row(
                    "大纲 Topic 库", "已解析的大纲：topic 列表与 paper 映射",
                    ft.CupertinoIcons.BOOK, open_syllabus,
                ),
                _menu_row(
                    "关于", "版本信息与反馈",
                    ft.CupertinoIcons.INFO_CIRCLE, open_about,
                ),
                indent=_MENU_ROW_RADIUS,
            ),
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )
    # 20 on all four sides, same as every other tab, so this page's title
    # lines up with the others'. It goes *inside* the track (hence via
    # push_track) rather than around it: wrapped around, the clip edge
    # retreats to the inside of the margin and a sliding sub-page would appear
    # and vanish 20px short of the nav rail, with a dead white strip between.
    # No explicit bgcolor: this Container (and every sub-page's) inherits
    # content_area's — i.e. page.bgcolor — same as the rest of the app.
    #
    # fill 留默认的 False：这个 tab 挂在 content_area 那根滚动列里，高度无界。
    body, show = push_track(page, 2, menu, padding=theme.SPACE_XL)
    return body