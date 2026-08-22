"""错题本 — browse every question a grading run took marks off, and export.

Two views over the same rows: by paper (the default — one collapsible group
per paper, matching how they were graded) and by topic (the same, grouped by
topic, with a chip filter for "which topic do I keep losing marks on").
Every decision about the rows themselves — grouping, filtering, CSV — lives
in ``modules.marking.mistakes``; this module only builds controls.

A standalone tab rather than a section of 统计: that tab is
aggregate-trend-shaped and this is a browse-select-export flow.

Styling follows the app's design language (docs/superpowers/specs/
2026-08-10-ui-design-language-design.md): white cards on the muted page
background, distinguished by soft shadow and a 10px radius; the shared
``data_table`` for anything tabular, so columns line up with the rest of the
app instead of being hand-spaced ``Row``s; ``theme`` tokens for every size
and gap; CupertinoIcons. Groups collapse by default and build their table on
first expand, the same as 统计's syllabus panels.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.widgets import data_table
from core.models import MistakeRecord
from core.storage import CSVStore, MistakeStore
from modules.marking.answer_sheet import build_answer_sheet
from modules.marking.mistake_pdf import build_export
from modules.marking.mistakes import (
    UNCLASSIFIED,
    distinct_topic_keys,
    filter_by_topic,
    group_by_paper,
    retag,
    subject_id_of,
    to_csv,
    topic_key,
)
from modules.marking.syllabus_parser import load_syllabus
from modules.marking.workflow import topics_for_paper

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from app_flet.state import AppState

_log = logging.getLogger("cie_helper.mistakes")

_BY_PAPER = "paper"
_BY_TOPIC = "topic"
_EXPORT_FILENAME = "mistakes.csv"
_EXPORT_PDF_FILENAME = "mistakes.pdf"
_EXPORT_ANSWERS_FILENAME = "mistakes-answers.pdf"

# ── Column widths ─────────────────────────────────────────────────
#
# The comment is the only free-text column, so it is the one that has to be
# told how much room is left — sized to content it pushes the table past the
# window edge and drags every other column with it. Everything else gets a
# fixed width so that "how much is left" is arithmetic rather than a guess.

#: main.py's nav rail (64 + 20 padding) plus its 1px divider. ``page.width``
#: is the whole window, so this comes off first — same constant, same reason,
#: as analytics.py's ``_NAV_CHROME_W``.
_NAV_CHROME_W = 85
#: DataTable's own horizontal margin (24 each side) plus its checkbox column.
_TABLE_CHROME = 48 + 48
#: DataTable's default gap between columns; ``data_table`` doesn't override it.
_COL_SPACING = 56

#: What each column gets when there is room. The comment's ideal is also its
#: cap — past ~420px it reads as a wall of text, not a column. Topic is wider
#: than its text needs because it holds a dropdown, whose arrow and padding
#: eat into the label.
_IDEAL: dict[str, int] = {
    "question": 80, "paper": 130, "topic": 210, "score": 60, "comment": 420,
}
#: What each column may be squeezed to before something has to give.
_MIN: dict[str, int] = {
    "question": 56, "paper": 96, "topic": 140, "score": 48, "comment": 90,
}
#: Row height. The default is sized for plain text and clips the dropdown.
_ROW_HEIGHT = 52.0
#: Who gives up room first. The comment is elided anyway, the score never
#: needs more than four glyphs.
_SHRINK_ORDER = ("comment", "topic", "paper", "question", "score")


def _usable_width(page: ft.Page, columns: int) -> int:
    """Room left for cell content once every fixed cost is paid."""
    return (
        int(page.width or 1024)
        - _NAV_CHROME_W
        - theme.SPACE_XL * 2            # page padding
        - theme.SPACE_LG * 2            # card padding
        - _TABLE_CHROME
        - _COL_SPACING * (columns - 1)
    )


def _column_widths(
    page: ft.Page, *, show_paper: bool
) -> tuple[dict[str, int], bool]:
    """Pin every column to a width that fits the window.

    Sized rather than left to the content because the comment is free text:
    one long one sizes its column to itself and pushes the whole table past
    the window edge. Returns the widths plus whether the 试卷 column survived
    — on a narrow window it is dropped rather than overflowing, and the paper
    id moves into the 题号 cell's tooltip.
    """
    for with_paper in ([True, False] if show_paper else [False]):
        keys = [
            k for k in ("question", "paper", "topic", "score", "comment")
            if k != "paper" or with_paper
        ]
        avail = _usable_width(page, len(keys))
        widths = {k: _IDEAL[k] for k in keys}
        over = sum(widths.values()) - avail
        for key in _SHRINK_ORDER:
            if over <= 0 or key not in widths:
                continue
            take = min(widths[key] - _MIN[key], over)
            widths[key] -= take
            over -= take
        if over <= 0 or not with_paper:
            return widths, with_paper
    return widths, False


def _score_text(record: MistakeRecord) -> str:
    return f"{record.score:g}/{record.max_score:g}"


def _topic_text(record: MistakeRecord) -> str:
    if record.topic_name:
        return (
            f"{record.topic_id} {record.topic_name}"
            if record.topic_id
            else record.topic_name
        )
    # An id with no name means the model answered with something the
    # syllabus doesn't list — worth showing rather than hiding as 未分类.
    return record.topic_id or UNCLASSIFIED


def _topic_choices(paper_id: str) -> dict[str, str] | None:
    """Topic id → name this paper may be tagged with, or None if unknown.

    Exactly the list the grader was given for the same paper — the syllabus
    stored for its subject, narrowed to its component. Correcting a tag by
    hand therefore offers the same range the model chose from (Chemistry
    Paper 1 → topics 1–22), not every topic in the syllabus.
    """
    info = load_syllabus(subject_id_of(paper_id))
    return topics_for_paper(info, paper_id)


def _topic_label(topic_id: str, name: str | None) -> str:
    return f"{topic_id} {name}" if name else topic_id


def _card(*controls: ft.Control) -> ft.Container:
    """One white surface. Soft shadow + hairline, per the design language."""
    return ft.Container(
        ft.Column(list(controls), spacing=theme.SPACE_MD),
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def _cell(
    text: str,
    width: int,
    *,
    size: int = theme.BODY,
    color: str | None = None,
    lines: int = 1,
    tooltip: str | None = None,
) -> ft.DataCell:
    """A width-pinned cell; anything longer is elided with the full text on
    hover, so one long comment can't widen the table."""
    return ft.DataCell(ft.Container(
        ft.Text(
            text,
            size=size,
            color=color,
            max_lines=lines,
            overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=tooltip or text or None,
        ),
        width=width,
    ))


