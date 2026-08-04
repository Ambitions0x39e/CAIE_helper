"""「按考季查询」子页：查一个考季的全部卷子，分列勾选、批量下载。"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import flet as ft
from pydantic import ValidationError

from app_flet import theme
from app_flet.components.widgets import error_banner
from app_flet.tabs.download.session_picker import build_session_picker
from core.config_store import ConfigStore
from modules.downloader import (
    DownloadRequest,
    PaperDownloader,
    QueryEntry,
    QueryResult,
    QuerySeason,
    query_available,
)

if TYPE_CHECKING:
    from app_flet.state import AppState


# 子行缩进：让分支图标挂在 QP 名字左下角
_TREE_INDENT = 34
_LEAF_ICON_SIZE = 14
# 行高写死，把 Material 勾选框那圈 48px 点击热区留下的空档压掉，
# 让 MS 子行贴到它的 QP 底下（配合 Checkbox 的 COMPACT 密度）。
# 再往下压就会开始切字：14pt 的行盒约 19px，13pt 约 17px。
_ROW_H = 24
_LEAF_ROW_H = 16
# 标签页内容区高度 = 窗口高 - 它上面那些东西的高度。
# 不能用 expand：外层 content_area 是 scroll=AUTO 的 Column，滚动容器里高度无界，
# expand 撑不出约束，TabBarView 会按内在高度铺开 —— 那正是页面底下拖出一大截空白的原因。
# 高度是算出来的，就必须跟着窗口走，见 build_download_tab 里的 on_resize。
#
# 拆成具名的几项而不是一个数：这个常量原本写死 210，其中 80 是**底部导航栏**。
# 导航改到左边一列之后底部不再占垂直空间，那 80 就变成了页面底下一条白边，
# 而一个光秃秃的 210 看不出哪一项该减。以后再动页头/标题就改对应那一项。
#: 页头 Container：上下 padding 各 12 + Material 按钮 40。
# ── 查询结果分列的表头 ────────────────────────────────────────────
# 表头原本是一行自由折行的 Text。卷子名长短不一（"Mechanics" 一行、
# "Probability & Statistics 1" 两行），折行数不同，下面的内容就从不同高度
# 开始，列与列参差不齐。所以表头改成**定高**：同一次渲染里所有列用同一个
# 行数，内容一定从同一条基线开始。
_COL_SPACING = 16
#: 13pt 行盒约 17px（见 _ROW_H 那条注释），留 1px 余量。
_COL_HEADER_LINE_H = 18
#: 挂了卷子名就给两行；窄到只剩「Paper X」时一行。
_COL_HEADER_LINES = 2
#: 列宽窄于此就只显示「Paper X」——名字挤成三四行反而更难看。
#: 想让卷子名更早/更晚出现，调这一个数就够。
_COL_DESC_MIN_W = 150
#: 结果区可用宽度 = 窗口宽 - 左侧导航列 84 - 分隔线 1 - 本页左右 padding 40。
_RESULT_CHROME_W = 125
_FALLBACK_PAGE_W = 1024


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
    on_resize_hooks: list[Callable[[], bool]] | None = None,
) -> ft.Container:
    def _fits_desc(n_cols: int) -> bool:
        """Is each of *n_cols* columns wide enough to carry the paper's name?"""
        if n_cols <= 0:
            return True
        avail = int(page.width or _FALLBACK_PAGE_W) - _RESULT_CHROME_W
        per_col = (avail - _COL_SPACING * (n_cols - 1)) / n_cols
        return per_col >= _COL_DESC_MIN_W

    syllabi = sorted(ConfigStore().load_all(), key=lambda s: s.syllabus_id)
    # 三个下拉框和「分数线」子页共用，见 session_picker.py。
    picker = build_session_picker()
    paper_type_dd, year_dd, season_dd = (
        picker.syllabus, picker.year, picker.season,
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
    # 最近一次查询结果 + 它渲染时用的表头模式。留着是为了窗口变宽/变窄时能
    # 就地重排，不必重新发一次网络查询。
    last_result: list[QueryResult | None] = [None]
    rendered_desc: list[bool | None] = [None]

    def _row_note(entry: QueryEntry) -> str:
        """右侧灰字：这行的状态。已下载不再单独打标，只在批量摘要里计跳过数。"""
        if entry.kind == "gt":
            return "分数线"
        if entry.kind == "other":
            return "暂不支持"
        return ""

    def _leaf(text: str, *, color: str = theme.MUTED) -> ft.Row:
        """树的子行：子项图标 + 灰字，缩进到勾选框右边，不占选择列。

        分支符号用 Material 图标
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

        last_result[0] = result
        _render_result(result)

    def _render_result(result: QueryResult) -> None:
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

        # 一次渲染只定一个表头行数，所有列共用 —— 逐列各算各的会重新引入
        # 高低不齐（比如某一列没配卷子名就只有一行）。
        show_desc = _fits_desc(len(groups))
        header_lines = _COL_HEADER_LINES if show_desc else 1
        rendered_desc[0] = show_desc

        columns: list[ft.Control] = []
        for digit in sorted(groups):
            named = type_names.get(digit) if show_desc else None
            col: list[ft.Control] = [
                ft.Container(
                    ft.Text(
                        f"Paper {digit}" + (f" · {named}" if named else ""),
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        max_lines=header_lines,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    height=header_lines * _COL_HEADER_LINE_H,
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
                    spacing=_COL_SPACING,
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

    def _reflow_on_resize() -> bool:
        """Re-lay the result columns when the window crosses the width cutoff.

        Returns whether anything was rebuilt, so the caller can skip a
        page.update() entirely on the (overwhelmingly common) resize events
        that change nothing.
        """
        result = last_result[0]
        if result is None:
            return False
        n_cols = len({
            _paper_digit(e.paper_id) for e in result.entries if e.kind == "qp"
        })
        if _fits_desc(n_cols) == rendered_desc[0]:
            return False

        # Re-rendering builds fresh Checkboxes, so carry the ticks across —
        # losing a careful selection to a window resize would be maddening.
        ticked = {e.paper_id for cb, _, e in rows if cb.value}
        rows.clear()
        result_list.controls.clear()
        _render_result(result)
        for cb, _, entry in rows:
            cb.value = entry.paper_id in ticked
        _refresh_status()
        return True

    if on_resize_hooks is not None:
        on_resize_hooks.append(_reflow_on_resize)

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
                picker.row(),
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
