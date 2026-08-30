"""【错题】— browse every question a grading run took marks off, and export.

Two views over the same rows: by paper (the default — one collapsible group
per paper, matching how they were graded) and by topic (the same, grouped by
topic, with a chip filter for "which topic do I keep losing marks on").
Every decision about the rows themselves — grouping, filtering, CSV — lives
in ``modules.marking.mistakes``; this module only builds controls.

行的样式来自 :mod:`app_flet.tabs.manage.organize` 的 ``finder_*`` —— 一行是
一道题而不是一张卷，列自然不一样，共用的是外观。分组是重点：一张卷一组，组里
是它的题。Groups collapse by default and build their table on first expand,
the same as 总览's syllabus panels.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.components.widgets import push_track, segmented_strip
from app_flet.tabs.manage.organize import (
    FINDER_ROW_PAD,
    finder_header,
    finder_label,
    finder_list,
    finder_row,
    finder_text,
)
from app_flet.tabs.manage.paper_icon import syllabus_names
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
    split_topic_key,
    subject_id_of,
    to_csv,
    topic_key,
)
from modules.marking.syllabus_parser import load_syllabus
from modules.marking.workflow import topics_for_paper

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from app_flet.state import AppState

_log = logging.getLogger("cie_helper.mistakes")

#: 两个视图在分段条上的先后。序号即推拉的方向。
_BY_PAPER = "paper"
_BY_TOPIC = "topic"
_VIEWS = (_BY_PAPER, _BY_TOPIC)
_EXPORT_FILENAME = "mistakes.csv"
_EXPORT_PDF_FILENAME = "mistakes.pdf"
_EXPORT_ANSWERS_FILENAME = "mistakes-answers.pdf"

# ── Column widths ─────────────────────────────────────────────────
#
# The comment is the only free-text column, so it is the one that has to be
# told how much room is left — sized to content it pushes the table past the
# window edge and drags every other column with it. Everything else gets a
# fixed width so that "how much is left" is arithmetic rather than a guess.

#: 勾选框那一格的宽。
_CHECKBOX_W = 40

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
#: 行高。默认那档是按一行纯文本算的，这里一格里塞了下拉框，还有两行的评语。
_ROW_H = 52
#: Who gives up room first. The comment is elided anyway, the score never
#: needs more than four glyphs.
_SHRINK_ORDER = ("comment", "topic", "paper", "question", "score")
_KEYS = ("question", "paper", "topic", "score", "comment")
_LABELS = {
    "question": "题号", "paper": "试卷", "topic": "Topic",
    "score": "得分", "comment": "评语",
}


def _usable_width(page: ft.Page, columns: int) -> int:
    """一行里留给内容的宽 —— 每一项固定开销都减掉之后剩下的。

    间隙数按 ``columns`` 算而不是 ``columns - 1``：勾选框和第一格之间也有一道。
    """
    return (
        int(page.width or 1024)
        - theme.NAV_CHROME_W
        - theme.SPACE_XL * 2            # 页面边距
        - theme.SPACE_LG * 2            # 卡片内边距
        - FINDER_ROW_PAD * 2            # 行内边距
        - _CHECKBOX_W
        - theme.SPACE_MD * columns      # 每格之间的间隙
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
        keys = [k for k in _KEYS if k != "paper" or with_paper]
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


def _event_flag(data: object) -> bool:
    """Flet sends selection state as a bool or as "true"/"false"."""
    return data if isinstance(data, bool) else str(data).strip().lower() == "true"


def build_mistakes(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    export_picker: ft.FilePicker,
) -> ft.Control:
    """Build the 错题 section.

    ``state`` is unused today but kept for symmetry with the other sections.
    """
    del state  # every other section takes it; nothing here needs it yet

    store = MistakeStore()
    try:
        records = store.load_all()
    except ValueError as exc:
        return ft.Text(
            f"错题记录读取失败: {exc}", color=theme.DANGER, size=theme.BODY,
        )

    if not records:
        return _card(
            ft.Row([
                ft.Icon(ft.CupertinoIcons.BOOK, color=theme.MUTED),
                ft.Text("还没有错题记录", size=theme.SUBHEAD,
                        weight=ft.FontWeight.W_600),
            ], spacing=theme.SPACE_SM),
            ft.Text(
                "批改一份「从已下载试卷」选出的卷子并点「确认并记录分数」后，"
                "没拿满分的题会自动记到这里。",
                size=theme.CAPTION, color=theme.MUTED,
                style=theme.caption_style(),
            ),
        )

    # Selection is keyed by position in ``records``: the store is append-only
    # and rows are not unique on their own (a re-grade repeats paper+question).
    selected: set[int] = set()
    active_topics: set[str] = set()
    #: syllabus code → 学科名，给 by-topic 那层分组的标题用。
    names = syllabus_names()
    view = _BY_PAPER
    content_area, show_view = push_track(
        page, len(_VIEWS), ft.Column(spacing=theme.SPACE_MD),
    )
    count_text = ft.Text(
        "", size=theme.CAPTION, color=theme.MUTED,
        style=theme.caption_style(),
    )

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
            return finder_text(
                _topic_text(record), width,
                size=theme.CAPTION, color=theme.MUTED, lines=2,
                tooltip="该科目未导入大纲，或这张卷不在大纲的 component 映射里",
                style=theme.caption_style(),
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
        keys = [k for k in _KEYS if k != "paper" or paper_col]
        boxes: dict[int, ft.Checkbox] = {}
        repaints: dict[int, Callable[[], None]] = {}
        rows: list[ft.Control] = []

        def _set(idx: int, picked: bool) -> None:
            if picked:
                selected.add(idx)
            else:
                selected.discard(idx)
            boxes[idx].value = picked
            repaints[idx]()
            _refresh_count()

        for idx in indices:
            record = records[idx]
            box = ft.Checkbox(value=idx in selected)
            boxes[idx] = box
            cells: list[ft.Control] = [
                ft.Container(box, width=_CHECKBOX_W),
                finder_text(
                    record.question_id, widths["question"],
                    style=theme.numeric_style(),
                    # When the window was too narrow for a 试卷 column, this
                    # is the only place left to read the paper id.
                    tooltip=None if paper_col else record.paper_id,
                ),
            ]
            if paper_col:
                cells.append(finder_text(
                    record.paper_id, widths["paper"], size=theme.CAPTION,
                    style=theme.numeric_style(),
                ))
            cells.extend([
                _topic_picker(idx, widths["topic"]),
                finder_text(
                    _score_text(record), widths["score"],
                    style=theme.numeric_style(),
                ),
                finder_text(
                    record.comment, widths["comment"],
                    size=theme.CAPTION, color=theme.MUTED, lines=2,
                    style=theme.caption_style(),
                ),
            ])

            def _on_row(
                _: ft.Event[ft.Container], idx: int = idx,
            ) -> None:
                _set(idx, idx not in selected)

            def _on_box(
                e: ft.Event[ft.Checkbox], idx: int = idx,
            ) -> None:
                _set(idx, _event_flag(e.data))

            def _is_picked(idx: int = idx) -> bool:
                return idx in selected

            row, repaint = finder_row(
                cells,
                on_click=_on_row,
                height=_ROW_H,
                selected=_is_picked,
            )
            repaints[idx] = repaint
            box.on_change = _on_box
            rows.append(row)

        def _on_select_all(e: ft.Event[ft.Checkbox]) -> None:
            picked = _event_flag(e.data)
            for idx in indices:
                if picked:
                    selected.add(idx)
                else:
                    selected.discard(idx)
                boxes[idx].value = picked
                repaints[idx]()
            _refresh_count()

        header = finder_header(
            [
                ft.Container(
                    ft.Checkbox(
                        value=all(i in selected for i in indices),
                        on_change=_on_select_all,
                    ),
                    width=_CHECKBOX_W,
                ),
                *(finder_label(_LABELS[k], widths[k]) for k in keys),
            ],
            height=_ROW_H,
        )
        return finder_list(header, rows)

    def _group_tile(
        title: str,
        subtitle: str,
        icon: ft.IconData,
        indices: Sequence[int],
        *,
        show_paper: bool,
        boxed: bool = True,
    ) -> ft.Control:
        """A collapsed group whose table is built the first time it opens.

        Same lazy pattern as 总览's syllabus panels: with a term's worth of
        papers in the store, building every table up front is work the user
        never asked for.

        ``boxed=False`` 去掉外面那层卡片：嵌在别的组里时，两层卡片会叠出双重
        描边和双重阴影，读起来像两块面板而不是一块里的一条。
        """
        body = ft.Column()
        built = [False]

        def _on_change(e: ft.Event[ft.ExpansionTile]) -> None:
            if _event_flag(e.data) and not built[0]:
                built[0] = True
                body.controls.append(_table(indices, show_paper=show_paper))
                page.update()

        tile = ft.ExpansionTile(
            title=ft.Row(
                [
                    ft.Icon(icon, color=theme.PRIMARY, size=18),
                    ft.Text(title, size=theme.SUBHEAD,
                            weight=ft.FontWeight.W_600),
                    ft.Text(
                        subtitle, size=theme.CAPTION, color=theme.MUTED,
                        style=theme.caption_style(),
                    ),
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
        )
        return _card(tile) if boxed else tile

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

    def _by_syllabus(keys: Iterable[str]) -> dict[str, dict[str, str]]:
        """``["9701 · Equilibria", …]`` → ``{"9701": {"Equilibria": <key>}}``。

        两层都靠 dict 的插入序，而喂进来的 key 是 ``distinct_topic_keys``
        排好的（未分类垫底），所以学科的先后和每个学科里 topic 的先后都是稳
        的，未分类也仍然落在各自学科的最后一个。
        """
        grouped: dict[str, dict[str, str]] = {}
        for key in keys:
            syl, name = split_topic_key(key)
            grouped.setdefault(syl, {})[name] = key
        return grouped

    def _syllabus_label(syl: str) -> str:
        if not syl:
            return UNCLASSIFIED
        name = names.get(syl)
        return f"{syl} — {name}" if name else syl

    def _topic_chip(key: str, label: str) -> ft.Chip:
        def _on_select(e: ft.Event[ft.Chip]) -> None:
            if e.control.selected:
                active_topics.add(key)
            else:
                active_topics.discard(key)
            _rebuild_content()

        return ft.Chip(
            # 芯片上只写 topic 名，学科代码由它上面那行小标题交代 —— 每颗都
            # 顶着一遍「9701 · 」时，一行放不下几颗，而且真正要读的那半截被
            # 挤到了后面。
            label=ft.Text(
                label, size=theme.CAPTION, style=theme.caption_style(),
            ),
            selected=key in active_topics,
            show_checkmark=True,
            bgcolor=theme.SURFACE,
            selected_color=theme.PRIMARY_TINT,
            on_select=_on_select,
        )

    def _chip_group(syl: str, topics: dict[str, str]) -> ft.Control:
        return ft.Column(
            [
                ft.Text(
                    _syllabus_label(syl),
                    size=theme.CAPTION, color=theme.MUTED,
                    weight=ft.FontWeight.W_600,
                    style=theme.caption_style(),
                ),
                ft.Row(
                    [
                        _topic_chip(key, name)
                        for name, key in topics.items()
                    ],
                    spacing=theme.SPACE_SM,
                    run_spacing=theme.SPACE_SM,
                    wrap=True,
                ),
            ],
            spacing=theme.SPACE_XS,
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
                ft.Text(
                    "不选＝全部", size=theme.CAPTION, color=theme.MUTED,
                    style=theme.caption_style(),
                ),
            ], spacing=theme.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
            *(
                _chip_group(syl, topics)
                for syl, topics in _by_syllabus(
                    distinct_topic_keys(records)
                ).items()
            ),
        )
        # 下面的分组列表按同一层次分：芯片按学科分了，列表还平铺的话，同一份
        # 数据在一屏里有两种组织方式。
        return [filter_card, *(
            _syllabus_group(
                syl, {name: index_by_topic[key] for name, key in topics.items()},
            )
            for syl, topics in _by_syllabus(index_by_topic).items()
        )]

    def _syllabus_group(
        syl: str, topics: dict[str, list[int]],
    ) -> ft.Control:
        """一个 syllabus 一块卡片，里面是它自己的 topic 分组。

        外层不做懒加载：里面每个 topic 组的表格各自懒建，这一层只是把它们的
        标题排起来，本来就没有多少活。
        """
        total = sum(len(v) for v in topics.values())
        return _card(ft.ExpansionTile(
            leading=ft.Icon(
                ft.CupertinoIcons.BOOK_FILL, color=theme.PRIMARY, size=18,
            ),
            title=ft.Row(
                [
                    ft.Text(
                        _syllabus_label(syl),
                        size=theme.SUBHEAD, weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        f"{len(topics)} 个 topic · {total} 题",
                        size=theme.CAPTION, color=theme.MUTED,
                        style=theme.caption_style(),
                    ),
                ],
                spacing=theme.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expanded=False,
            controls=[
                _group_tile(
                    topic,
                    f"{len(indices)} 题",
                    ft.CupertinoIcons.TAG,
                    indices,
                    show_paper=True,
                    boxed=False,
                )
                for topic, indices in topics.items()
            ],
        ))

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
            papers = CSVStore().load_all()
        except ValueError as exc:
            show_snack(f"读取试卷记录失败: {exc}", theme.DANGER)
            return
        qp_of = {r.paper_id: r.qp_path for r in papers}
        ms_of = {r.paper_id: r.ms_path for r in papers}

        show_snack("正在从原卷裁剪题目…", theme.ACCENT)
        try:
            # Two pdfminer passes per paper — off the event loop, or the
            # window freezes for the duration.
            data, warnings = await asyncio.to_thread(
                build_export, chosen, qp_of, ms_of
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

    def _rebuild_content() -> None:
        # 每次给一个**新的** Column：换的是格子里挂的是谁，原地 clear +
        # extend 会把旧树销毁掉，Flutter 侧就没有可供补间的东西。
        #
        # 序号没变时 push_track 只换内容不推 —— 改 topic 标签、点 topic 过滤
        # 芯片走的都是这条，同一个视图重排一遍，推一下会读成换了页。
        show_view(_VIEWS.index(view), ft.Column(
            _paper_view() if view == _BY_PAPER else _topic_view(),
            spacing=theme.SPACE_MD,
        ))
        count_text.value = f"已选 {len(selected)} / {len(records)} 题"
        page.update()

    def _on_view_change(index: int) -> None:
        nonlocal view
        view = _VIEWS[index]
        _rebuild_content()

    toolbar = ft.Row(
        [
            segmented_strip(
                ["按卷", "按 topic"], _on_view_change,
                selected=_VIEWS.index(view),
            ),
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
                tooltip="把所选题目从原卷裁下来，一道大题一页（不含答题横线）；"
                        "每题后面跟一页 mark scheme",
                on_click=_on_export_pdf_click,
                style=theme.filled_button(),
            ),
        ],
        spacing=theme.SPACE_MD,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    _rebuild_content()

    return ft.Column([toolbar, content_area], spacing=theme.SPACE_MD)
