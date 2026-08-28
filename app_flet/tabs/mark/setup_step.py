"""Step 1 — pick the mark scheme and the answer paper, then analyse both.

The two halves run concurrently: parsing the mark scheme is dominated by
grader-API round trips, while scanning the answer PDF is pdfminer work, so
they overlap for real despite the GIL (measured ~1.9x on a 24-page paper).
The scan can start before the question ids are known because
:func:`~modules.marking.page_segmenter.scan_document` needs only the PDF —
the ids first matter in ``match_scanned``, which runs once both are done.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

import flet as ft

from app_flet import theme
from app_flet.tabs.mark.context import MarkTabContext
from core.config_store import grading_type_for_paper
from core.models import PaperType
from modules.marking.ms_parser import (
    ms_cache_exists,
    parse_mark_scheme,
    resolve_ms_start_page,
)
from modules.marking.page_segmenter import (
    ScannedDocument,
    match_scanned,
    scan_document,
)
from modules.marking.renderer import NativeRenderer
from modules.marking.syllabus_parser import (
    SyllabusParseError,
    load_syllabus,
    parse_syllabus,
)
from modules.marking.workflow import regions_to_page_map

if TYPE_CHECKING:
    from modules.marking.ms_parser import PaperConfig

_log = logging.getLogger("cie_helper.mark")

#: Where the user goes to fetch a syllabus PDF by hand. There is deliberately
#: no download code: the site serves its app shell instead of the file unless
#: the request carries the right headers, so a scraper would "succeed" with
#: HTML — see the design doc's Non-Goals.
_SYLLABUS_SLUGS: dict[str, str] = {
    "9709": "mathematics-9709",
    "9231": "further-mathematics-9231",
    "9702": "physics-9702",
    "9701": "chemistry-9701",
    "9700": "biology-9700",
    "9696": "geography-9696",
}
_SYLLABUS_URL = "https://pastpapers.co/caie/a-level/{slug}/syllabus-%26-specimen"


def _async_click(
    fn: Callable[[MarkTabContext], Awaitable[None]],
    ctx: MarkTabContext,
) -> Callable[[ft.Event[ft.Button]], Awaitable[None]]:
    """Bind ``ctx`` into an async click handler.

    Must produce a genuine ``async def`` — a lambda returning the coroutine
    would hand Flet an un-awaited object and the picker would never open.
    """
    async def _handler(_: ft.Event[ft.Button]) -> None:
        await fn(ctx)

    return _handler


# ── View ──────────────────────────────────────────────────────────

def build_setup_step(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    controls: list[ft.Control] = [
        ft.Text("AI 批改", size=24, weight=ft.FontWeight.BOLD),
        ft.Divider(),
        ft.Text(
            "Step 1 — 选择试卷与答卷", size=18,
            weight=ft.FontWeight.BOLD,
        ),
    ]

    # Source radio
    controls.append(ft.RadioGroup(
        content=ft.Row([
            ft.Radio(value="downloaded", label="从已下载试卷"),
            ft.Radio(value="upload", label="上传 PDF"),
        ]),
        value=ctx.ms_source,
        on_change=lambda e: _on_source_change(ctx, e),
    ))

    # Built before the type radio even though it renders after it: choosing
    # the paper is what resolves the default selection, and the configured
    # grading type follows from the paper.
    selector = (
        _build_paper_selector(ctx) if ctx.ms_source == "downloaded" else []
    )
    _sync_paper_type(ctx)

    # Paper type radio
    controls.append(ft.RadioGroup(
        content=ft.Row([
            ft.Radio(value="mcq", label="MCQ"),
            ft.Radio(value="math", label="Structured / Math"),
        ]),
        value=ctx.paper_type.value,
        on_change=lambda e: _on_type_change(ctx, e),
    ))

    if ctx.ms_source == "downloaded":
        controls.extend(selector)
        controls.extend(_build_syllabus_row(ctx))
    else:
        upload_label = (
            ctx.ms_upload_path.split("\\")[-1].split("/")[-1]
            if ctx.ms_upload_path
            else "未选择文件"
        )
        controls.append(ft.Row([
            ft.Button(
                "选择 MS PDF 文件",
                icon=ft.Icons.UPLOAD_FILE,
                on_click=_async_click(_on_ms_upload_click, ctx),
            ),
            ft.Text(upload_label, size=12, color=theme.MUTED),
        ]))

    # Start page (MATH only)
    if ctx.paper_type == PaperType.MATH:
        controls.append(ft.TextField(
            label="MS 内容起始页",
            label_style=theme.field_label_style(),
            value="" if ctx.start_page is None else str(ctx.start_page),
            hint_text="自动",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=200,
            helper=ft.Text("默认留空，自动检测", size=11, color=theme.MUTED),
            on_change=lambda e: _on_start_page_change(ctx, e),
        ))

    # Answer paper — picked here so its scan can run alongside the MS parse.
    # Math calls it 答卷; MCQ wants the annotated question paper.
    is_mcq = ctx.paper_type == PaperType.MCQ
    answer_label = (
        ctx.answer_path.replace("\\", "/").split("/")[-1]
        if ctx.answer_path
        else "未选择文件（可稍后再选）"
    )
    controls.append(ft.Row([
        ft.Button(
            "选择已批注 QP PDF" if is_mcq else "选择答卷 PDF",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=_async_click(_on_answer_pick_click, ctx),
        ),
        ft.Text(answer_label, size=12, color=theme.MUTED),
    ]))
    if is_mcq:
        controls.append(ft.Text(
            "上传在 GoodNotes 中批注过的试卷（圈出/写出每题答案）。",
            size=12, color=theme.MUTED,
        ))

    # Warning if MATH but no grader configured
    if ctx.paper_type == PaperType.MATH and state.grader_config is None:
        controls.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.WARNING, color=theme.WARNING),
                ft.Text("请先在设置中配置 Grader API 凭证", color=theme.WARNING),
            ]),
            padding=8,
        ))

    # Parse button (+ cached-result hint on the same row, far right)
    can_parse = (
        not ctx.parsing
        and ctx.ms_path() is not None
        and (is_mcq or state.grader_config is not None)
    )
    parse_row: list[ft.Control] = [ft.Button(
        (
            "解析 Mark Scheme 与答卷"
            if ctx.answer_path and not is_mcq
            else "解析 Mark Scheme"
        ),
        icon=ft.Icons.SEARCH,
        disabled=not can_parse,
        style=theme.filled_button(),
        on_click=lambda _: start_analysis(ctx, force=False),
    )]
    if state.paper_config and state.ms_from_cache:
        parse_row.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.HISTORY, color=theme.ACCENT_STRONG, size=16),
                ft.Text("此结果来自缓存", size=12),
                ft.TextButton(
                    "重新解析",
                    disabled=not can_parse,
                    on_click=lambda _: start_analysis(ctx, force=True),
                ),
            ], spacing=6, tight=True),
            bgcolor=theme.ACCENT_TINT,
            border_radius=8,
            padding=ft.Padding(left=10, right=4, top=2, bottom=2),
        ))
    controls.append(ft.Row(
        parse_row, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    ))

    # Parsed config preview (hidden while a new parse is running)
    if state.paper_config and not ctx.parsing:
        pc = state.paper_config
        q_controls: list[ft.Control] = []
        for qid, qcfg in pc.questions.items():
            q_controls.append(ft.Text(
                f"{qid} — {qcfg.max_marks} marks",
                weight=ft.FontWeight.BOLD, size=13,
            ))
            q_controls.append(ft.Text(
                qcfg.mark_scheme, size=12, color=theme.MUTED,
            ))
        controls.append(ft.ExpansionTile(
            title=ft.Text(
                f"已解析: {pc.paper_id} ({len(pc.questions)} 题)",
            ),
            controls=[ft.Container(
                ft.Column(q_controls, spacing=4), padding=12,
            )],
        ))

    return controls


def _build_paper_selector(ctx: MarkTabContext) -> list[ft.Control]:
    try:
        all_records = ctx.state.store.load_all()
    except ValueError:
        all_records = []
    ms_records = [r for r in all_records if r.ms_path]
    if not ms_records:
        return [ft.Text(
            "没有包含 Mark Scheme 的已下载试卷。请先下载或直接上传。",
            color=theme.MUTED, size=13,
        )]

    syllabus_codes = sorted({r.paper_id.split("_")[0] for r in ms_records})
    if ctx.selected_syllabus not in syllabus_codes and syllabus_codes:
        ctx.selected_syllabus = syllabus_codes[0]
    sel_syl = ctx.selected_syllabus or ""

    filtered = sorted(
        [r for r in ms_records if r.paper_id.startswith(f"{sel_syl}_")],
        key=lambda r: r.paper_id,
    )
    filtered_ids = [r.paper_id for r in filtered]
    if ctx.selected_paper not in filtered_ids and filtered_ids:
        ctx.selected_paper = filtered_ids[0]

    return [ft.Row([
        ft.Dropdown(
            label="科目代码",
            label_style=theme.field_label_style(),
            options=[ft.dropdown.Option(code) for code in syllabus_codes],
            value=ctx.selected_syllabus,
            width=160,
            on_select=lambda e: _on_syllabus_select(ctx, e),
        ),
        ft.Dropdown(
            label="选择试卷",
            label_style=theme.field_label_style(),
            options=[ft.dropdown.Option(pid) for pid in filtered_ids],
            value=ctx.selected_paper,
            expand=True,
            on_select=lambda e: _on_paper_select(ctx, e),
        ),
    ], spacing=12)]


# ── Syllabus (optional, for topic tagging) ────────────────────────

def _syllabus_status(ctx: MarkTabContext) -> ft.Text:
    if ctx.syllabus_parsing:
        return ft.Text("正在解析大纲…", size=12, color=theme.MUTED)
    if ctx.syllabus_error:
        return ft.Text(
            f"大纲解析失败: {ctx.syllabus_error}", size=12, color=theme.DANGER,
        )
    info = ctx.syllabus_info
    if info is None:
        return ft.Text(
            "未选择（不影响批改，仅用于给错题打 topic 标签）",
            size=12, color=theme.MUTED,
        )
    return ft.Text(
        f"{info.subject_id}: 已识别 {len(info.topics)} 个 topic，"
        f"{len(info.component_topics)} 个 component",
        size=12, color=theme.MUTED,
    )


def _sync_paper_type(ctx: MarkTabContext) -> None:
    """Set the grading path from ``syllabus_config.json`` for this paper.

    Picking it by hand every time is both a chore and a silent trap: grading
    a structured paper in MCQ mode takes the deterministic answer-key path,
    which never calls the VL model, so the paper comes back with no topics
    and no mistake records and nothing says why.

    The user still wins — moving the radio sets ``paper_type_overridden``
    and that stands until they select a different paper.
    """
    if ctx.ms_source != "downloaded" or ctx.paper_type_overridden:
        return
    paper_id = ctx.selected_paper
    if not paper_id or paper_id == ctx.paper_type_synced_for:
        return
    configured = grading_type_for_paper(paper_id)
    if configured is None:
        # Not in syllabus_config — leave paper_type_synced_for unset so a
        # config added later in this session is picked up on the next visit,
        # and reset paper_type instead of carrying over whatever the last
        # configured paper left it at.
        ctx.paper_type = PaperType.MATH
        return
    ctx.paper_type_synced_for = paper_id
    ctx.paper_type = configured


def _sync_syllabus_to_subject(ctx: MarkTabContext) -> None:
    """Point ``ctx.syllabus_info`` at the *selected* subject's syllabus.

    Two things depend on this, both of which were wrong without it:

    * a syllabus parsed in an earlier session is picked up from the store, so
      the user uploads each subject's PDF once, not once per app start;
    * switching the subject dropdown drops the previous subject's topics.
      Keeping them would hand 9709's topic list to a 9231 paper and tag every
      question against the wrong syllabus — silently, since the ids overlap.
    """
    if ctx.syllabus_parsing:
        return
    subject = ctx.selected_syllabus or ""
    current = ctx.syllabus_info
    if current is not None and current.subject_id == subject:
        return
    ctx.syllabus_info = load_syllabus(subject) if subject else None
    ctx.syllabus_error = None
    ctx.syllabus_path = None


def _build_syllabus_row(ctx: MarkTabContext) -> list[ft.Control]:
    """The 大纲 PDF picker plus a link to where one is downloaded.

    Only shown for the downloaded-MS Math flow: MCQ papers are graded
    deterministically and never call the VL model, and an uploaded mark
    scheme has no paper id to resolve a component against — both cases would
    show a control that could not do anything.
    """
    if ctx.ms_source != "downloaded" or ctx.paper_type != PaperType.MATH:
        return []
    _sync_syllabus_to_subject(ctx)

    row: list[ft.Control] = [
        ft.Button(
            "选择大纲 PDF",
            icon=ft.Icons.MENU_BOOK,
            disabled=ctx.syllabus_parsing,
            on_click=_async_click(_on_syllabus_upload_click, ctx),
        ),
        _syllabus_status(ctx),
    ]
    slug = _SYLLABUS_SLUGS.get(ctx.selected_syllabus or "")
    if slug:
        row.append(ft.TextButton(
            "去官网下载",
            icon=ft.Icons.OPEN_IN_NEW,
            on_click=_launch_syllabus_url(ctx, slug),
        ))
    return [ft.Row(row, spacing=8, wrap=True)]


def _launch_syllabus_url(
    ctx: MarkTabContext, slug: str,
) -> Callable[[ft.Event[ft.TextButton]], None]:
    url = _SYLLABUS_URL.format(slug=slug)

    async def _open() -> None:
        await ctx.page.launch_url(url)

    def _handler(_: ft.Event[ft.TextButton]) -> None:
        ctx.page.run_task(_open)

    return _handler


async def _on_syllabus_upload_click(ctx: MarkTabContext) -> None:
    if ctx.syllabus_picker is None:
        ctx.syllabus_picker = ft.FilePicker()
        ctx.page.services.append(ctx.syllabus_picker)
    files = await ctx.syllabus_picker.pick_files(
        allowed_extensions=["pdf"],
        dialog_title="选择大纲 (Syllabus) PDF",
    )
    if not files or not files[0].path:
        return
    _start_syllabus_parse(ctx, files[0].path)


def _start_syllabus_parse(ctx: MarkTabContext, path: str) -> None:
    """Parse the syllabus off the UI thread; a failure is never fatal."""
    subject_id = ctx.selected_syllabus or ""
    ctx.syllabus_path = path
    ctx.syllabus_error = None
    ctx.syllabus_info = None
    ctx.syllabus_parsing = True
    ctx.rebuild()

    def _run() -> None:
        try:
            # force: picking a file by hand is an explicit "use this one".
            # Without it a corrected PDF would be swallowed by the copy
            # already in the store.
            ctx.syllabus_info = parse_syllabus(path, subject_id, force=True)
        except SyllabusParseError as exc:
            ctx.syllabus_error = str(exc)
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            _log.exception("syllabus parse failed")
            ctx.syllabus_error = str(exc)
        finally:
            ctx.syllabus_parsing = False
            ctx.rebuild()

    ctx.page.run_thread(_run)


# ── Handlers ──────────────────────────────────────────────────────

def _on_source_change(
    ctx: MarkTabContext, e: ft.Event[ft.RadioGroup],
) -> None:
    ctx.ms_source = str(e.data)
    ctx.rebuild()


def _on_type_change(
    ctx: MarkTabContext, e: ft.Event[ft.RadioGroup],
) -> None:
    ctx.paper_type = (
        PaperType.MCQ if str(e.data) == "mcq" else PaperType.MATH
    )
    # Their choice outranks the configured one until they change papers.
    ctx.paper_type_overridden = True
    ctx.rebuild()


def _on_start_page_change(
    ctx: MarkTabContext, e: ft.Event[ft.TextField],
) -> None:
    raw = str(e.data or "").strip()
    if not raw:
        ctx.start_page = None  # blank → auto-detect
        return
    try:
        ctx.start_page = int(raw)
    except ValueError:
        ctx.start_page = None


def _on_syllabus_select(
    ctx: MarkTabContext, e: ft.Event[ft.Dropdown],
) -> None:
    ctx.selected_syllabus = str(e.data) if e.data else None
    ctx.selected_paper = None
    ctx.rebuild()


def _on_paper_select(
    ctx: MarkTabContext, e: ft.Event[ft.Dropdown],
) -> None:
    ctx.selected_paper = str(e.data) if e.data else None
    # A different paper gets its own configured type, override cleared.
    ctx.paper_type_overridden = False
    ctx.rebuild()


async def _on_ms_upload_click(ctx: MarkTabContext) -> None:
    files = await ctx.ms_picker.pick_files(
        allowed_extensions=["pdf"],
        dialog_title="选择 Mark Scheme PDF",
    )
    if files and files[0].path:
        ctx.ms_upload_path = files[0].path
        ctx.rebuild()


async def _on_answer_pick_click(ctx: MarkTabContext) -> None:
    is_mcq = ctx.paper_type == PaperType.MCQ
    files = await ctx.answer_picker.pick_files(
        allowed_extensions=["pdf"],
        dialog_title=(
            "选择已批注 QP PDF" if is_mcq
            else "选择答卷 PDF (GoodNotes 导出)"
        ),
    )
    if not files or not files[0].path:
        return

    ctx.answer_path = files[0].path
    # Picking a file only records it — nothing is analysed until the button
    # runs both halves together. Drop whatever the previous answer produced
    # so no stale page list is left on screen.
    state = ctx.state
    state.answer_pdf_path = None
    state.auto_pages_done = False
    state.auto_pages.clear()
    state.auto_clips.clear()
    state.grading_results.clear()
    state.score_overrides.clear()
    state.grading_confirmed = False
    state.mcq_qp_path = None
    state.mcq_qp_filename = None
    state.mcq_detected = {}
    state.mcq_undetected = []
    state.mcq_confirmed = False
    ctx.manual_answer_values.clear()
    ctx.rebuild()


# ── The analysis itself ───────────────────────────────────────────

def start_analysis(ctx: MarkTabContext, *, force: bool) -> None:
    """Kick off the mark-scheme parse and the answer scan on two threads."""
    state = ctx.state
    ms_path = ctx.ms_path()
    if not ms_path:
        ctx.show_snack("请先选择 Mark Scheme 文件", theme.DANGER)
        return

    pt = ctx.paper_type
    answer_path = ctx.answer_path
    # Only the Math flow segments the answer PDF up front; MCQ detection is a
    # paid LLM call the user triggers explicitly, so there is nothing to
    # overlap there — MCQ just carries the file through.
    scan_path = answer_path if pt == PaperType.MATH else None

    progress_bar = ft.ProgressBar(visible=True)
    progress_text = ft.Text(
        "正在解析 Mark Scheme…", size=12, color=theme.MUTED,
    )
    scan_text = (
        ft.Text("正在解析答卷…", size=12, color=theme.MUTED)
        if scan_path else None
    )
    ctx.parse_bar = progress_bar
    ctx.parse_text = progress_text
    ctx.scan_text = scan_text
    ctx.parsing = True
    ctx.rebuild()

    def _parse_ms() -> tuple[PaperConfig, bool]:
        def _on_progress(batch: int, total: int) -> None:
            progress_bar.value = batch / total
            progress_text.value = f"处理第 {batch}/{total} 批…"
            ctx.ui_update()

        # Resolve the start page once up front (MCQ ignores it): both the
        # cache-hit check and the parse itself need it, and passing the
        # resolved number to parse_mark_scheme avoids running the
        # page-detection scan a second time.
        resolved_start = (
            resolve_ms_start_page(ms_path, ctx.start_page)
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
                state.pdf_renderer, ctx.page.session.connection.loop,
            ),
            force=force,
        )
        return pc, from_cache

    def _scan_answer(path: str) -> ScannedDocument:
        cached = ctx.scanned
        if cached is not None and cached[0] == path:
            return cached[1]
        doc = scan_document(path)
        ctx.scanned = (path, doc)
        return doc

    def _on_scan_done(fut: Future[ScannedDocument]) -> None:
        # Fires on the scan's own thread the moment it finishes, so the
        # status flips while the (slower) MS parse is still running.
        if scan_text is None:
            return
        scan_text.value = (
            "答卷解析失败" if fut.exception() else "答卷解析完成"
        )
        ctx.ui_update()

    def _run() -> None:
        pc: PaperConfig | None = None
        from_cache = False
        doc: ScannedDocument | None = None
        ms_error: str | None = None
        scan_error: str | None = None

        # Exiting the `with` joins both workers.
        with ThreadPoolExecutor(max_workers=2) as pool:
            ms_future = pool.submit(_parse_ms)
            scan_future = (
                pool.submit(_scan_answer, scan_path) if scan_path else None
            )
            if scan_future is not None:
                scan_future.add_done_callback(_on_scan_done)
            try:
                pc, from_cache = ms_future.result()
            except Exception as exc:
                ms_error = str(exc)
            if scan_future is not None:
                try:
                    doc = scan_future.result()
                except Exception as exc:
                    _log.exception("answer scan failed")
                    scan_error = str(exc)

        try:
            if pc is not None:
                _commit(ctx, pc, from_cache, pt, answer_path, doc)
            if ms_error is not None:
                ctx.show_snack(f"解析失败: {ms_error}", theme.DANGER)
            elif scan_error is not None:
                ctx.show_snack(f"答卷分析失败: {scan_error}", theme.DANGER)
            elif pc is not None:
                ctx.show_snack(_summary(ctx, pc, doc), theme.SUCCESS)
        finally:
            ctx.parsing = False
            ctx.parse_bar = None
            ctx.parse_text = None
            ctx.scan_text = None
            ctx.rebuild()

    ctx.page.run_thread(_run)


def _commit(
    ctx: MarkTabContext,
    pc: PaperConfig,
    from_cache: bool,
    pt: PaperType,
    answer_path: str | None,
    doc: ScannedDocument | None,
) -> None:
    """Publish a finished analysis to AppState, resetting stale results."""
    state = ctx.state
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
    ctx.grade_questions = []
    ctx.grade_questions_seeded = False

    if pt == PaperType.MCQ:
        state.mcq_qp_path = answer_path
        state.mcq_qp_filename = (
            answer_path.replace("\\", "/").split("/")[-1]
            if answer_path else None
        )
        state.mcq_detected = {}
        state.mcq_undetected = []
        state.mcq_confirmed = False
        return

    if answer_path is None:
        return
    state.answer_pdf_path = answer_path
    if doc is None:
        # Scan failed — let the user type page numbers by hand rather than
        # stranding the flow at Step 1. Every question counts as unmatched,
        # and the page total is unknown (not the last paper's).
        state.answer_total_pages = 0
        state.unmatched_questions = list(pc.questions.keys())
        state.auto_pages_done = True
        return

    # Cheap half of segmentation: the question ids only became known when
    # the MS parse finished.
    regions, report = match_scanned(doc, list(pc.questions.keys()))
    auto_pages, auto_clips = regions_to_page_map(regions)
    state.answer_total_pages = doc.page_count
    state.auto_pages = auto_pages
    state.auto_clips = auto_clips
    state.unmatched_questions = report.unmatched
    state.auto_pages_done = True


def _summary(
    ctx: MarkTabContext, pc: PaperConfig, doc: ScannedDocument | None,
) -> str:
    msg = (
        f"已解析 {pc.paper_id} — 共 {len(pc.questions)} 题, "
        f"总分为 {pc.total_marks}"
    )
    if doc is not None:
        msg += (
            f"；答卷 {doc.page_count} 页，"
            f"识别 {len(ctx.state.auto_pages)}/{len(pc.questions)} 题"
        )
    return msg
