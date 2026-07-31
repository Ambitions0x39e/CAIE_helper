from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

from app_flet.components.widgets import metric_card, success_banner
from core.models import PaperType
from core.settings import GraderConfig
from modules.marking.grader import (
    QuestionResult,
    grade_question,
    parse_grading_result,
)
from modules.marking.mcq_parser import (
    detect_student_answers,
    is_valid_manual_answer,
    score_mcq_answers,
)
from modules.marking.ms_parser import (
    ms_cache_exists,
    parse_mark_scheme,
    resolve_ms_start_page,
)
from modules.marking.page_segmenter import PageClip, segment_questions_report
from modules.marking.renderer import NativeRenderer, page_count, to_pdf_bytes

if TYPE_CHECKING:
    from app_flet.state import AppState

_log = logging.getLogger("cie_helper.mark")


def build_mark_tab(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    ms_picker: ft.FilePicker,
    answer_picker: ft.FilePicker,
    refresh_cb: Callable[[], None] | None = None,
) -> ft.Container:
    content = ft.Column(spacing=12)

    # ── Local UI state ─────────────────────────────────────────────
    ms_source_ref: list[str] = ["downloaded"]
    paper_type_ref: list[PaperType] = [PaperType.MATH]
    # None = auto-detect from the MS PDF; a number is a manual override.
    start_page_ref: list[int | None] = [None]
    selected_syllabus_ref: list[str | None] = [None]
    selected_paper_ref: list[str | None] = [None]
    ms_upload_path_ref: list[str | None] = [None]
    thinking_ref: list[bool] = [
        state.grader_config.enable_thinking
        if state.grader_config
        else False
    ]
    grade_questions_ref: list[list[str]] = [[]]
    grade_questions_seeded: list[bool] = [False]
    page_inputs: dict[str, ft.TextField] = {}
    mcq_manual_inputs: dict[str, ft.TextField] = {}
    manual_answer_values: dict[str, str] = {}
    # While a mark-scheme parse is running, the whole tab collapses to just
    # Step 1 + this progress bar — otherwise re-parsing from the last step
    # would append the bar below the stale question list, buried off-screen.
    parsing_ref: list[bool] = [False]
    parse_bar_ref: list[ft.ProgressBar | None] = [None]
    parse_text_ref: list[ft.Text | None] = [None]

    # ── Rebuild the entire tab ─────────────────────────────────────
    def _sync_page_inputs_to_state() -> None:
        # Step 2 rebuilds fresh TextFields from state.auto_pages on every
        # _rebuild() call — snapshot the user's live edits back into state
        # first so an unrelated rebuild (checkbox toggle, delete question)
        # doesn't wipe out manually typed page numbers.
        for qid, tf in page_inputs.items():
            val = (tf.value or "").strip()
            if val:
                state.auto_pages[qid] = val

    def _rebuild() -> None:
        _sync_page_inputs_to_state()
        content.controls.clear()
        content.controls.extend(_build_step1())
        if parsing_ref[0]:
            # Parsing in progress: show only the progress bar, nothing below.
            if parse_bar_ref[0] is not None:
                content.controls.append(parse_bar_ref[0])
            if parse_text_ref[0] is not None:
                content.controls.append(parse_text_ref[0])
            page.update()
            return
        if state.paper_config and state.paper_type == PaperType.MATH.value:
            content.controls.extend(_build_step2())
            if state.answer_pdf_path and state.auto_pages_done:
                content.controls.extend(_build_step3())
            if state.grading_results:
                content.controls.extend(_build_step4())
        elif state.paper_config and state.paper_type == PaperType.MCQ.value:
            content.controls.extend(_build_mcq_flow())
        page.update()

    def _responsive_grid(
        cells: list[ft.Control],
        cell_width: int,
        spacing: int = 8,
    ) -> list[ft.Control]:
        # Lay the fixed-width cells out in as many columns as the current
        # screen width fits, chunked into explicit Rows. This is deterministic
        # (unlike Row(wrap=True), which collapsed the nested-Row page inputs
        # into a single overlapping column on iPad); the column count tracks
        # page.width so it adapts from phone (2 cols) to iPad Pro (5-7 cols).
        avail = int(page.width or 1024) - 40  # tab Container padding, 20/side
        cols = max(1, (avail + spacing) // (cell_width + spacing))
        return [
            ft.Row(cells[i : i + cols], spacing=spacing)
            for i in range(0, len(cells), cols)
        ]

    # ══════════════════════════════════════════════════════════════
    #  Step 1: Mark Scheme
    # ══════════════════════════════════════════════════════════════
    def _build_step1() -> list[ft.Control]:
        controls: list[ft.Control] = [
            ft.Text(
                "AI 批改", size=24,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
            ft.Divider(),
            ft.Text(
                "Step 1 — 解析 Mark Scheme", size=18,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
        ]

        # Source radio
        source_group = ft.RadioGroup(
            content=ft.Row([
                ft.Radio(
                    value="downloaded", label="从已下载试卷",
                    label_style=ft.TextStyle(color=ft.Colors.BLACK),
                ),
                ft.Radio(
                    value="upload", label="上传 PDF",
                    label_style=ft.TextStyle(color=ft.Colors.BLACK),
                ),
            ]),
            value=ms_source_ref[0],
            on_change=_on_source_change,  # type: ignore[arg-type]
        )
        controls.append(source_group)

        # Paper type radio
        type_group = ft.RadioGroup(
            content=ft.Row([
                ft.Radio(
                    value="mcq", label="MCQ",
                    label_style=ft.TextStyle(color=ft.Colors.BLACK),
                ),
                ft.Radio(
                    value="math", label="Structured / Math",
                    label_style=ft.TextStyle(color=ft.Colors.BLACK),
                ),
            ]),
            value=paper_type_ref[0].value,
            on_change=_on_type_change,  # type: ignore[arg-type]
        )
        controls.append(type_group)

        if ms_source_ref[0] == "downloaded":
            controls.extend(_build_paper_selector())
        else:
            upload_label = (
                ms_upload_path_ref[0].split("\\")[-1].split("/")[-1]
                if ms_upload_path_ref[0]
                else "未选择文件"
            )
            controls.append(ft.Row([
                ft.Button(
                    "选择 MS PDF 文件",
                    icon=ft.Icons.UPLOAD_FILE,
                    on_click=_on_ms_upload_click,  # type: ignore[arg-type]
                ),
                ft.Text(upload_label, size=12, color=ft.Colors.GREY),
            ]))

        # Start page (MATH only)
        if paper_type_ref[0] == PaperType.MATH:
            start_page_field = ft.TextField(
                label="MS 内容起始页",
                label_style=ft.TextStyle(color=ft.Colors.BLACK),
                value=(
                    "" if start_page_ref[0] is None
                    else str(start_page_ref[0])
                ),
                hint_text="自动",
                keyboard_type=ft.KeyboardType.NUMBER,
                width=200,
                color=ft.Colors.BLACK,
                helper=ft.Text(
                    "默认留空，自动检测",
                    size=11, color=ft.Colors.GREY,
                ),
                on_change=_on_start_page_change,  # type: ignore[arg-type]
            )
            controls.append(start_page_field)

        # Warning if MATH but no grader configured
        if (
            paper_type_ref[0] == PaperType.MATH
            and state.grader_config is None
        ):
            controls.append(ft.Container(
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE),
                    ft.Text(
                        "请先在设置中配置 Grader API 凭证",
                        color=ft.Colors.ORANGE,
                    ),
                ]),
                padding=8,
            ))

        # Parse button (+ cached-result hint on the same row, far right)
        can_parse = (
            not parsing_ref[0]
            and _get_ms_path() is not None
            and (
                paper_type_ref[0] == PaperType.MCQ
                or state.grader_config is not None
            )
        )
        parse_row: list[ft.Control] = [ft.Button(
            "解析 Mark Scheme",
            icon=ft.Icons.SEARCH,
            disabled=not can_parse,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
            ),
            on_click=_on_parse_click,  # type: ignore[arg-type]
        )]
        if state.paper_config and state.ms_from_cache:
            parse_row.append(ft.Container(
                ft.Row([
                    ft.Icon(
                        ft.Icons.HISTORY,
                        color=ft.Colors.AMBER_800, size=16,
                    ),
                    ft.Text(
                        "此结果来自缓存",
                        size=12, color=ft.Colors.BLACK,
                    ),
                    ft.TextButton(
                        "重新解析",
                        disabled=not can_parse,
                        on_click=_on_reparse_click,  # type: ignore[arg-type]
                    ),
                ], spacing=6, tight=True),
                bgcolor=ft.Colors.AMBER_100,
                border_radius=8,
                padding=ft.Padding(left=10, right=4, top=2, bottom=2),
            ))
        controls.append(ft.Row(
            parse_row,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ))

        # Parsed config preview (hidden while a new parse is running)
        if state.paper_config and not parsing_ref[0]:
            pc = state.paper_config
            q_controls: list[ft.Control] = []
            for qid, qcfg in pc.questions.items():
                q_controls.append(ft.Text(
                    f"{qid} — {qcfg.max_marks} marks",
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLACK, size=13,
                ))
                q_controls.append(ft.Text(
                    qcfg.mark_scheme, size=12, color=ft.Colors.GREY,
                ))

            controls.append(ft.ExpansionTile(
                title=ft.Text(
                    f"已解析: {pc.paper_id}"
                    f" ({len(pc.questions)} 题)",
                    color=ft.Colors.BLACK,
                ),
                controls=[ft.Container(
                    ft.Column(q_controls, spacing=4), padding=12,
                )],
            ))

        return controls

    def _build_paper_selector() -> list[ft.Control]:
        try:
            all_records = state.store.load_all()
        except ValueError:
            all_records = []
        ms_records = [r for r in all_records if r.ms_path]
        if not ms_records:
            return [ft.Text(
                "没有包含 Mark Scheme 的已下载试卷。请先下载或直接上传。",
                color=ft.Colors.GREY, size=13,
            )]

        syllabus_codes = sorted(
            {r.paper_id.split("_")[0] for r in ms_records}
        )

        if selected_syllabus_ref[0] not in syllabus_codes and syllabus_codes:
            selected_syllabus_ref[0] = syllabus_codes[0]
        sel_syl = selected_syllabus_ref[0] or ""

        filtered = sorted(
            [
                r for r in ms_records
                if r.paper_id.startswith(f"{sel_syl}_")
            ],
            key=lambda r: r.paper_id,
        )
        filtered_ids = [r.paper_id for r in filtered]
        if selected_paper_ref[0] not in filtered_ids and filtered_ids:
            selected_paper_ref[0] = filtered_ids[0]

        syllabus_dd = ft.Dropdown(
            label="科目代码",
            label_style=ft.TextStyle(color=ft.Colors.BLACK),
            options=[
                ft.dropdown.Option(code) for code in syllabus_codes
            ],
            value=selected_syllabus_ref[0],
            width=160,
            color=ft.Colors.BLACK,
            on_select=_on_syllabus_select,  # type: ignore[arg-type]
        )
        paper_dd = ft.Dropdown(
            label="选择试卷",
            label_style=ft.TextStyle(color=ft.Colors.BLACK),
            options=[
                ft.dropdown.Option(pid) for pid in filtered_ids
            ],
            value=selected_paper_ref[0],
            expand=True,
            color=ft.Colors.BLACK,
            on_select=_on_paper_select,  # type: ignore[arg-type]
        )

        return [ft.Row([syllabus_dd, paper_dd], spacing=12)]

    def _get_ms_path() -> str | None:
        if ms_source_ref[0] == "upload":
            return ms_upload_path_ref[0]
        if selected_paper_ref[0] is None:
            return None
        try:
            records = state.store.load_all()
        except ValueError:
            return None
        target = next(
            (r for r in records if r.paper_id == selected_paper_ref[0]),
            None,
        )
        return target.ms_path if target else None

    # ── Step 1 event handlers ──────────────────────────────────────
    def _on_source_change(
        e: ft.ControlEvent,  # noqa: ARG001
    ) -> None:
        ms_source_ref[0] = str(e.data)
        _rebuild()

    def _on_type_change(
        e: ft.ControlEvent,  # noqa: ARG001
    ) -> None:
        val = str(e.data)
        paper_type_ref[0] = (
            PaperType.MCQ if val == "mcq" else PaperType.MATH
        )
        _rebuild()

    def _on_start_page_change(
        e: ft.ControlEvent,  # noqa: ARG001
    ) -> None:
        raw = str(e.data or "").strip()
        if not raw:
            start_page_ref[0] = None  # blank → auto-detect
            return
        try:
            start_page_ref[0] = int(raw)
        except ValueError:
            start_page_ref[0] = None

    def _on_syllabus_select(
        e: ft.ControlEvent,  # noqa: ARG001
    ) -> None:
        selected_syllabus_ref[0] = str(e.data) if e.data else None
        selected_paper_ref[0] = None
        _rebuild()

    def _on_paper_select(
        e: ft.ControlEvent,  # noqa: ARG001
    ) -> None:
        selected_paper_ref[0] = str(e.data) if e.data else None
        _rebuild()

    async def _on_ms_upload_click(
        _: ft.ControlEvent,
    ) -> None:
        files = await ms_picker.pick_files(
            allowed_extensions=["pdf"],
            dialog_title="选择 Mark Scheme PDF",
        )
        if files and files[0].path:
            ms_upload_path_ref[0] = files[0].path
            _rebuild()

    def _start_parse(force: bool) -> None:
        ms_path = _get_ms_path()
        if not ms_path:
            show_snack("请先选择 Mark Scheme 文件", ft.Colors.RED)
            return

        pt = paper_type_ref[0]

        progress_bar = ft.ProgressBar(visible=True)
        progress_text = ft.Text(
            "正在解析 Mark Scheme…", size=12, color=ft.Colors.GREY,
        )
        # Collapse the tab to Step 1 + this bar so a re-parse from the last
        # step doesn't bury the bar under the previous question list.
        parse_bar_ref[0] = progress_bar
        parse_text_ref[0] = progress_text
        parsing_ref[0] = True
        _rebuild()

        def _do_parse() -> None:
            try:
                def _on_progress(batch: int, total: int) -> None:
                    progress_bar.value = batch / total
                    progress_text.value = (
                        f"处理第 {batch}/{total} 批…"
                    )
                    page.update()

                # Resolve the start page once up front (MCQ ignores it):
                # both the cache-hit check and the parse itself need it,
                # and passing the resolved number to parse_mark_scheme
                # avoids running the page-detection scan a second time.
                resolved_start = (
                    resolve_ms_start_page(ms_path, start_page_ref[0])
                    if pt == PaperType.MATH else None
                )
                from_cache = not force and ms_cache_exists(
                    ms_path, pt, resolved_start,
                )
                pc = parse_mark_scheme(
                    ms_path,
                    paper_type=pt,
                    grader_config=state.grader_config,
                    start_page=resolved_start,
                    on_progress=_on_progress,
                    renderer=NativeRenderer(
                        state.pdf_renderer, page.session.connection.loop,
                    ),
                    force=force,
                )
                state.paper_config = pc
                state.ms_from_cache = from_cache
                state.paper_type = pt.value
                state.deleted_questions.clear()
                state.grading_results.clear()
                state.score_overrides.clear()
                state.grading_confirmed = False
                state.answer_pdf_path = None
                state.auto_pages_done = False
                state.auto_pages.clear()
                state.auto_clips.clear()
                grade_questions_ref[0] = []
                grade_questions_seeded[0] = False
                show_snack(
                    f"已解析 {pc.paper_id} — "
                    f"共 {len(pc.questions)} 题, "
                    f"总分为 {pc.total_marks}",
                    ft.Colors.GREEN,
                )
            except Exception as exc:
                show_snack(f"解析失败: {exc}", ft.Colors.RED)
            finally:
                parsing_ref[0] = False
                parse_bar_ref[0] = None
                parse_text_ref[0] = None
                _rebuild()

        page.run_thread(_do_parse)

    def _on_parse_click(_: ft.ControlEvent) -> None:
        _start_parse(force=False)

    def _on_reparse_click(_: ft.ControlEvent) -> None:
        _start_parse(force=True)

    # ══════════════════════════════════════════════════════════════
    #  Step 2: Answer Paper + Segmentation
    # ══════════════════════════════════════════════════════════════
    def _build_step2() -> list[ft.Control]:
        controls: list[ft.Control] = [
            ft.Divider(),
            ft.Text(
                "Step 2 — 上传答卷", size=18,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
        ]

        upload_label = "未选择文件"
        if state.answer_pdf_path:
            name = (
                state.answer_pdf_path
                .replace("\\", "/").split("/")[-1]
            )
            upload_label = name

        controls.append(ft.Row([
            ft.Button(
                "选择答卷 PDF",
                icon=ft.Icons.UPLOAD_FILE,
                on_click=_on_answer_upload_click,  # type: ignore[arg-type]
            ),
            ft.Text(upload_label, size=12, color=ft.Colors.GREY),
        ]))

        if not state.answer_pdf_path:
            return controls

        if not state.auto_pages_done:
            controls.append(ft.Row([
                ft.ProgressRing(width=20, height=20, stroke_width=2),
                ft.Text(
                    "正在解析 QP…",
                    size=12, color=ft.Colors.GREY,
                ),
            ], spacing=8))
            return controls

        # Segmentation info
        matched_count = len(state.auto_pages)
        total_q = (
            len(state.paper_config.questions)
            if state.paper_config
            else 0
        )
        info_parts = [
            f"PDF 共 {state.answer_total_pages} 页",
            f"自动识别 {matched_count}/{total_q} 题",
        ]
        # Partial detection is the common failure, not an edge case — warn
        # on any shortfall rather than only when nothing at all was found.
        incomplete = matched_count < total_q
        controls.append(ft.Container(
            ft.Row([
                ft.Icon(
                    ft.Icons.WARNING if incomplete else ft.Icons.INFO,
                    color=ft.Colors.ORANGE if incomplete else ft.Colors.BLUE,
                    size=18,
                ),
                ft.Text(
                    " | ".join(info_parts),
                    color=ft.Colors.BLACK, size=13,
                ),
            ]),
            bgcolor=ft.Colors.ORANGE_50 if incomplete else ft.Colors.BLUE_50,
            border_radius=8, padding=12,
        ))
        if incomplete:
            missing = state.unmatched_questions
            preview = "、".join(missing[:8])
            if len(missing) > 8:
                preview += f" 等 {len(missing)} 题"
            controls.append(ft.Text(
                f"未自动识别：{preview}。"
                "请在下方为这些题手动输入页码（例如 2 或 2,3）。",
                color=ft.Colors.ORANGE, size=12,
            ))

        # Page assignment per question
        controls.append(ft.Text(
            "为每题指定页码:", size=14,
            weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
        ))

        pc = state.paper_config
        if pc is None:
            return controls

        q_items = [
            (qid, qcfg)
            for qid, qcfg in pc.questions.items()
            if qid not in state.deleted_questions
        ]

        page_inputs.clear()
        cells: list[ft.Control] = []
        for qid, qcfg in q_items:
            default_val = state.auto_pages.get(qid, "")
            # An empty box here means detection failed for this question —
            # colour it so it reads as "type a page number", not as a glitch.
            needs_input = not default_val
            tf = ft.TextField(
                label=f"{qid} ({qcfg.max_marks}m)",
                label_style=ft.TextStyle(
                    color=ft.Colors.ORANGE_800 if needs_input else ft.Colors.BLACK,
                ),
                value=default_val,
                hint_text="待填" if needs_input else "例: 2,3",
                border_color=ft.Colors.ORANGE if needs_input else None,
                expand=True,
                color=ft.Colors.BLACK,
                dense=True,
            )
            page_inputs[qid] = tf

            def _make_del_handler(q: str = qid) -> Callable[..., None]:
                def _handler(_: ft.ControlEvent) -> None:
                    state.deleted_questions.add(q)
                    _rebuild()
                return _handler

            # Fixed-width cell so the responsive grid can compute columns; the
            # TextField expands to fill it, leaving room for the delete button.
            cells.append(ft.Container(
                ft.Row([
                    tf,
                    ft.IconButton(
                        ft.Icons.CLOSE, tooltip=f"移除 {qid}",
                        icon_size=18, on_click=_make_del_handler(),
                    ),
                ], spacing=0),
                width=158,  # TextField + IconButton (~48)
            ))

        # Dynamic columns-per-row based on the live screen width.
        controls.extend(_responsive_grid(cells, 158))

        return controls

    # ── Step 2 event handlers ──────────────────────────────────────
    async def _on_answer_upload_click(
        _: ft.ControlEvent,
    ) -> None:
        files = await answer_picker.pick_files(
            allowed_extensions=["pdf"],
            dialog_title="选择答卷 PDF (GoodNotes 导出)",
        )
        if not files or not files[0].path:
            return

        path = files[0].path
        state.answer_pdf_path = path
        state.auto_pages_done = False
        state.auto_pages.clear()
        state.auto_clips.clear()
        state.grading_results.clear()
        state.score_overrides.clear()
        state.grading_confirmed = False
        _rebuild()

        def _do_segment() -> None:
            try:
                pc = state.paper_config
                if pc is None:
                    return
                # Page count + segmentation both pdfminer-backed (iOS-safe).
                state.answer_total_pages = page_count(path)
                q_ids = list(pc.questions.keys())
                regions, report = segment_questions_report(path, q_ids)
                auto_pages: dict[str, str] = {}
                auto_clips: dict[str, list[PageClip]] = {}
                for r in regions:
                    page_nums = sorted(
                        {c.page_idx + 1 for c in r.clips}
                    )
                    if not page_nums:
                        continue  # never store a phantom (blank) entry
                    auto_pages[r.question_id] = ",".join(
                        str(p) for p in page_nums
                    )
                    auto_clips[r.question_id] = r.clips
                state.auto_pages = auto_pages
                state.auto_clips = auto_clips
                state.unmatched_questions = report.unmatched
                state.auto_pages_done = True
                _rebuild()
            except Exception as exc:
                show_snack(
                    f"答卷分析失败: {exc}", ft.Colors.RED,
                )
                state.auto_pages_done = True
                _rebuild()

        page.run_thread(_do_segment)

    # ══════════════════════════════════════════════════════════════
    #  Step 3: Grade
    # ══════════════════════════════════════════════════════════════
    def _build_step3() -> list[ft.Control]:
        controls: list[ft.Control] = [
            ft.Divider(),
            ft.Text(
                "Step 3 — 批改", size=18,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
        ]

        # Persistent failure banner — a grade that stalls/errors on one
        # question would otherwise only flash a toast and vanish.
        if state.grading_error:
            controls.append(ft.Container(
                ft.Row([
                    ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED, size=18),
                    ft.Text(
                        state.grading_error,
                        color=ft.Colors.RED, size=13, expand=True,
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=8),
                bgcolor=ft.Colors.RED_50, border_radius=8, padding=12,
            ))

        if state.grader_config is None:
            controls.append(ft.Container(
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE),
                    ft.Text(
                        "请先在设置中配置 Grader API 凭证",
                        color=ft.Colors.ORANGE,
                    ),
                ]),
                padding=8,
            ))
            return controls

        # Thinking mode toggle
        thinking_switch = ft.Switch(
            label="启用思考模式 (更慢但更准确)",
            label_text_style=ft.TextStyle(color=ft.Colors.BLACK),
            value=thinking_ref[0],
            on_change=_on_thinking_change,  # type: ignore[arg-type]
        )
        controls.append(thinking_switch)

        # Question checkboxes
        pc = state.paper_config
        if pc is None:
            return controls

        available_qs = [
            qid for qid in pc.questions
            if qid not in state.deleted_questions
        ]
        if not grade_questions_seeded[0]:
            grade_questions_seeded[0] = True
            grade_questions_ref[0] = list(
                _collect_page_assignments().keys()
            )

        controls.append(ft.Row(
            [
                ft.Text(
                    "选择要批改的题目:", size=13, color=ft.Colors.BLACK,
                ),
                ft.Container(expand=True),
                ft.TextButton(
                    "全选", on_click=_on_select_all_click,  # type: ignore[arg-type]
                ),
                ft.TextButton(
                    "全不选", on_click=_on_select_none_click,  # type: ignore[arg-type]
                ),
            ],
        ))

        q_checks: list[ft.Control] = []
        for qid in available_qs:
            q_checks.append(ft.Container(
                ft.Checkbox(
                    label=qid,
                    label_style=ft.TextStyle(
                        color=ft.Colors.BLACK, size=13,
                    ),
                    value=qid in grade_questions_ref[0],
                    on_change=_make_q_check_handler(qid),
                ),
                width=130,
            ))
        # Dynamic columns-per-row based on the live screen width.
        controls.extend(_responsive_grid(q_checks, 130))

        # Validation
        assignments = _collect_page_assignments()
        selected = grade_questions_ref[0]
        missing = [q for q in selected if q not in assignments]
        if not selected:
            controls.append(ft.Text(
                "请至少勾选一个题目进行批改。",
                color=ft.Colors.ORANGE, size=12,
            ))
        elif missing:
            controls.append(ft.Text(
                f"请为以下题目指定页码: {', '.join(missing)}",
                color=ft.Colors.ORANGE, size=12,
            ))

        can_grade = (
            bool(selected) and not missing
            and not state.grading_in_progress
        )
        controls.append(ft.Button(
            "开始批改",
            icon=ft.Icons.ROCKET_LAUNCH,
            disabled=not can_grade,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
            ),
            on_click=_on_grade_click,  # type: ignore[arg-type]
        ))

        return controls

    # ── Step 3 event handlers ──────────────────────────────────────
    def _on_thinking_change(
        e: ft.ControlEvent,  # noqa: ARG001
    ) -> None:
        thinking_ref[0] = str(e.data).lower() == "true"

    def _make_q_check_handler(
        qid: str,
    ) -> Callable[..., None]:
        def _handler(
            e: ft.ControlEvent,  # noqa: ARG001
        ) -> None:
            checked = str(e.data).lower() == "true"
            if checked and qid not in grade_questions_ref[0]:
                grade_questions_ref[0].append(qid)
            elif not checked and qid in grade_questions_ref[0]:
                grade_questions_ref[0].remove(qid)
            _rebuild()
        return _handler

    def _on_select_all_click(_: ft.ControlEvent) -> None:
        pc = state.paper_config
        if pc is None:
            return
        grade_questions_ref[0] = [
            qid for qid in pc.questions
            if qid not in state.deleted_questions
        ]
        _rebuild()

    def _on_select_none_click(_: ft.ControlEvent) -> None:
        grade_questions_ref[0] = []
        _rebuild()

    def _collect_page_assignments() -> dict[str, list[int]]:
        assignments: dict[str, list[int]] = {}
        for qid, tf in page_inputs.items():
            val = (tf.value or "").strip()
            if val:
                try:
                    pages = [
                        int(p.strip())
                        for p in val.split(",") if p.strip()
                    ]
                    assignments[qid] = pages
                except ValueError:
                    pass
        return assignments

    def _on_grade_click(_: ft.ControlEvent) -> None:
        if state.grading_in_progress:
            show_snack("已有批改请求进行中，请等待完成", ft.Colors.ORANGE)
            return
        gc = state.grader_config
        if gc is None:
            return
        pc = state.paper_config
        if pc is None:
            return

        assignments = _collect_page_assignments()
        questions_to_grade = [
            q for q in grade_questions_ref[0] if q in assignments
        ]
        if not questions_to_grade:
            show_snack("没有可批改的题目", ft.Colors.ORANGE)
            return

        grade_cfg = GraderConfig(
            api_key=gc.api_key.get_secret_value(),
            base_url=gc.base_url,
            model=gc.model,
            dpi=gc.dpi,
            enable_thinking=thinking_ref[0],
        )

        state.grading_error = None  # clear any prior failure banner
        progress_bar = ft.ProgressBar(value=0, visible=True)
        progress_text = ft.Text(
            "正在批改…", size=12, color=ft.Colors.GREY,
        )
        content.controls.append(ft.Divider())
        content.controls.append(progress_bar)
        content.controls.append(progress_text)
        page.update()

        def _do_grade() -> None:
            results: list[QuestionResult] = []
            total_score = 0
            total_max = 0
            qid = "?"  # set in the loop; guards the except before it starts

            try:
                renderer = NativeRenderer(
                    state.pdf_renderer, page.session.connection.loop,
                )
                pdf_bytes = to_pdf_bytes(state.answer_pdf_path)  # type: ignore[arg-type]
                for i, qid in enumerate(questions_to_grade):
                    progress_bar.value = (
                        i / len(questions_to_grade)
                    )
                    progress_text.value = f"正在批改 {qid}…"
                    page.update()

                    qcfg = pc.questions[qid]
                    q_pages = assignments[qid]
                    clips_for_q = state.auto_clips.get(qid)

                    if clips_for_q:
                        images = renderer.render_regions(
                            pdf_bytes, clips_for_q, dpi=grade_cfg.dpi,
                        )
                    else:
                        images = renderer.render_pages(
                            pdf_bytes, q_pages, dpi=grade_cfg.dpi,
                        )

                    raw = grade_question(
                        config=grade_cfg,
                        images=images,
                        question_id=qid,
                        mark_scheme=qcfg.mark_scheme,
                        max_marks=qcfg.max_marks,
                        paper_type=PaperType(
                            state.paper_type or "math"
                        ),
                    )
                    qr = parse_grading_result(raw)
                    results.append(qr)
                    total_score += qr.total
                    total_max += qr.max

                progress_bar.value = 1.0
                progress_text.value = "批改完成!"
                page.update()

                state.grading_results = results  # type: ignore[assignment]
                state.score_overrides = {
                    r.question: r.total for r in results
                }
                state.grading_confirmed = False

            except Exception as exc:
                # Log the full traceback (a toast auto-dismisses and the
                # stack is what pins down a render/API stall) and keep the
                # message on screen as a banner until the next grade.
                _log.exception("grading failed on question %s", qid)
                state.grading_error = f"批改失败（{qid}）: {exc}"
                show_snack(f"批改失败: {exc}", ft.Colors.RED)
            finally:
                state.grading_in_progress = False
                _rebuild()

        state.grading_in_progress = True
        page.run_thread(_do_grade)

    # ══════════════════════════════════════════════════════════════
    #  Step 4: Results & Confirm
    # ══════════════════════════════════════════════════════════════
    def _build_step4() -> list[ft.Control]:
        results: list[QuestionResult] = (
            state.grading_results  # type: ignore[assignment]
        )
        if not results:
            return []

        controls: list[ft.Control] = [
            ft.Divider(),
            ft.Text(
                "批改结果", size=18,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
        ]

        overrides = state.score_overrides
        score = sum(
            overrides.get(r.question, r.total) for r in results
        )
        max_score = sum(r.max for r in results)
        pct = (score / max_score * 100) if max_score > 0 else 0

        controls.append(ft.Row(
            [
                metric_card(
                    "总分", f"{score}/{max_score}", ft.Colors.BLUE,
                ),
                metric_card(
                    "百分比", f"{pct:.1f}%", ft.Colors.GREEN,
                ),
                metric_card(
                    "题数", str(len(results)), ft.Colors.PURPLE,
                ),
            ],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        ))

        # Per-question results
        for qr in results:
            ov = overrides.get(qr.question, qr.total)
            mark_controls: list[ft.Control] = [
                ft.Text(
                    f"{qr.question} — {ov}/{qr.max}",
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLACK, size=15,
                ),
            ]
            for m in qr.marks:
                icon = (
                    ft.Icons.CHECK_CIRCLE
                    if m.awarded
                    else ft.Icons.CANCEL
                )
                color = (
                    ft.Colors.GREEN if m.awarded else ft.Colors.RED
                )
                mark_controls.append(ft.Row(
                    [
                        ft.Icon(icon, color=color, size=18),
                        ft.Text(
                            f"{m.code}: {m.reason}",
                            color=ft.Colors.BLACK, size=13,
                            expand=True,  # wrap long reasons, don't overflow
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ))

            if qr.comment:
                mark_controls.append(ft.Container(
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.CHAT_BUBBLE,
                                color=ft.Colors.BLUE, size=16,
                            ),
                            ft.Text(
                                qr.comment,
                                color=ft.Colors.GREY, size=12,
                                expand=True,  # wrap long comments
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    padding=ft.Padding(
                        left=0, right=0, top=4, bottom=0,
                    ),
                ))

            def _make_override_handler(
                q: str = qr.question,
            ) -> Callable[..., None]:
                def _handler(
                    e: ft.ControlEvent,  # noqa: ARG001
                ) -> None:
                    try:
                        val = int(e.data or 0)
                        state.score_overrides[q] = val
                        _rebuild()
                    except ValueError:
                        pass
                return _handler

            adj_field = ft.TextField(
                label="调分", value=str(ov), width=90,
                label_style=ft.TextStyle(color=ft.Colors.BLACK),
                keyboard_type=ft.KeyboardType.NUMBER,
                color=ft.Colors.BLACK, dense=True,
                on_submit=_make_override_handler(),
                on_blur=_make_override_handler(),
            )

            panel = ft.Container(
                ft.Row(
                    [
                        ft.Container(
                            ft.Column(mark_controls, spacing=4),
                            expand=4,
                        ),
                        ft.VerticalDivider(width=1),
                        ft.Container(
                            adj_field,
                            expand=1,
                            alignment=ft.Alignment(0, 0),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=12,
                ),
                padding=12,
                border=ft.Border.all(1, ft.Colors.GREY_300),
                border_radius=8,
            )
            controls.append(panel)

        # Confirm & Log
        if state.grading_confirmed:
            controls.append(success_banner("分数已记录"))
        else:
            controls.append(ft.Text(
                "检查上方结果，确认后记录分数。",
                size=12, color=ft.Colors.GREY,
            ))
            controls.append(ft.Button(
                "确认并记录分数",
                icon=ft.Icons.CHECK,
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.GREEN,
                    color=ft.Colors.WHITE,
                ),
                on_click=_on_confirm_click,  # type: ignore[arg-type]
            ))

        return controls

    # ── Step 4 event handler ───────────────────────────────────────
    def _on_confirm_click(_: ft.ControlEvent) -> None:
        results: list[QuestionResult] = (
            state.grading_results  # type: ignore[assignment]
        )
        if not results:
            return

        overrides = state.score_overrides
        score = sum(
            overrides.get(r.question, r.total) for r in results
        )
        max_score = sum(r.max for r in results)

        try:
            records = state.store.load_all()
            paper_id_match = (
                selected_paper_ref[0]
                if ms_source_ref[0] == "downloaded"
                else None
            )

            if paper_id_match:
                target = next(
                    (
                        r for r in records
                        if r.paper_id == paper_id_match
                    ),
                    None,
                )
                if target:
                    updated = target.model_copy(update={
                        "score_raw": float(score),
                        "score_total": float(max_score),
                        "status": "Completed",
                    })
                    state.store.update(updated)
                    state.grading_confirmed = True
                    show_snack(
                        f"已记录 {score}/{max_score}"
                        f" → {paper_id_match}",
                        ft.Colors.GREEN,
                    )
                else:
                    show_snack(
                        "未找到匹配的试卷记录",
                        ft.Colors.ORANGE,
                    )
            else:
                pct = (
                    score / max_score * 100
                ) if max_score > 0 else 0
                show_snack(
                    f"分数: {score}/{max_score} ({pct:.1f}%)"
                    " — 使用管理页面手动记录",
                    ft.Colors.AMBER,
                )
                state.grading_confirmed = True
        except Exception as exc:
            show_snack(f"记录失败: {exc}", ft.Colors.RED)

        _rebuild()

    # ══════════════════════════════════════════════════════════════
    #  MCQ flow — upload, detect, manual override, score, confirm
    # ══════════════════════════════════════════════════════════════
    def _build_mcq_flow() -> list[ft.Control]:
        pc = state.paper_config
        if pc is None:
            return []

        controls: list[ft.Control] = [
            ft.Divider(),
            ft.Text(
                "Step 2 — 上传已批注 QP", size=18,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ),
            ft.Text(
                "上传在 GoodNotes 中批注过的试卷"
                "（圈出/写出每题答案）。",
                size=13, color=ft.Colors.GREY,
            ),
        ]

        if state.grader_config is None:
            controls.append(ft.Container(
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE),
                    ft.Text(
                        "请先在设置中配置 Grader API 凭证以启用自动检测",
                        color=ft.Colors.ORANGE,
                    ),
                ]),
                padding=8,
            ))

        upload_label = (
            state.mcq_qp_filename or "未选择文件"
        )
        controls.append(ft.Row([
            ft.Button(
                "选择已批注 QP PDF",
                icon=ft.Icons.UPLOAD_FILE,
                on_click=_on_mcq_upload_click,  # type: ignore[arg-type]
            ),
            ft.Text(upload_label, size=12, color=ft.Colors.GREY),
        ]))

        if not state.mcq_qp_path:
            return controls

        controls.append(ft.Divider())
        controls.append(ft.Text(
            "Step 3 — 检测与批改", size=18,
            weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
        ))
        controls.append(ft.Button(
            "检测答案",
            icon=ft.Icons.SEARCH,
            disabled=(
                state.grader_config is None
                or state.grading_in_progress
            ),
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
            ),
            on_click=_on_detect_click,  # type: ignore[arg-type]
        ))

        if state.mcq_undetected:
            controls.append(ft.Text(
                f"未能检测到 {len(state.mcq_undetected)} 题: "
                f"{', '.join(state.mcq_undetected)}。请在下方手动填写。",
                color=ft.Colors.ORANGE, size=12,
            ))

            controls.append(ft.Text(
                "手动填写未检测题目:", size=13,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ))
            mcq_manual_inputs.clear()
            manual_fields: list[ft.Control] = []
            for qid in state.mcq_undetected:
                tf = ft.TextField(
                    label=qid[1:],
                    label_style=ft.TextStyle(color=ft.Colors.BLACK),
                    value=manual_answer_values.get(qid, ""),
                    max_length=1,
                    width=70,
                    color=ft.Colors.BLACK,
                    dense=True,
                    text_align=ft.TextAlign.CENTER,
                    on_change=_make_manual_change_handler(qid),
                )
                mcq_manual_inputs[qid] = tf
                manual_fields.append(tf)
            controls.append(ft.Row(manual_fields, wrap=True, spacing=8))

        merged_answers = _collect_mcq_answers()
        if merged_answers:
            controls.append(ft.Divider())
            score, total, per_q = score_mcq_answers(pc, merged_answers)
            pct = (score / total * 100) if total > 0 else 0

            controls.append(ft.Row(
                [
                    metric_card("得分", f"{score}/{total}", ft.Colors.BLUE),
                    metric_card(
                        "百分比", f"{pct:.1f}%", ft.Colors.GREEN,
                    ),
                    metric_card(
                        "已检测", str(len(merged_answers)), ft.Colors.PURPLE,
                    ),
                ],
                spacing=12, scroll=ft.ScrollMode.AUTO,
            ))

            controls.append(ft.Text(
                "逐题结果:", size=13,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK,
            ))
            q_cards: list[ft.Control] = []
            for qid in pc.questions:
                correct_ans = pc.questions[qid].mark_scheme
                student_ans = merged_answers.get(qid, "–")
                is_correct = per_q.get(qid, False)
                if qid in merged_answers:
                    icon = (
                        ft.Icons.CHECK_CIRCLE
                        if is_correct
                        else ft.Icons.CANCEL
                    )
                    icon_color = (
                        ft.Colors.GREEN if is_correct else ft.Colors.RED
                    )
                else:
                    icon = ft.Icons.REMOVE
                    icon_color = ft.Colors.GREY
                q_cards.append(ft.Container(
                    ft.Column([
                        ft.Text(
                            qid[1:], weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLACK, size=13,
                        ),
                        ft.Icon(icon, color=icon_color, size=16),
                        ft.Text(
                            student_ans, color=ft.Colors.BLACK, size=12,
                        ),
                        ft.Text(
                            correct_ans, color=ft.Colors.GREY, size=11,
                        ),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    width=60, padding=6,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=6,
                ))
            controls.append(ft.Row(q_cards, wrap=True, spacing=6))

            controls.append(ft.Divider())
            if state.mcq_confirmed:
                controls.append(success_banner("分数已记录"))
            else:
                controls.append(ft.Text(
                    "检查上方结果，确认后记录分数。",
                    size=12, color=ft.Colors.GREY,
                ))
                controls.append(ft.Button(
                    "确认并记录分数",
                    icon=ft.Icons.CHECK,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN, color=ft.Colors.WHITE,
                    ),
                    on_click=_on_mcq_confirm_click,  # type: ignore[arg-type]
                ))

        return controls

    def _collect_mcq_answers() -> dict[str, str]:
        merged = dict(state.mcq_detected)
        for qid, val in manual_answer_values.items():
            if is_valid_manual_answer(val):
                merged[qid] = val
        return merged

    def _make_manual_change_handler(
        qid: str,
    ) -> Callable[..., None]:
        def _handler(e: ft.ControlEvent) -> None:
            manual_answer_values[qid] = str(e.data or "").strip().upper()
            _rebuild()
        return _handler

    async def _on_mcq_upload_click(
        _: ft.ControlEvent,
    ) -> None:
        files = await answer_picker.pick_files(
            allowed_extensions=["pdf"],
            dialog_title="选择已批注 QP PDF",
        )
        if not files or not files[0].path:
            return

        state.mcq_qp_path = files[0].path
        state.mcq_qp_filename = files[0].path.replace(
            "\\", "/",
        ).split("/")[-1]
        state.mcq_detected = {}
        state.mcq_undetected = []
        state.mcq_confirmed = False
        manual_answer_values.clear()
        _rebuild()

    def _on_detect_click(_: ft.ControlEvent) -> None:
        if state.grading_in_progress:
            show_snack("已有批改请求进行中，请等待完成", ft.Colors.ORANGE)
            return
        gc = state.grader_config
        pc = state.paper_config
        if gc is None or pc is None or state.mcq_qp_path is None:
            return

        progress_bar = ft.ProgressBar(value=0, visible=True)
        progress_text = ft.Text(
            "正在检测答案…", size=12, color=ft.Colors.GREY,
        )
        content.controls.append(progress_bar)
        content.controls.append(progress_text)
        page.update()

        def _do_detect() -> None:
            def _on_progress(cur: int, tot: int) -> None:
                progress_bar.value = cur / tot
                progress_text.value = f"第 {cur}/{tot} 页…"
                page.update()

            try:
                renderer = NativeRenderer(
                    state.pdf_renderer, page.session.connection.loop,
                )
                detected, undetected = detect_student_answers(
                    state.mcq_qp_path,  # type: ignore[arg-type]
                    pc,
                    gc,
                    renderer,
                    on_progress=_on_progress,
                    source_filename=state.mcq_qp_filename,
                )
                state.mcq_detected = detected
                state.mcq_undetected = undetected
                manual_answer_values.clear()
            except Exception as exc:
                show_snack(f"检测失败: {exc}", ft.Colors.RED)
            finally:
                state.grading_in_progress = False
                _rebuild()

        state.grading_in_progress = True
        page.run_thread(_do_detect)

    def _on_mcq_confirm_click(_: ft.ControlEvent) -> None:
        pc = state.paper_config
        if pc is None:
            return

        merged = _collect_mcq_answers()
        score, total, _per_q = score_mcq_answers(pc, merged)
        pct = (score / total * 100) if total > 0 else 0

        try:
            paper_id_match = (
                selected_paper_ref[0]
                if ms_source_ref[0] == "downloaded"
                else None
            )
            if paper_id_match:
                records = state.store.load_all()
                target = next(
                    (
                        r for r in records
                        if r.paper_id == paper_id_match
                    ),
                    None,
                )
                if target:
                    updated = target.model_copy(update={
                        "score_raw": float(score),
                        "score_total": float(total),
                        "status": "Completed",
                    })
                    state.store.update(updated)
                    state.mcq_confirmed = True
                    show_snack(
                        f"已记录 {score}/{total} ({pct:.1f}%)"
                        f" → {paper_id_match}",
                        ft.Colors.GREEN,
                    )
                else:
                    show_snack("未找到匹配的试卷记录", ft.Colors.ORANGE)
            else:
                show_snack(
                    f"分数: {score}/{total} ({pct:.1f}%)"
                    " — 使用管理页面手动记录",
                    ft.Colors.AMBER,
                )
                state.mcq_confirmed = True
        except Exception as exc:
            show_snack(f"记录失败: {exc}", ft.Colors.RED)

        _rebuild()

    # ── Initial build ──────────────────────────────────────────────
    _rebuild()

    return ft.Container(content, padding=20)
