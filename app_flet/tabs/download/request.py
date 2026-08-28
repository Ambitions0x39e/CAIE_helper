"""「按考季查询」子页：查一个考季的全部卷子，分列勾选、批量下载。"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import flet as ft
from pydantic import ValidationError

from app_flet import theme
from app_flet.components.widgets import error_banner, warning_banner
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
# 行高写死，把 Material 勾选框那圈 48px 点击热区留下的空档压掉（配合 Checkbox
# 的 COMPACT 密度），让 MS/insert 子行能贴在它的 QP 底下——一套打包进同一个
# spacing=0 的内层 Column，跟其他内容之间的间距则由外层 Column 的 SPACE_SM 控制。
# 再往下压就会开始切字：14pt 的行盒约 19px，13pt 约 17px。
_ROW_H = 24
_LEAF_ROW_H = 16
# ── 查询结果分列的表头 ────────────────────────────────────────────
# 表头必须**定高**：卷子名长短不一（"Mechanics" 一行、"Probability &
# Statistics 1" 两行），如果按内容自由折行，折行数不同的列就会从不同高度
# 开始铺内容，列与列参差不齐。定高让同一次渲染里所有列用同一个行数，
# 内容一定从同一条基线开始。
#
# 但「定高」不等于「一律留两行」：定高容器里的 Text 是顶对齐的，多留的那一行
# 就成了标题和它底下那条分割线之间一片没人要的空白（分割线离上面的标题比离
# 下面的卷子还远）。所以行数是**按这次的列宽和标题长度算出来的**，只有真的有
# 哪一列放不下才留两行 —— 见 _header_plan。
_COL_SPACING = 16
#: 13pt 行盒约 17px（见 _ROW_H 那条注释），留 1px 余量。
_COL_HEADER_LINE_H = 18
#: 标题最多折两行，再长就省略号。
_COL_HEADER_LINES = 2
#: 13pt 粗体拉丁字符的保守估宽（px/字符），用来判断标题放不放得下一行。
#: 宁可估宽：估宽了顶多多留一行空白（也就是改这版之前的样子），估窄了
#: max_lines 会把标题截成省略号，那是把信息弄丢。
_HEADER_CHAR_W = 7.6
#: 全角字符一个顶一个字宽。syllabus_config.json 是手写的，卷子名填中文
#: 完全可能 —— 按拉丁字宽估会短掉近一半，标题就被截了。
_HEADER_WIDE_CHAR_W = 13.0
#: 列宽窄于此就只显示「Paper X」——名字挤成三四行反而更难看。
#: 想让卷子名更早/更晚出现，调这一个数就够。
_COL_DESC_MIN_W = 150
#: 结果区可用宽度 = 窗口宽 - 左侧导航列 84 - 分隔线 1 - 本页左右 padding 40。
_RESULT_CHROME_W = 125
_FALLBACK_PAGE_W = 1024


def _est_header_w(label: str) -> float:
    """表头标题画出来大概多宽（px）。CJK 起步的码位按全角算，其余按拉丁算。"""
    return sum(
        _HEADER_WIDE_CHAR_W if ord(ch) > 0x2E7F else _HEADER_CHAR_W
        for ch in label
    )


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
    def _per_col_w(n_cols: int) -> float:
        """一列有多宽（px），按当前窗口宽算。"""
        avail = int(page.width or _FALLBACK_PAGE_W) - _RESULT_CHROME_W
        return (avail - _COL_SPACING * (n_cols - 1)) / n_cols

    def _fits_desc(n_cols: int) -> bool:
        """Is each of *n_cols* columns wide enough to carry the paper's name?"""
        if n_cols <= 0:
            return True
        return _per_col_w(n_cols) >= _COL_DESC_MIN_W

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

    # 查询和批量下载共用一把锁：两边都会改 rows / result_list.controls /
    # last_result / rendered_head / total_files，双击或者查询没完就点下载
    # 都会让两个后台线程同时改同一份没上锁的状态。
    busy = [False]
    # (勾选框, 右侧状态文字, 条目) — 只装可勾选的行（qp / gt）
    rows: list[tuple[ft.Checkbox, ft.Text, QueryEntry]] = []
    total_files = [0]  # 这一次查询返回的文件总数，含挂在 qp 下面的 ms / insert
    # 最近一次查询结果 + 它渲染时用的表头模式。留着是为了窗口变宽/变窄时能
    # 就地重排，不必重新发一次网络查询。
    last_result: list[QueryResult | None] = [None]
    #: 拿到 last_result 时用的科目 —— 表头必须按它来标，而不是随手一读下拉框
    #: 当前的值：查完之后用户可能已经把下拉框切到别的科目，此时表头再读
    #: 一次下拉框会用新科目的卷子名去标旧科目查出来的结果。
    last_syllabus_id: list[str | None] = [None]
    #: 上次渲染用的表头方案 (显不显示卷子名, 留几行)，给 _reflow_on_resize 比对。
    rendered_head: list[tuple[bool, int] | None] = [None]

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
        """ci / er 之类（含没配上 QP 的孤儿 MS/insert）：列出来，但不给选择列。"""
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
        if busy[0]:
            show_snack("上一次请求还没完成，请稍候")  # type: ignore[operator]
            return
        if not paper_type_dd.value or not year_dd.value or not season_dd.value:
            show_snack("请先选择完整的查询条件")  # type: ignore[operator]
            return
        syllabus_id, year, season = (
            paper_type_dd.value, year_dd.value, season_dd.value,
        )

        busy[0] = True
        progress_ring.visible = True
        result_list.visible = False
        batch_bar.visible = False
        error_area.visible = False
        status_text.color = theme.MUTED
        status_text.value = "查询中…"
        page.update()

        def _work() -> None:
            try:
                result = query_available(
                    syllabus_id,
                    year,
                    cast(QuerySeason, season),
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
                last_syllabus_id[0] = syllabus_id
                _render_result(result)
            finally:
                busy[0] = False

        page.run_thread(_work)

    def _type_names() -> dict[str, str]:
        """当前结果所属科目的 卷号 → 卷子名（没配就是空表）。

        按 ``last_syllabus_id``（这份结果实际查询时用的科目）来标，而不是
        直接读下拉框此刻的值 —— 查完之后用户切了下拉框，结果还没重新查询，
        这里不能跟着换。还没查过（``None``）时才退回下拉框当前值。
        """
        sid = (
            last_syllabus_id[0]
            if last_syllabus_id[0] is not None else paper_type_dd.value
        )
        selected = next((s for s in syllabi if s.syllabus_id == sid), None)
        return selected.paper_types_as_dict() if selected else {}

    def _header_label(digit: str, named: str | None) -> str:
        return f"Paper {digit}" + (f" · {named}" if named else "")

    def _header_plan(digits: list[str]) -> tuple[bool, int]:
        """这次渲染的表头方案：(显不显示卷子名, 所有列共用几行)。

        行数全列统一，否则「某列一行、某列两行」又会让内容错开基线；但统一的
        那个数按实际标题长度来定，两列都放得下就只留一行，标题和分割线之间
        不留那截空白。
        """
        n_cols = len(digits)
        show_desc = _fits_desc(n_cols)
        if not show_desc or n_cols <= 0:
            return show_desc, 1

        names = _type_names()
        per_col = _per_col_w(n_cols)
        needs_two = any(
            _est_header_w(_header_label(d, names.get(d))) > per_col
            for d in digits
        )
        return True, _COL_HEADER_LINES if needs_two else 1

    def _column_digits(result: QueryResult) -> list[str]:
        return sorted({
            _paper_digit(e.paper_id) for e in result.entries if e.kind == "qp"
        })

    def _render_result(result: QueryResult) -> None:
        total_files[0] = len(result.entries)
        available = {e.paper_id for e in result.entries}
        # 已经作为子行挂在某个 QP 下面的 id（MS 和 insert），底下不再重复列一遍。
        nested: set[str] = set()

        # 按卷号（倒数第二位数字：_11/_12/_13 → 1，_21/_22 → 2）分列，
        # 一张卷子一列，横向铺满窗口。
        groups: dict[str, list[QueryEntry]] = {}
        for entry in result.entries:
            if entry.kind == "qp":
                groups.setdefault(_paper_digit(entry.paper_id), []).append(entry)

        type_names = _type_names()
        show_desc, header_lines = _header_plan(sorted(groups))
        rendered_head[0] = (show_desc, header_lines)

        columns: list[ft.Control] = []
        for digit in sorted(groups):
            named = type_names.get(digit) if show_desc else None
            col: list[ft.Control] = [
                ft.Container(
                    ft.Text(
                        _header_label(digit, named),
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        max_lines=header_lines,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    height=header_lines * _COL_HEADER_LINE_H,
                ),
                ft.Divider(height=9),
            ]
            # QP 打头、对应的 MS 和 insert 作 ╰─ 子行挂在下面；子行不单独占行、
            # 不占选择列，因为勾一个 QP 下的就是一整套（download_with_insert
            # 就是 QP+MS+in 一起下）。一套打包成一个内层 Column（spacing=0，
            # 贴紧成一个整体）；这些整体之间、以及整体和上面表头之间走外层
            # Column 的 SPACE_SM，跟其他内容的间距一致。
            for entry in groups[digit]:
                ms_id = entry.paper_id.replace("_qp_", "_ms_")
                unit: list[ft.Control] = [_selectable_row(entry)]
                if ms_id in available:
                    nested.add(ms_id)
                    unit.append(_leaf(ms_id))
                else:
                    unit.append(_leaf("（没有对应 MS）"))
                # insert 只有部分卷子有（阅读材料、数据册…），没有就什么都不显示，
                # 不像 MS 那样缺了要专门讲一句。
                if entry.has_insert:
                    insert_id = entry.paper_id.replace("_qp_", "_in_")
                    nested.add(insert_id)
                    unit.append(_leaf(insert_id))
                col.append(ft.Column(unit, spacing=0))
            columns.append(ft.Column(col, spacing=theme.SPACE_SM, expand=True))

        if columns:
            result_list.controls.append(
                ft.Row(
                    columns,
                    spacing=_COL_SPACING,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

        # 剩下的：gt 可勾（无子行）；ci/er 之类列出但没有选择列；
        # 没配上 QP 的孤儿 MS / insert 也照样列出来，不让它凭空消失。
        leftovers = [
            e for e in result.entries
            if e.kind != "qp" and e.paper_id not in nested
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
        """Re-lay the result columns when the window crosses a header cutoff.

        Both halves of the header plan depend on the window width — whether the
        paper names fit at all, and whether the longest one needs a second line
        — so the whole plan is what gets compared, not just the name cutoff.

        Returns whether anything was rebuilt, so the caller can skip a
        page.update() entirely on the (overwhelmingly common) resize events
        that change nothing.
        """
        result = last_result[0]
        if result is None:
            return False
        if _header_plan(_column_digits(result)) == rendered_head[0]:
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
        if busy[0]:
            show_snack("上一次请求还没完成，请稍候")  # type: ignore[operator]
            return
        picked = [(cb, note, e) for cb, note, e in rows if cb.value]
        if not picked:
            show_snack("请先勾选要下载的文件")  # type: ignore[operator]
            return

        busy[0] = True
        progress_ring.visible = True
        error_area.controls.clear()
        error_area.visible = False
        page.update()

        def _work() -> None:
            try:
                downloader = PaperDownloader(store=state.store)
                succeeded = skipped = failed = 0
                errors: list[str] = []
                # insert 下载失败不算这一行失败（QP+MS 已经到手），单独攒起来提示。
                warnings: list[str] = []

                for idx, (checkbox, note, entry) in enumerate(picked, start=1):
                    if entry.already_downloaded:
                        skipped += 1
                        checkbox.value = False
                        continue

                    status_text.color = theme.MUTED
                    status_text.value = (
                        f"下载中 {idx}/{len(picked)} — {entry.paper_id}"
                    )
                    page.update()

                    try:
                        request = DownloadRequest(paper_id=entry.paper_id)
                    except ValidationError as exc:
                        failed += 1
                        msgs = "; ".join(
                            e["msg"].removeprefix("Value error, ")
                            for e in exc.errors()
                        )
                        errors.append(f"{entry.paper_id}: {msgs}")
                        continue

                    # 这一列里显示了 insert 子行的，就走 QP+MS+in 那条；
                    # 其余（含 gt）走 download()。
                    dl = (
                        downloader.download_with_insert(request)
                        if entry.has_insert
                        else downloader.download(request)
                    )
                    if dl.success:
                        succeeded += 1
                        if dl.insert_error:
                            warnings.append(
                                f"{entry.paper_id} 的 insert 没下到: "
                                f"{dl.insert_error}"
                            )
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
                    error_area.controls.extend(
                        error_banner(msg) for msg in errors[:5]
                    )
                    if len(errors) > 5:
                        error_area.controls.append(
                            ft.Text(
                                f"…另有 {len(errors) - 5} 条失败",
                                size=12,
                                color=theme.DANGER,
                            )
                        )
                    error_area.visible = True

                if warnings:
                    error_area.controls.extend(
                        warning_banner(msg) for msg in warnings[:5]
                    )
                    error_area.visible = True

                page.update()
                show_snack(  # type: ignore[operator]
                    f"成功 {succeeded} · 跳过 {skipped} · 失败 {failed}",
                    theme.DANGER if failed else theme.SUCCESS,
                )
            finally:
                busy[0] = False

        page.run_thread(_work)

    send_btn = ft.Button(
        "查询",
        icon=ft.CupertinoIcons.SEARCH,
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
                ft.Row([
                    ft.Container(
                        ft.Column(
                            [
                                picker.row(),
                                ft.Container(height=12),
                                ft.Row(
                                    [send_btn, progress_ring],
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=4,
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
                # 批量下载栏放列表上面：列表可能很长，按钮别被顶到看不见的地方。
                batch_bar,
                result_list,
                error_area,
            ],
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        padding=theme.SPACE_XL // 2,
    )
