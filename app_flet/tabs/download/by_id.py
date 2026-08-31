"""「按 ID 下载」子页：输入 paper_id 直接下载，可选发去 GoodNotes。"""
from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft
from pydantic import ValidationError

from app_flet import theme
from app_flet.components.widgets import (
    error_banner,
    segmented_strip,
    success_banner,
    swap_slot,
)
from modules.downloader import (
    DownloadRequest,
    DownloadSource,
    PaperDownloader,
)
from modules.mailer import GoodNotesMailer, MailRequest

if TYPE_CHECKING:
    from app_flet.state import AppState

#: 两个下载源在分段条上的先后。分段条只报序号，值查这张表。
_SOURCES: tuple[DownloadSource, ...] = ("CIEFrank", "PapaCambridge")


def build_by_id_tab(
    page: ft.Page,
    state: AppState,
    show_snack: object,
) -> ft.Container:

    paper_id_field = ft.TextField(
        label="Paper ID",
        label_style=theme.field_label_style(),
        hint_text="9702_s23_qp_11",
        helper="格式: <科目>_<考期>_qp_<试卷>",
        expand=True,
    )

    #: 当前选中的下载源 —— 分段条自己管选中态，只把序号报出来。
    source = [_SOURCES[0]]

    def _on_source(index: int) -> None:
        source[0] = _SOURCES[index]

    source_selector = segmented_strip(list(_SOURCES), _on_source)

    # 结果区三态（空 / 成功 / 失败）走换槽位：空态就是一个空 Column。
    # 单个结果没什么形状可预告，等待仍旧交给进度圈。
    result_area, show_result = swap_slot(page, ft.Column(), theme.DURATION_FAST)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
    gn_section = ft.Column(visible=False)
    #: 挡住下载没完时的重复点击 —— 后台线程和一次新点击都会改结果区 /
    #: state.last_downloaded_id，没锁的话两次下载会踩到同一份状态。
    busy = [False]

    def _refresh_gn_section() -> None:
        gn_section.controls.clear()
        if state.last_downloaded_id and state.mail_config:
            gn_section.controls.append(ft.Divider())
            gn_section.controls.append(
                ft.Row([
                    ft.Text(
                        f"准备发送: {state.last_downloaded_id}",
                        size=theme.CAPTION,
                        color=theme.MUTED,
                        expand=True,
                        style=theme.caption_style(),
                    ),
                    ft.Button(
                        "发送到 GoodNotes",
                        icon=ft.CupertinoIcons.PAPERPLANE,
                        on_click=on_send_gn,  # type: ignore[arg-type]
                        style=theme.filled_button(theme.ACCENT),
                    ),
                ])
            )
            gn_section.visible = True
        else:
            gn_section.visible = False

    def on_download(_: ft.ControlEvent) -> None:
        if busy[0]:
            show_snack("上一次下载还没完成，请稍候")  # type: ignore[operator]
            return
        pid = paper_id_field.value or ""
        if not pid.strip():
            show_snack("请输入 Paper ID")  # type: ignore[operator]
            return

        try:
            request = DownloadRequest(paper_id=pid.strip(), source=source[0])
        except ValidationError as exc:
            msgs = "; ".join(
                e["msg"].removeprefix("Value error, ") for e in exc.errors()
            )
            show_snack(f"验证失败: {msgs}", theme.DANGER)  # type: ignore[operator]
            return

        busy[0] = True
        progress_ring.visible = True
        show_result(ft.Column())

        def _work() -> None:
            try:
                downloader = PaperDownloader(store=state.store)
                dl = downloader.download(request)

                progress_ring.visible = False

                if dl.success:
                    show_result(success_banner(
                        f"已下载: {dl.paper_id}",
                        [f"QP → {dl.qp_path}", f"MS → {dl.ms_path}"],
                    ))
                    state.last_downloaded_id = dl.paper_id
                    state.last_downloaded_qp = dl.qp_path
                else:
                    show_result(error_banner(f"下载失败: {dl.error}"))

                _refresh_gn_section()
                page.update()
            finally:
                busy[0] = False

        page.run_thread(_work)

    def on_record(_: ft.ControlEvent) -> None:
        pid = paper_id_field.value or ""
        if not pid.strip():
            show_snack("请输入 Paper ID")  # type: ignore[operator]
            return

        downloader = PaperDownloader(store=state.store)
        dl = downloader.record_only(pid.strip())

        if dl.success:
            show_result(success_banner(f"已记录 (无PDF): {dl.paper_id}"))
        else:
            show_result(error_banner(f"记录失败: {dl.error}"))

    def on_send_gn(_: ft.ControlEvent) -> None:
        if not state.last_downloaded_id or not state.mail_config:
            return

        try:
            mail_req = MailRequest(
                paper_id=state.last_downloaded_id,
                qp_path=state.last_downloaded_qp or "",
            )
        except ValidationError as exc:
            show_snack(  # type: ignore[operator]
                f"验证失败: {exc.errors()[0]['msg']}",
                theme.DANGER,
            )
            return

        mailer = GoodNotesMailer(config=state.mail_config, store=state.store)
        mail_result = mailer.send(mail_req)

        if mail_result.success:
            show_snack(  # type: ignore[operator]
                f"✅ 已发送到 {mail_result.recipient}",
                theme.SUCCESS,
            )
            state.last_downloaded_id = None
            state.last_downloaded_qp = None
            _refresh_gn_section()
            page.update()
        else:
            show_snack(  # type: ignore[operator]
                f"发送失败: {mail_result.error}",
                theme.DANGER,
            )

    download_btn = ft.Button(
        "下载",
        icon=ft.CupertinoIcons.TRAY_ARROW_DOWN,
        on_click=on_download,  # type: ignore[arg-type]
        style=theme.filled_button(),
    )

    record_btn = ft.Button(
        "仅记录",
        icon=ft.CupertinoIcons.TEXT_BADGE_PLUS,
        on_click=on_record,  # type: ignore[arg-type]
        style=theme.filled_button(theme.NEUTRAL),
    )

    return ft.Container(
        ft.Column(
            [
                ft.Row([
                    ft.Container(
                        ft.Column(
                            [
                                ft.Row([paper_id_field], spacing=12),
                                ft.Row(
                                    [
                                        ft.Text("来源:", size=14),
                                        source_selector,
                                    ],
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Row(
                                    [download_btn, record_btn, progress_ring],
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=theme.SPACE_MD,
                        ),
                        expand=True,
                        padding=theme.SPACE_MD,
                        bgcolor=theme.SURFACE,
                        border_radius=theme.CARD_RADIUS,
                        border=ft.Border.all(1, theme.HAIRLINE),
                        shadow=theme.card_shadow(),
                    )
                ]),
                result_area,
                gn_section,
            ],
            spacing=4,
        ),
        # top 比左右小一档：分段条选的就是下面显示谁，两者贴紧才读得出
        # 这层从属关系。管理页和批改页的推拉轨道用的是同一组数，三个 tab 的
        # 内容起点因此落在同一条水平线上。
        padding=ft.Padding(
            left=theme.SPACE_XL, right=theme.SPACE_XL,
            top=theme.SPACE_MD, bottom=theme.SPACE_XL,
        ),
    )
