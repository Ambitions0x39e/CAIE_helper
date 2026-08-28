"""「分数线」子页：下载 grade threshold PDF，解析分数线，并按 option 批量取卷。

解析走 :mod:`core.gt_parser`，它是纯 pdfminer 的，可以直接 import —— 不像
早期版本要为 pdfplumber 做可选依赖的降级处理。

GT 表里的 component 只有两位（``11``、``24``），单看没法下载；这里补成完整
卷号 ``<科目>_<考期>_qp_<component>``，勾选一个 option 就等于选中它那一整套卷，
底下一条批量下载栏，路径与「按考季查询」完全一致。

勾选用 ``DataTable`` 自带的 ``show_checkbox_column``，不是自己塞 Checkbox：
分数线本来就是张表，逐行比较各等第才是它的用法。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft
from pydantic import ValidationError

from app_flet import theme
from app_flet.components.widgets import (
    data_table,
    error_banner,
    success_banner,
)
from app_flet.tabs.download.session_picker import build_session_picker
from core.gt_parser import GTParser
from modules.downloader import DownloadRequest, PaperDownloader

if TYPE_CHECKING:
    from app_flet.state import AppState
    from core.gt_parser import GradeThreshold, GTDocument

def build_by_gt_tab(
    page: ft.Page, state: AppState, show_snack: object,
) -> ft.Container:
    # 和「按考季查询」同一套下拉框：选的本来就是同一件事（哪科哪一场），
    # 而且卷号由代码拼，用户不会再把 _gt 的格式打错。
    picker = build_session_picker()
    result_area = ft.Column(visible=False, spacing=8)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
    status_text = ft.Text("", size=12, color=theme.MUTED)
    error_area = ft.Column(visible=False, spacing=4)

    # (表格行, 这个 option 要下的完整卷号)
    rows: list[tuple[ft.DataRow, list[str]]] = []
    # 查询分数线和批量下载共用一把锁：两边都会改 rows / result_area /
    # error_area，没锁的话双击或者一个没完就点另一个会撞车。
    busy = [False]

    def _selected_papers() -> list[str]:
        """勾中的所有卷号，去重后保持出现顺序 —— 多个 option 常共用同一份卷。"""
        seen: dict[str, None] = {}
        for row, papers in rows:
            if row.selected:
                seen.update(dict.fromkeys(papers))
        return list(seen)

    def _refresh_status() -> None:
        picked = sum(1 for r, _ in rows if r.selected)
        papers = _selected_papers()
        status_text.color = theme.MUTED
        status_text.value = (
            f"共 {len(rows)} 个 option · 已勾选 {picked}"
            + (f"，合计 {len(papers)} 份卷子（已去重）" if papers else "")
        )

    def _set_all(value: bool) -> None:
        for row, _ in rows:
            row.selected = value
        _refresh_status()
        page.update()

    def on_batch_download(_: ft.ControlEvent) -> None:
        if busy[0]:
            show_snack("上一次请求还没完成，请稍候")  # type: ignore[operator]
            return
        papers = _selected_papers()
        if not papers:
            show_snack("请先勾选要下载的 option")  # type: ignore[operator]
            return

        busy[0] = True
        progress_ring.visible = True
        error_area.controls.clear()
        error_area.visible = False
        page.update()

        def _work() -> None:
            try:
                # 走和「按考季查询」「按 ID 下载」同一条下载路径，不另开逻辑。
                downloader = PaperDownloader(store=state.store)
                succeeded = failed = 0
                errors: list[str] = []

                for idx, paper_id in enumerate(papers, start=1):
                    status_text.color = theme.MUTED
                    status_text.value = (
                        f"下载中 {idx}/{len(papers)} — {paper_id}"
                    )
                    page.update()
                    try:
                        request = DownloadRequest(paper_id=paper_id)
                    except ValidationError as exc:
                        failed += 1
                        msgs = "; ".join(
                            e["msg"].removeprefix("Value error, ")
                            for e in exc.errors()
                        )
                        errors.append(f"{paper_id}: {msgs}")
                        continue

                    dl = downloader.download(request)
                    if dl.success:
                        succeeded += 1
                        state.last_downloaded_id = dl.paper_id
                        state.last_downloaded_qp = dl.qp_path
                    else:
                        failed += 1
                        errors.append(f"{paper_id}: {dl.error}")

                progress_ring.visible = False
                _set_all(False)
                if errors:
                    error_area.controls.extend(
                        error_banner(m) for m in errors[:5]
                    )
                    if len(errors) > 5:
                        error_area.controls.append(
                            error_banner(f"还有 {len(errors) - 5} 个错误未显示")
                        )
                    error_area.visible = True
                show_snack(  # type: ignore[operator]
                    f"完成: 成功 {succeeded}，失败 {failed}",
                    theme.SUCCESS if not failed else theme.WARNING,
                )
                page.update()
            finally:
                busy[0] = False

        page.run_thread(_work)

    batch_bar = ft.Row(
        [
            ft.Button(
                "批量下载",
                icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                on_click=on_batch_download,  # type: ignore[arg-type]
                style=theme.filled_button(),
            ),
            ft.TextButton("全选", on_click=lambda _: _set_all(True)),
            ft.TextButton("清空", on_click=lambda _: _set_all(False)),
        ],
        spacing=8,
        visible=False,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    def _on_row_select(
        row: ft.DataRow, e: ft.Event[ft.DataRow],
    ) -> None:
        row.selected = str(e.data).lower() == "true"
        _refresh_status()
        page.update()

    def _render_options(doc: GTDocument) -> list[ft.Control]:
        try:
            downloaded = {r.paper_id for r in state.store.load_all()}
        except ValueError:
            downloaded = set()

        # 普通字符串排序会把 "A" 排在 "A*" 前面（"A" 是 "A*" 的前缀，更短的先来）；
        # CIE 成绩里 A* 是最高档，惯例排在 A 前面。按去掉 "*" 的字母分组，同组内带
        # "*" 的排前面，其余字母（B/C/D/E/U…）本来字母序就是成绩从高到低，不用动。
        grades = sorted(
            {g for o in doc.options for g in o.thresholds},
            key=lambda g: (g.rstrip("*"), "*" not in g),
        )
        prefix = f"{doc.syllabus_id}_{doc.session}_qp_"

        data_rows: list[ft.DataRow] = []
        for opt in doc.options:
            papers = _papers_for(doc, opt)
            row = ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(opt.option)),
                    ft.DataCell(ft.Text(str(opt.max_weighted))),
                    *[
                        ft.DataCell(ft.Text(str(opt.thresholds.get(g, "–"))))
                        for g in grades
                    ],
                    # 每个 component 单独一段：本地已有的标绿，一眼看出这套卷
                    # 还差哪几份，不必再单开一列计数。
                    ft.DataCell(ft.Row(
                        [
                            ft.Text(
                                component,
                                color=(
                                    theme.SUCCESS if pid in downloaded
                                    else None
                                ),
                                weight=(
                                    ft.FontWeight.BOLD if pid in downloaded
                                    else None
                                ),
                                # 前缀每行都一样，写在表格上方一次即可；
                                # 完整卷号留在 tooltip 里，方便复制。
                                tooltip=pid + (
                                    "（本地已有）" if pid in downloaded else ""
                                ),
                            )
                            for component, pid in zip(
                                opt.components, papers, strict=True,
                            )
                        ],
                        spacing=6,
                        tight=True,
                    )),
                ],
            )
            row.on_select_change = lambda e, r=row: _on_row_select(r, e)
            data_rows.append(row)
            rows.append((row, papers))

        return [
            ft.Text(
                f"{doc.syllabus_id} · {doc.session} — 共 "
                f"{len(doc.options)} 个 option",
                weight=ft.FontWeight.BOLD,
            ),
            ft.Row([
                ft.Text(
                    f"卷号 = {prefix}<卷子列的号>，例如 {prefix}"
                    f"{doc.options[0].components[0]}。"
                    "勾选 option 即选中它的整套卷子；",
                    size=12, color=theme.MUTED,
                ),
                ft.Text(
                    "绿色",
                    size=12,
                    color=theme.SUCCESS,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text("＝本地已有。", size=12, color=theme.MUTED),
            ], spacing=0, wrap=True),
            data_table(
                columns=[
                    ft.DataColumn(label=ft.Text("Option")),
                    ft.DataColumn(label=ft.Text("满分")),
                    *[ft.DataColumn(label=ft.Text(g)) for g in grades],
                    ft.DataColumn(label=ft.Text("卷子")),
                ],
                rows=data_rows,
                show_checkbox_column=True,
                on_select_all=lambda e: _set_all(
                    str(e.data).lower() == "true"
                ),
            ),
        ]

    def on_download(_: ft.ControlEvent) -> None:
        if busy[0]:
            show_snack("上一次请求还没完成，请稍候")  # type: ignore[operator]
            return
        if not picker.is_complete():
            show_snack("请先选择完整的查询条件")  # type: ignore[operator]
            return
        pid = picker.gt_paper_id()

        try:
            request = DownloadRequest(paper_id=pid, source="CIEFrank")
        except ValidationError as exc:
            msgs = "; ".join(
                e["msg"].removeprefix("Value error, ") for e in exc.errors()
            )
            show_snack(f"验证失败: {msgs}", theme.DANGER)  # type: ignore[operator]
            return

        busy[0] = True
        progress_ring.visible = True
        result_area.visible = False
        batch_bar.visible = False
        error_area.visible = False
        rows.clear()
        page.update()

        def _work() -> None:
            try:
                dl = PaperDownloader(store=state.store).download(request)

                progress_ring.visible = False
                result_area.controls.clear()

                if not dl.success:
                    result_area.controls.append(
                        error_banner(f"下载失败: {dl.error}")
                    )
                    result_area.visible = True
                    page.update()
                    return

                result_area.controls.append(
                    success_banner(
                        f"已下载: {dl.paper_id}", [f"PDF → {dl.qp_path}"],
                    )
                )
                doc = _parse(dl.qp_path, pid)
                if isinstance(doc, str):
                    result_area.controls.append(error_banner(doc))
                else:
                    result_area.controls.extend(_render_options(doc))
                    batch_bar.visible = True
                    _refresh_status()

                result_area.visible = True
                page.update()
            finally:
                busy[0] = False

        page.run_thread(_work)

    # scroll + expand, unlike the sibling sub-tabs: those are short enough to
    # fit, but a thresholds list runs to dozens of options. Everything here
    # lives inside ft.Tabs(height=…), which clips rather than scrolls, so a
    # long list would simply lose its bottom rows.
    return ft.Container(
        ft.Column(
            [
                ft.Row([
                    ft.Container(
                        ft.Column(
                            [
                                # ft.Text(
                                #     "选择考季，下载并解析这一场的分数线。",
                                #     size=13, color=theme.MUTED,
                                # ),
                                picker.row(),
                                ft.Container(height=4),
                                ft.Row(
                                    [
                                        ft.Button(
                                            "查询分数线",
                                            icon=ft.Icons.DOWNLOAD,
                                            style=theme.filled_button(),
                                            on_click=on_download,  # type: ignore[arg-type]
                                        ),
                                        progress_ring,
                                    ],
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=12,
                        ),
                        expand=True,
                        padding=theme.SPACE_MD,
                        bgcolor=theme.SURFACE,
                        border_radius=theme.CARD_RADIUS,
                        border=ft.Border.all(1, theme.HAIRLINE),
                        shadow=theme.card_shadow(),
                    )
                ]),
                status_text,
                batch_bar,
                error_area,
                result_area,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        padding=theme.SPACE_XL // 2,
    )


def _papers_for(doc: GTDocument, opt: GradeThreshold) -> list[str]:
    """把两位 component 补成完整卷号：``9701`` + ``w25`` + ``14`` → 9701_w25_qp_14."""
    return [
        f"{doc.syllabus_id}_{doc.session}_qp_{component}"
        for component in opt.components
    ]


def _parse(pdf_path: str | None, paper_id: str) -> GTDocument | str:
    """解析分数线；失败时返回给用户看的错误文案而不是抛出去。"""
    if not pdf_path:
        return "下载结果里没有文件路径，无法解析。"
    try:
        return GTParser().parse(Path(pdf_path), _session_from_id(paper_id))
    except Exception as exc:  # noqa: BLE001 — 报给用户，不冒泡到 UI
        return f"分数线解析失败: {exc}"


def _session_from_id(paper_id: str) -> str:
    """``9231_s25_gt`` → ``s25``；取不到就交给 parser 自己判断。"""
    parts = paper_id.split("_")
    return parts[1] if len(parts) > 1 else ""
