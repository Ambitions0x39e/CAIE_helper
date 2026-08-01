from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, cast

import flet as ft
from pydantic import ValidationError

from app_flet import theme
from app_flet.components.widgets import error_banner, success_banner
from core.config_store import ConfigStore
from modules.downloader import (
    DownloadRequest,
    DownloadSource,
    PaperDownloader,
    QueryEntry,
    QuerySeason,
    query_available,
)
from modules.mailer import GoodNotesMailer, MailRequest

if TYPE_CHECKING:
    from app_flet.state import AppState

_SEASONS = [
    ("m", "March"),
    ("s", "Summer"),
    ("w", "Winter"),
]
_FIRST_YEAR = 2004
# 子行缩进：让分支图标挂在 QP 名字左下角
_TREE_INDENT = 34
_LEAF_ICON_SIZE = 14
# 行高写死，把 Material 勾选框那圈 48px 点击热区留下的空档压掉，
# 让 MS 子行贴到它的 QP 底下（配合 Checkbox 的 COMPACT 密度）。
# 再往下压就会开始切字：14pt 的行盒约 19px，13pt 约 17px。
_ROW_H = 24
_LEAF_ROW_H = 16
# 标签页内容区高度 = 窗口高 - (页头 64 + 页内标题 48 + 间距 8 + 底部导航 80)。
# 不能用 expand：外层 content_area 是 scroll=AUTO 的 Column，滚动容器里高度无界，
# expand 撑不出约束，TabBarView 会按内在高度铺开 —— 那正是页面底下拖出一大截空白的原因。
# 高度是算出来的，就必须跟着窗口走，见 build_download_tab 里的 on_resize。
_TAB_CHROME_H = 210
_TAB_MIN_H = 320
_FALLBACK_PAGE_H = 800


def _paper_digit(paper_id: str) -> str:
    """
    卷号 = variant 的倒数第二位数字：``_qp_12`` / ``_qp_13`` → "1"，``_qp_21`` → "2"。
    单位数 variant（``_qp_1``）就取那一位；取不到数字的归到 "?" 那一列。
    """
    variant = paper_id.rsplit("_", 1)[-1]
    if len(variant) >= 2 and variant[-2].isdigit():
        return variant[-2]
    if variant[:1].isdigit():
        return variant[0]
    return "?"