def _columns(*labels: str) -> list[ft.DataColumn]:
    return [
        ft.DataColumn(label=ft.Text(
            label, size=theme.CAPTION, weight=ft.FontWeight.W_600,
        ))
        for label in labels
    ]


def _event_flag(data: object) -> bool:
    """Flet sends selection state as a bool or as "true"/"false"."""
    return data if isinstance(data, bool) else str(data).strip().lower() == "true"


def build_mistakes_tab(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    export_picker: ft.FilePicker,
) -> ft.Container:
    """Build the 错题本 tab.

    ``state`` is unused today but kept for symmetry with every other
    ``build_*_tab``.
    """
    del state  # every other tab takes it; nothing here needs it yet

    store = MistakeStore()
    try:
        records = store.load_all()
    except ValueError as exc:
        return _page_shell(
            ft.Text(f"错题记录读取失败: {exc}", color=theme.DANGER,
                    size=theme.BODY),
        )

    if not records:
        return _page_shell(
            ft.Text("错题本", size=theme.TITLE, weight=ft.FontWeight.BOLD),
            _card(
                ft.Row([
                    ft.Icon(ft.CupertinoIcons.BOOK, color=theme.MUTED),
                    ft.Text("还没有错题记录", size=theme.SUBHEAD,
                            weight=ft.FontWeight.W_600),
                ], spacing=theme.SPACE_SM),
                ft.Text(
                    "批改一份「从已下载试卷」选出的卷子并点「确认并记录分数」后，"
                    "没拿满分的题会自动记到这里。",
                    size=theme.CAPTION, color=theme.MUTED,
                ),
            ),
        )

    # Selection is keyed by position in ``records``: the store is append-only
    # and rows are not unique on their own (a re-grade repeats paper+question).
    selected: set[int] = set()
    active_topics: set[str] = set()
    view = _BY_PAPER
    content_area = ft.Column(spacing=theme.SPACE_MD)
    count_text = ft.Text("", size=theme.CAPTION, color=theme.MUTED)

    def _refresh_count() -> None:
        """Only the counter changes on a tick — rebuilding the views instead
        would collapse the very group the user is ticking inside."""
        count_text.value = f"已选 {len(selected)} / {len(records)} 题"
        page.update()

    # ── Topic picker ──────────────────────────────────────────────

    def _topic_picker(idx: int, width: int) -> ft.Control:
        """The topic cell: a dropdown over this paper's own topic range.

        The model's tag is a guess, and on a practical paper or a subject
        with no syllabus there is no tag at all — so the column is editable
        rather than a label. Writes straight through to the store: the row
        is identified by its position, which is what the store's ``update_at``
        takes.
        """
        record = records[idx]
        choices = _topic_choices(record.paper_id)
        if not choices:
            # No syllabus for this subject (or a component it doesn't map,
            # like a practical paper) — nothing to choose from, so say why
            # instead of showing an empty dropdown.
            return ft.Container(
                ft.Text(
                    _topic_text(record),
                    size=theme.CAPTION,
                    color=theme.MUTED,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip="该科目未导入大纲，或这张卷不在大纲的 component 映射里",
                ),
                width=width,
            )

        options = [ft.dropdown.Option(key="", text=UNCLASSIFIED)]
        options.extend(
            ft.dropdown.Option(key=tid, text=_topic_label(tid, name))
            for tid, name in choices.items()
        )
        # An id the syllabus doesn't list (the model invented it, or the
        # syllabus was re-parsed since) would otherwise vanish from the
        # dropdown and read as 未分类.
        if record.topic_id and record.topic_id not in choices:
            options.append(ft.dropdown.Option(
                key=record.topic_id,
                text=_topic_label(record.topic_id, record.topic_name),
            ))

        def _on_select(e: ft.Event[ft.Dropdown], idx: int = idx) -> None:
            _set_topic(idx, str(e.data or ""))

        return ft.Dropdown(
            options=options,
            value=record.topic_id or "",
            width=width,
            text_size=theme.CAPTION,
            dense=True,
            border_color=theme.HAIRLINE,
            on_select=_on_select,
        )

    def _set_topic(idx: int, topic_id: str) -> None:
        record = records[idx]
        updated = retag(
            record, topic_id or None, _topic_choices(record.paper_id)
        )
        if updated == record:
            return
        try:
            store.update_at(idx, updated)
        except (OSError, ValueError, IndexError) as exc:
            show_snack(f"topic 保存失败: {exc}", theme.DANGER)
            return
        records[idx] = updated
        # The by-topic view groups on this very field, so the row has to move
        # — that needs the rebuild. The by-paper view doesn't regroup, and
        # rebuilding there would collapse the card being edited.
        if view == _BY_TOPIC:
            _rebuild_content()
        else:
            page.update()

    # ── Table ─────────────────────────────────────────────────────

    def _table(indices: Sequence[int], *, show_paper: bool) -> ft.Control:
        widths, paper_col = _column_widths(page, show_paper=show_paper)
        rows: list[ft.DataRow] = []

        for idx in indices:
            record = records[idx]
            cells = [_cell(
                record.question_id,
                widths["question"],
                # When the window was too narrow for a 试卷 column, this is
                # the only place left to read the paper id.
                tooltip=None if paper_col else record.paper_id,
            )]
            if paper_col:
                cells.append(_cell(
                    record.paper_id, widths["paper"], size=theme.CAPTION,
                ))
            cells.extend([
                ft.DataCell(_topic_picker(idx, widths["topic"])),
                _cell(_score_text(record), widths["score"]),
                _cell(
                    record.comment, widths["comment"],
                    size=theme.CAPTION, color=theme.MUTED, lines=2,
                ),
            ])
            rows.append(ft.DataRow(cells=cells, selected=idx in selected))

        for row, idx in zip(rows, indices, strict=True):
            def _on_select(
                e: ft.Event[ft.DataRow], row: ft.DataRow = row, idx: int = idx,
            ) -> None:
                picked = _event_flag(e.data)
                row.selected = picked
                if picked:
                    selected.add(idx)
                else:
                    selected.discard(idx)
                _refresh_count()

            row.on_select_change = _on_select

        def _on_select_all(e: ft.Event[ft.DataTable]) -> None:
            picked = _event_flag(e.data)
            for row, idx in zip(rows, indices, strict=True):
                row.selected = picked
                if picked:
                    selected.add(idx)
                else:
                    selected.discard(idx)
            _refresh_count()

        labels = (
            ("题号", "试卷", "Topic", "得分", "评语") if paper_col
            else ("题号", "Topic", "得分", "评语")
        )
        return data_table(
            _columns(*labels),
            rows,
            show_checkbox_column=True,
            on_select_all=_on_select_all,
            # The topic column holds a dropdown; the default row height is
            # sized for plain text and clips it.
            row_height=_ROW_HEIGHT,
        )

    def _group_tile(
        title: str,
        subtitle: str,
        icon: ft.IconData,
        indices: Sequence[int],
        *,
        show_paper: bool,
    ) -> ft.Control:
        """A collapsed group whose table is built the first time it opens.

        Same lazy pattern as 统计's syllabus panels: with a term's worth of
        papers in the store, building every table up front is work the user
        never asked for.
        """
        body = ft.Column()
        built = [False]

        def _on_change(e: ft.Event[ft.ExpansionTile]) -> None:
            if _event_flag(e.data) and not built[0]:
                built[0] = True
                body.controls.append(_table(indices, show_paper=show_paper))
                page.update()

        return _card(ft.ExpansionTile(
            title=ft.Row(
                [
                    ft.Icon(icon, color=theme.PRIMARY, size=18),
                    ft.Text(title, size=theme.SUBHEAD,
                            weight=ft.FontWeight.W_600),
                    ft.Text(subtitle, size=theme.CAPTION, color=theme.MUTED),
                ],
                spacing=theme.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expanded=False,
            on_change=_on_change,
            controls=[ft.Container(
                body,
                padding=ft.Padding(
                    left=0, right=0, top=theme.SPACE_XS,
                    bottom=theme.SPACE_MD,
                ),
            )],
        ))

    # ── By paper ──────────────────────────────────────────────────

    def _paper_view() -> list[ft.Control]:
        index_by_paper: dict[str, list[int]] = {}
        for i, record in enumerate(records):
            index_by_paper.setdefault(record.paper_id, []).append(i)

        return [
            _group_tile(
                paper_id,
                f"{len(index_by_paper[paper_id])} 题",
                ft.CupertinoIcons.DOC_TEXT,
                index_by_paper[paper_id],
                show_paper=False,
            )
            for paper_id in group_by_paper(records)
        ]

    # ── By topic ──────────────────────────────────────────────────

    def _topic_chip(key: str) -> ft.Chip:
        def _on_select(e: ft.Event[ft.Chip]) -> None:
            if e.control.selected:
                active_topics.add(key)
            else:
                active_topics.discard(key)
            _rebuild_content()

        return ft.Chip(
            label=ft.Text(key, size=theme.CAPTION),
            selected=key in active_topics,
            show_checkmark=True,
            bgcolor=theme.SURFACE,
            selected_color=theme.PRIMARY_TINT,
            on_select=_on_select,
        )

    def _topic_view() -> list[ft.Control]:
        shown = filter_by_topic(records, active_topics)
        shown_ids = {id(r) for r in shown}
        index_by_topic: dict[str, list[int]] = {}
        for i, record in enumerate(records):
            if id(record) in shown_ids:
                index_by_topic.setdefault(topic_key(record), []).append(i)

        filter_card = _card(
            ft.Row([
                ft.Icon(ft.CupertinoIcons.TAG, color=theme.PRIMARY, size=18),
                ft.Text("按 topic 过滤", size=theme.SUBHEAD,
                        weight=ft.FontWeight.W_600),
                ft.Text("不选＝全部", size=theme.CAPTION, color=theme.MUTED),
            ], spacing=theme.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row(
                [_topic_chip(key) for key in distinct_topic_keys(records)],
                spacing=theme.SPACE_SM,
                run_spacing=theme.SPACE_SM,
                wrap=True,
            ),
        )
        tiles = [
            _group_tile(
                key,
                f"{len(indices)} 题",
                ft.CupertinoIcons.TAG,
                indices,
                show_paper=True,
            )
            for key, indices in index_by_topic.items()
        ]
        return [filter_card, *tiles]

    # ── Export ────────────────────────────────────────────────────

    async def _do_export() -> None:
        chosen = [records[i] for i in sorted(selected)]
        if not chosen:
            show_snack("请先勾选要导出的错题", theme.WARNING)
            return
        # utf-8-sig: Excel reads a plain UTF-8 CSV as mojibake, and every
        # comment in here is Chinese.
        path = await export_picker.save_file(
            dialog_title="导出所选错题",
            file_name=_EXPORT_FILENAME,
            allowed_extensions=["csv"],
            src_bytes=to_csv(chosen).encode("utf-8-sig"),
        )
        if path:
            show_snack(f"已导出 {len(chosen)} 题 → {path}", theme.SUCCESS)

    def _on_export_click(_: ft.Event[ft.TextButton]) -> None:
        page.run_task(_do_export)

    async def _do_export_pdf() -> None:
        chosen = [records[i] for i in sorted(selected)]
        if not chosen:
            show_snack("请先勾选要导出的错题", theme.WARNING)
            return
        try:
            qp_of = {r.paper_id: r.qp_path for r in CSVStore().load_all()}
        except ValueError as exc:
            show_snack(f"读取试卷记录失败: {exc}", theme.DANGER)
            return

        show_snack("正在从原卷裁剪题目…", theme.ACCENT)
        try:
            # Two pdfminer passes per paper — off the event loop, or the
            # window freezes for the duration.
            data, warnings = await asyncio.to_thread(
                build_export, chosen, qp_of
            )
        except ValueError as exc:
            show_snack(f"导出失败: {exc}", theme.DANGER)
            return
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            _log.exception("mistake PDF export failed")
            show_snack(f"导出失败: {exc}", theme.DANGER)
            return

        path = await export_picker.save_file(
            dialog_title="导出所选错题（PDF）",
            file_name=_EXPORT_PDF_FILENAME,
            allowed_extensions=["pdf"],
            src_bytes=data,
        )
        if not path:
            return
        if warnings:
            show_snack(
                f"已导出 → {path}；{len(warnings)} 项未包含: "
                f"{'；'.join(warnings)}",
                theme.WARNING,
            )
        else:
            show_snack(f"已导出 → {path}", theme.SUCCESS)

    def _on_export_pdf_click(_: ft.Event[ft.Button]) -> None:
        page.run_task(_do_export_pdf)

    async def _do_export_answers() -> None:
        chosen = [records[i] for i in sorted(selected)]
        if not chosen:
            show_snack("请先勾选要导出的错题", theme.WARNING)
            return
        try:
            ms_of = {r.paper_id: r.ms_path for r in CSVStore().load_all()}
        except ValueError as exc:
            show_snack(f"读取试卷记录失败: {exc}", theme.DANGER)
            return

        show_snack("正在排版答案…", theme.ACCENT)
        try:
            # Reads the mark-scheme cache and lays out text — no PDF work
            # and no network, but still off the event loop.
            data, warnings = await asyncio.to_thread(
                build_answer_sheet, chosen, ms_of
            )
        except ValueError as exc:
            show_snack(f"导出失败: {exc}", theme.DANGER)
            return
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            _log.exception("answer sheet export failed")
            show_snack(f"导出失败: {exc}", theme.DANGER)
            return

        path = await export_picker.save_file(
            dialog_title="导出所选错题的答案（PDF）",
            file_name=_EXPORT_ANSWERS_FILENAME,
            allowed_extensions=["pdf"],
            src_bytes=data,
        )
        if not path:
            return
        if warnings:
            show_snack(
                f"已导出 → {path}；{len(warnings)} 项未包含: "
                f"{'；'.join(warnings)}",
                theme.WARNING,
            )
        else:
            show_snack(f"已导出 → {path}", theme.SUCCESS)

    def _on_export_answers_click(_: ft.Event[ft.TextButton]) -> None:
        page.run_task(_do_export_answers)

    # ── Shell ─────────────────────────────────────────────────────

    view_selector = ft.SegmentedButton(
        segments=[
            ft.Segment(value=_BY_PAPER, label=ft.Text("按卷")),
            ft.Segment(value=_BY_TOPIC, label=ft.Text("按 topic")),
        ],
        selected=[view],
        allow_multiple_selection=False,
    )

    def _rebuild_content() -> None:
        nonlocal view
        view = (
            view_selector.selected[0] if view_selector.selected else _BY_PAPER
        )
        content_area.controls.clear()
        content_area.controls.extend(
            _paper_view() if view == _BY_PAPER else _topic_view()
        )
        count_text.value = f"已选 {len(selected)} / {len(records)} 题"
        page.update()

    view_selector.on_change = lambda _: _rebuild_content()
    _rebuild_content()

    return _page_shell(
        ft.Row(
            [
                ft.Text("错题本", size=theme.TITLE,
                        weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                count_text,
                ft.TextButton(
                    "导出 CSV",
                    icon=ft.CupertinoIcons.ARROW_DOWN_DOC,
                    on_click=_on_export_click,
                ),
                ft.TextButton(
                    "导出答案",
                    icon=ft.CupertinoIcons.CHECKMARK_SEAL,
                    tooltip="把所选题目的 mark scheme 排成一份答案 —— "
                            "用批改时已解析的结果，不会重新解析",
                    on_click=_on_export_answers_click,
                ),
                ft.Button(
                    "导出 PDF",
                    icon=ft.CupertinoIcons.DOC_ON_CLIPBOARD,
                    tooltip="把所选题目从原卷裁下来，一道大题一页（不含答题横线）",
                    on_click=_on_export_pdf_click,
                    style=theme.filled_button(),
                ),
            ],
            spacing=theme.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        view_selector,
        content_area,
    )


def _page_shell(*controls: ft.Control) -> ft.Container:
    """Page padding + the standard vertical rhythm, no spacer hacks."""
    return ft.Container(
        ft.Column(list(controls), spacing=theme.SPACE_MD),
        padding=theme.SPACE_XL,
    )