def build_request_tab(
    page: ft.Page,
    state: AppState,
    show_snack: object,
) -> ft.Container:
    syllabi = sorted(ConfigStore().load_all(), key=lambda s: s.syllabus_id)
    current_year = dt.date.today().year

    paper_type_dd = ft.Dropdown(
        label="科目",
        label_style=theme.field_label_style(),
        options=[
            ft.dropdown.Option(key=s.syllabus_id, text=f"{s.syllabus_id} — {s.name}")
            for s in syllabi
        ],
        value=syllabi[0].syllabus_id if syllabi else None,
        expand=True,
    )

    year_dd = ft.Dropdown(
        label="年份",
        label_style=theme.field_label_style(),
        options=[
            ft.dropdown.Option(key=str(y), text=str(y))
            for y in range(current_year, _FIRST_YEAR - 1, -1)
        ],
        value=str(current_year),
        expand=True,
    )

    season_dd = ft.Dropdown(
        label="考季",
        label_style=theme.field_label_style(),
        options=[
            ft.dropdown.Option(key=code, text=label)
            for code, label in _SEASONS
        ],
        value=_SEASONS[0][0],
        expand=True,
    )

    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
    status_text = ft.Text("", size=12, color=theme.MUTED)
    # 自己不滚也不 expand：由外层那个 scroll=AUTO 的列统一滚，
    # 免得短列表也占满整屏、长列表套两层滚动条。
    result_list = ft.Column(spacing=0, visible=False)
    error_area = ft.Column(visible=False, spacing=4)

    # (勾选框, 右侧状态文字, 条目) — 只装可勾选的行（qp / gt）
    rows: list[tuple[ft.Checkbox, ft.Text, QueryEntry]] = []
    total_files = [0]  # 这一次查询返回的文件总数，含挂在 qp 下面的 ms

    def _row_note(entry: QueryEntry) -> str:
        """右侧灰字：这行的状态。已下载不再单独打标，只在批量摘要里计跳过数。"""
        if entry.kind == "gt":
            return "分数线"
        if entry.kind == "other":
            return "暂不支持"
        return ""

    def _leaf(text: str, *, color: str = theme.MUTED) -> ft.Row:
        """树的子行：子项图标 + 灰字，缩进到勾选框右边，不占选择列。

        分支符号用 Material 图标而不是 ``╰─``：制表符（U+2570/U+2500）的
        East Asian Width 是 Ambiguous，在全局那套中文字体（main.py 的
        Microsoft YaHei）里按全角渲染，宽度和基线都跟旁边的半角文件名对不上，
        看着歪。图标是矢量的，跟字体无关。
        """
        return ft.Row(
            [
                ft.Container(width=_TREE_INDENT),
                ft.Icon(
                    ft.Icons.SUBDIRECTORY_ARROW_RIGHT,
                    size=_LEAF_ICON_SIZE,
                    color=color,
                ),
                ft.Text(text, size=13, color=color),
            ],
            spacing=4,
            height=_LEAF_ROW_H,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _selectable_row(entry: QueryEntry) -> ft.Row:
        """qp / gt：黑字 + 勾选框，右端灰字状态，整行铺满窗口宽度。"""
        checkbox = ft.Checkbox(
            label=entry.paper_id,
            label_style=ft.TextStyle(size=14),
            value=False,  # 默认全不选
            visual_density=ft.VisualDensity.COMPACT,
            splash_radius=_LEAF_ICON_SIZE,
            on_change=_on_check,  # type: ignore[arg-type]
        )
        note = ft.Text(_row_note(entry), size=12, color=theme.MUTED)
        rows.append((checkbox, note, entry))
        return ft.Row(
            [checkbox, ft.Container(expand=True), note],
            spacing=8,
            height=_ROW_H,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _plain_row(entry: QueryEntry) -> ft.Row:
        """ci / in / er 之类：列出来，但不给选择列。"""
        return ft.Row(
            [
                ft.Container(width=_TREE_INDENT),
                ft.Text(entry.paper_id, size=14, color=theme.MUTED),
                ft.Container(expand=True),
                ft.Text(_row_note(entry), size=12, color=theme.MUTED),
            ],
            spacing=8,
            height=_ROW_H,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _refresh_status() -> None:
        picked = sum(1 for cb, _, _ in rows if cb.value)
        skip = sum(1 for cb, _, e in rows if cb.value and e.already_downloaded)
        status_text.color = theme.MUTED
        status_text.value = (
            f"共 {total_files[0]} 个文件，{len(rows)} 份可下载 · 已勾选 {picked}"
            + (f"（其中 {skip} 个本地已有，会跳过）" if skip else "")
        )

    def _on_check(_: ft.ControlEvent) -> None:
        _refresh_status()
        page.update()

    def _set_all(value: bool) -> None:
        for cb, _, _ in rows:
            cb.value = value
        _refresh_status()
        page.update()

    def on_send_request(_: ft.ControlEvent) -> None:
        if not paper_type_dd.value or not year_dd.value or not season_dd.value:
            show_snack("请先选择完整的查询条件")  # type: ignore[operator]
            return

        progress_ring.visible = True
        result_list.visible = False
        batch_bar.visible = False
        error_area.visible = False
        status_text.color = theme.MUTED
        status_text.value = "查询中…"
        page.update()

        result = query_available(
            paper_type_dd.value,
            year_dd.value,
            cast(QuerySeason, season_dd.value),
            store=state.store,
        )

        progress_ring.visible = False
        rows.clear()
        result_list.controls.clear()
        error_area.controls.clear()
        error_area.visible = False

        if not result.success:
            status_text.color = theme.DANGER
            status_text.value = f"查询失败: {result.error}"
            page.update()
            return

        if not result.entries:
            status_text.color = theme.MUTED
            status_text.value = "这个考季没有查到任何文件"
            page.update()
            return

        total_files[0] = len(result.entries)
        available = {e.paper_id for e in result.entries}
        nested_ms: set[str] = set()

        # 按卷号（倒数第二位数字：_11/_12/_13 → 1，_21/_22 → 2）分列，
        # 一张卷子一列，横向铺满窗口。
        groups: dict[str, list[QueryEntry]] = {}
        for entry in result.entries:
            if entry.kind == "qp":
                groups.setdefault(_paper_digit(entry.paper_id), []).append(entry)

        selected_syllabus = next(
            (s for s in syllabi if s.syllabus_id == paper_type_dd.value), None
        )
        type_names = (
            selected_syllabus.paper_types_as_dict() if selected_syllabus else {}
        )

        columns: list[ft.Control] = []
        for digit in sorted(groups):
            named = type_names.get(digit)
            header = f"Paper {digit}" + (f" · {named}" if named else "")
            col: list[ft.Control] = [
                ft.Text(
                    header,
                    size=13,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Divider(height=9),
            ]
            # QP 打头、对应 MS 作 ╰─ 子行挂在下面；MS 不单独占行、不占选择列，
            # 因为 download() 本来就是 QP+MS 一起下。
            for entry in groups[digit]:
                ms_id = entry.paper_id.replace("_qp_", "_ms_")
                col.append(_selectable_row(entry))
                if ms_id in available:
                    nested_ms.add(ms_id)
                    col.append(_leaf(ms_id))
                else:
                    col.append(_leaf("（没有对应 MS）"))
            columns.append(ft.Column(col, spacing=0, expand=True))

        if columns:
            result_list.controls.append(
                ft.Row(
                    columns,
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

        # 剩下的：gt 可勾（无子行）；ci/in/er 之类列出但没有选择列；
        # 没配上 QP 的孤儿 MS 也照样列出来，不让它凭空消失。
        leftovers = [
            e for e in result.entries
            if e.kind != "qp" and e.paper_id not in nested_ms
        ]
        if leftovers:
            result_list.controls.append(ft.Divider())
            for entry in leftovers:
                if entry.kind == "gt":
                    result_list.controls.append(_selectable_row(entry))
                else:
                    result_list.controls.append(_plain_row(entry))

        result_list.visible = True
        batch_bar.visible = True
        _refresh_status()
        page.update()

    def on_batch_download(_: ft.ControlEvent) -> None:
        picked = [(cb, note, e) for cb, note, e in rows if cb.value]
        if not picked:
            show_snack("请先勾选要下载的文件")  # type: ignore[operator]
            return

        # 走和「按 ID 下载」完全同一条路径，不另开下载逻辑。
        downloader = PaperDownloader(store=state.store)
        succeeded = skipped = failed = 0
        errors: list[str] = []

        progress_ring.visible = True
        error_area.controls.clear()
        error_area.visible = False
        page.update()

        for idx, (checkbox, note, entry) in enumerate(picked, start=1):
            if entry.already_downloaded:
                skipped += 1
                checkbox.value = False
                continue

            status_text.color = theme.MUTED
            status_text.value = f"下载中 {idx}/{len(picked)} — {entry.paper_id}"
            page.update()

            try:
                request = DownloadRequest(paper_id=entry.paper_id)
            except ValidationError as exc:
                failed += 1
                msgs = "; ".join(
                    e["msg"].removeprefix("Value error, ") for e in exc.errors()
                )
                errors.append(f"{entry.paper_id}: {msgs}")
                continue

            dl = downloader.download(request)
            if dl.success:
                succeeded += 1
                entry.already_downloaded = True
                checkbox.value = False
                note.value = _row_note(entry)
                # 发 GoodNotes 只发 QP：gt 之类不排进待发送位。
                if entry.kind == "qp":
                    state.last_downloaded_id = dl.paper_id
                    state.last_downloaded_qp = dl.qp_path
            else:
                failed += 1
                errors.append(f"{entry.paper_id}: {dl.error}")

        progress_ring.visible = False
        _refresh_status()

        if errors:
            error_area.controls.extend(error_banner(msg) for msg in errors[:5])
            if len(errors) > 5:
                error_area.controls.append(
                    ft.Text(
                        f"…另有 {len(errors) - 5} 条失败",
                        size=12,
                        color=theme.DANGER,
                    )
                )
            error_area.visible = True

        page.update()
        show_snack(  # type: ignore[operator]
            f"成功 {succeeded} · 跳过 {skipped} · 失败 {failed}",
            theme.DANGER if failed else theme.SUCCESS,
        )

    send_btn = ft.Button(
        "查询",
        icon=ft.Icons.SEARCH,
        on_click=on_send_request,  # type: ignore[arg-type]
        style=theme.filled_button(),
    )

    batch_bar = ft.Row(
        [
            ft.Button(
                "批量下载",
                icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                on_click=on_batch_download,  # type: ignore[arg-type]
                style=theme.filled_button(),
            ),
            ft.TextButton("全选可下载", on_click=lambda _: _set_all(True)),
            ft.TextButton("清空", on_click=lambda _: _set_all(False)),
        ],
        spacing=8,
        visible=False,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    return ft.Container(
        ft.Column(
            [
                ft.Row(
                    [paper_type_dd, year_dd, season_dd],
                    spacing=12,
                ),
                ft.Container(height=12),
                ft.Row(
                    [send_btn, progress_ring],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=8),
                status_text,
                # 批量下载栏放列表上面：列表可能很长，按钮别被顶到看不见的地方。
                batch_bar,
                result_list,
                error_area,
            ],
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        padding=20,
    )


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

    source_selector = ft.SegmentedButton(
        segments=[
            ft.Segment(value="CIEFrank", label=ft.Text("CIEFrank")),
            ft.Segment(value="PapaCambridge", label=ft.Text("PapaCambridge")),
        ],
        selected=["CIEFrank"],
        allow_multiple_selection=False,
    )

    result_area = ft.Column(visible=False)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
    gn_section = ft.Column(visible=False)

    def _refresh_gn_section() -> None:
        gn_section.controls.clear()
        if state.last_downloaded_id and state.mail_config:
            gn_section.controls.append(ft.Divider())
            gn_section.controls.append(
                ft.Row([
                    ft.Text(
                        f"准备发送: {state.last_downloaded_id}",
                        size=12,
                        color=theme.MUTED,
                        expand=True,
                    ),
                    ft.Button(
                        "发送到 GoodNotes",
                        icon=ft.Icons.SEND,
                        on_click=on_send_gn,  # type: ignore[arg-type]
                        style=theme.filled_button(theme.ACCENT),
                    ),
                ])
            )
            gn_section.visible = True
        else:
            gn_section.visible = False

    def on_download(_: ft.ControlEvent) -> None:
        pid = paper_id_field.value or ""
        if not pid.strip():
            show_snack("请输入 Paper ID")  # type: ignore[operator]
            return

        src: DownloadSource = source_selector.selected[0]  # type: ignore[assignment]

        try:
            request = DownloadRequest(paper_id=pid.strip(), source=src)
        except ValidationError as exc:
            msgs = "; ".join(
                e["msg"].removeprefix("Value error, ") for e in exc.errors()
            )
            show_snack(f"验证失败: {msgs}", theme.DANGER)  # type: ignore[operator]
            return

        progress_ring.visible = True
        result_area.visible = False
        page.update()

        downloader = PaperDownloader(store=state.store)
        dl = downloader.download(request)

        progress_ring.visible = False
        result_area.controls.clear()

        if dl.success:
            result_area.controls.append(
                success_banner(
                    f"已下载: {dl.paper_id}",
                    [f"QP → {dl.qp_path}", f"MS → {dl.ms_path}"],
                )
            )
            state.last_downloaded_id = dl.paper_id
            state.last_downloaded_qp = dl.qp_path
        else:
            result_area.controls.append(error_banner(f"下载失败: {dl.error}"))

        result_area.visible = True
        _refresh_gn_section()
        page.update()

    def on_record(_: ft.ControlEvent) -> None:
        pid = paper_id_field.value or ""
        if not pid.strip():
            show_snack("请输入 Paper ID")  # type: ignore[operator]
            return

        downloader = PaperDownloader(store=state.store)
        dl = downloader.record_only(pid.strip())

        result_area.controls.clear()
        if dl.success:
            result_area.controls.append(
                success_banner(f"已记录 (无PDF): {dl.paper_id}")
            )
        else:
            result_area.controls.append(error_banner(f"记录失败: {dl.error}"))
        result_area.visible = True
        page.update()

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
        icon=ft.Icons.DOWNLOAD,
        on_click=on_download,  # type: ignore[arg-type]
        style=theme.filled_button(),
    )

    record_btn = ft.Button(
        "仅记录",
        icon=ft.Icons.NOTE_ADD,
        on_click=on_record,  # type: ignore[arg-type]
        style=theme.filled_button(theme.NEUTRAL),
    )

    return ft.Container(
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
                ft.Container(height=8),
                ft.Row(
                    [download_btn, record_btn, progress_ring],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=12),
                result_area,
                gn_section,
            ],
            spacing=4,
        ),
        padding=20,
    )


def build_download_tab(
    page: ft.Page,
    state: AppState,
    show_snack: object,
) -> ft.Container:
    # 见 _TAB_CHROME_H 注释：滚动父容器里必须给个确定高度，不能靠 expand。
    def _tab_height() -> int:
        return max(
            _TAB_MIN_H, int(page.height or _FALLBACK_PAGE_H) - _TAB_CHROME_H
        )

    tabs: ft.Tabs = ft.Tabs(
        length=2,
        selected_index=0,
        height=_tab_height(),
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="按考季查询"),
                        ft.Tab(label="按 ID 下载"),
                    ]
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        build_request_tab(page, state, show_snack),
                        build_by_id_tab(page, state, show_snack),
                    ],
                ),
            ],
        ),
    )

    # 高度是算出来的，就得跟着窗口走：不接 on_resize 的话，最大化之后标签页
    # 还停在开窗时那个高度，下面留一大块白。page.on_resize 全仓没别人用
    # （其它页都是建页时读 page.width 决定布局），这里独占。
    def _on_page_resize(_: ft.ControlEvent) -> None:
        tabs.height = _tab_height()
        page.update()

    page.on_resize = _on_page_resize  # type: ignore[assignment]

    return ft.Container(
        ft.Column(
            [
                ft.Container(
                    ft.Text(
                        "下载试卷",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                    ),
                    padding=ft.Padding(left=20, right=20, top=16, bottom=0),
                ),
                tabs,
            ],
            spacing=8,
        ),
        padding=0,
    )
