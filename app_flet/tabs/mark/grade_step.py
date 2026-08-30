"""第二步「核对」——每题一格：批不批、页码是几、满分多少，然后开跑。

页码和勾选合在同一格里，是因为它们说的是同一题：分成两张表的时候，「1(a) 的
页码」和「要不要批 1(a)」隔着半屏，改一处要在两边各找一次。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.components.widgets import (
    error_banner,
    info_banner,
    warning_banner,
)
from app_flet.tabs.mark.context import MarkTabContext
from core.models import PaperType
from core.settings import GraderConfig
from modules.marking.grader import QuestionResult
from modules.marking.renderer import NativeRenderer
from modules.marking.workflow import collect_page_assignments, grade_paper

_log = logging.getLogger("cie_helper.mark")


def collect_assignments(ctx: MarkTabContext) -> dict[str, list[int]]:
    """Read the page-number boxes into question id → pages."""
    return collect_page_assignments({
        qid: tf.value or "" for qid, tf in ctx.page_inputs.items()
    })


# ── View ──────────────────────────────────────────────────────────

#: 一行放几格。跟结果区同一个数——两步看的是同一批题，列数一致才认得出是
#: 同一张表。
_CELLS_PER_ROW = 6


def build_check_step(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    controls: list[ft.Control] = [
        ft.Text(
            "核对题目", size=theme.SECTION, weight=ft.FontWeight.BOLD,
            style=theme.section_style(),
        ),
    ]

    # Persistent failure banner — a grade that stalls/errors on one question
    # would otherwise only flash a toast and vanish.
    if state.grading_error:
        controls.append(error_banner(state.grading_error))

    if state.grader_config is None:
        controls.append(warning_banner("请先在设置中配置 Grader API 凭证"))
        return controls

    pc = state.paper_config
    if pc is None:
        return controls

    controls.append(_detection_banner(ctx))

    available_qs = [
        qid for qid in pc.questions if qid not in state.deleted_questions
    ]
    if not ctx.grade_questions_seeded:
        ctx.grade_questions_seeded = True
        ctx.grade_questions = list(collect_assignments(ctx).keys())

    controls.append(ft.Row([
        ft.Text(
            "勾选要批改的题，并确认每题的页码。", size=theme.BODY,
            style=theme.body_style(),
        ),
        ft.Container(expand=True),
        ft.TextButton("全选", on_click=lambda _: _select_all(ctx, True)),
        ft.TextButton("全不选", on_click=lambda _: _select_all(ctx, False)),
    ]))

    ctx.page_inputs.clear()
    cells: list[ft.Control] = [
        _question_cell(ctx, qid, pc.questions[qid].max_marks)
        for qid in available_qs
    ]
    for i in range(0, len(cells), _CELLS_PER_ROW):
        row = cells[i : i + _CELLS_PER_ROW]
        # 最后一行不足一整行时补透明占位，理由同结果区：格子靠 expand 平分。
        row += [
            ft.Container(expand=True)
            for _ in range(_CELLS_PER_ROW - len(row))
        ]
        controls.append(ft.Row(
            row, spacing=theme.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ))

    # Validation
    assignments = collect_assignments(ctx)
    selected = ctx.grade_questions
    missing = [q for q in selected if q not in assignments]
    if not selected:
        controls.append(ft.Text(
            "请至少勾选一个题目进行批改。", color=theme.WARNING,
            size=theme.CAPTION, style=theme.caption_style(),
        ))
    elif missing:
        controls.append(ft.Text(
            f"请为以下题目指定页码: {', '.join(missing)}",
            color=theme.WARNING, size=theme.CAPTION,
            style=theme.caption_style(),
        ))

    can_grade = (
        bool(selected) and not missing and not state.grading_in_progress
    )
    controls.append(ft.Row([
        ft.Switch(
            label="启用思考模式 (更慢但更准确)",
            value=ctx.thinking,
            on_change=lambda e: _on_thinking_change(ctx, e),
        ),
        ft.Container(expand=True),
        ft.Button(
            "开始批改",
            icon=ft.CupertinoIcons.ROCKET_FILL,
            disabled=not can_grade,
            style=theme.filled_button(),
            on_click=lambda _: _on_grade_click(ctx),
        ),
    ]))

    return controls


def _detection_banner(ctx: MarkTabContext) -> ft.Control:
    """自动分页找到了多少题，以及没找到的是哪些。

    只差一题也报警：分页部分成功是常态，不是边角情况——漏掉的那题会一路走到
    批改时才失败。
    """
    state = ctx.state
    matched = len(state.auto_pages)
    total_q = len(state.paper_config.questions) if state.paper_config else 0
    if matched >= total_q:
        return info_banner(
            f"PDF 共 {state.answer_total_pages} 页 | "
            f"{matched}/{total_q} 题已自动定位",
        )
    missing = state.unmatched_questions
    preview = "、".join(missing[:8])
    if len(missing) > 8:
        preview += f" 等 {len(missing)} 题"
    return warning_banner(
        f"PDF 共 {state.answer_total_pages} 页 | "
        f"自动识别 {matched}/{total_q} 题",
        details=[f"未识别：{preview}。请为这些题手动填页码（例如 2 或 2,3）。"],
    )


def _question_cell(
    ctx: MarkTabContext, qid: str, max_marks: int,
) -> ft.Control:
    """一题一格：勾选 + 题号 + 满分 + 页码 + 移除。"""
    default_val = ctx.state.auto_pages.get(qid, "")
    # 空页码 = 这题没被自动识别出来。染成警告色，读作「该你填了」而不是故障。
    needs_input = not default_val
    tf = ft.TextField(
        label="页码",
        label_style=ft.TextStyle(
            color=theme.WARNING_STRONG if needs_input else None,
        ),
        value=default_val,
        hint_text="待填" if needs_input else "例: 2,3",
        border_color=theme.WARNING if needs_input else None,
        dense=True,
    )
    ctx.page_inputs[qid] = tf
    return ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Checkbox(
                            label=f"{qid} ({max_marks}m)",
                            label_style=ft.TextStyle(size=theme.BODY),
                            value=qid in ctx.grade_questions,
                            on_change=_check_handler(ctx, qid),
                            expand=True,
                        ),
                        # 六列下每格只有 ~180px，IconButton 默认那 48px 的
                        # 命中区会把题号挤到换行。
                        ft.IconButton(
                            ft.CupertinoIcons.XMARK,
                            tooltip=f"移除 {qid}",
                            icon_size=14,
                            width=28,
                            height=28,
                            padding=0,
                            on_click=_delete_handler(ctx, qid),
                        ),
                    ],
                    spacing=0,
                ),
                tf,
            ],
            spacing=theme.SPACE_XS,
            tight=True,
        ),
        expand=True,
        padding=theme.SPACE_SM,
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
    )


# ── Handlers ──────────────────────────────────────────────────────

def _on_thinking_change(
    ctx: MarkTabContext, e: ft.Event[ft.Switch],
) -> None:
    ctx.thinking = str(e.data).lower() == "true"


def _delete_handler(
    ctx: MarkTabContext, qid: str,
) -> Callable[[ft.Event[ft.IconButton]], None]:
    def _handler(_: ft.Event[ft.IconButton]) -> None:
        ctx.state.deleted_questions.add(qid)
        ctx.rebuild()

    return _handler


def _check_handler(
    ctx: MarkTabContext, qid: str,
) -> Callable[[ft.Event[ft.Checkbox]], None]:
    def _handler(e: ft.Event[ft.Checkbox]) -> None:
        checked = str(e.data).lower() == "true"
        if checked and qid not in ctx.grade_questions:
            ctx.grade_questions.append(qid)
        elif not checked and qid in ctx.grade_questions:
            ctx.grade_questions.remove(qid)
        ctx.rebuild()

    return _handler


def _select_all(ctx: MarkTabContext, select: bool) -> None:
    pc = ctx.state.paper_config
    if pc is None:
        return
    ctx.grade_questions = (
        [
            qid for qid in pc.questions
            if qid not in ctx.state.deleted_questions
        ]
        if select else []
    )
    ctx.rebuild()


def _on_grade_click(ctx: MarkTabContext) -> None:
    state = ctx.state
    if state.grading_in_progress:
        ctx.show_snack("已有批改请求进行中，请等待完成", theme.WARNING)
        return
    gc = state.grader_config
    pc = state.paper_config
    if gc is None or pc is None:
        return

    assignments = collect_assignments(ctx)
    questions_to_grade = [
        q for q in ctx.grade_questions if q in assignments
    ]
    if not questions_to_grade:
        ctx.show_snack("没有可批改的题目", theme.WARNING)
        return

    grade_cfg = GraderConfig(
        api_key=gc.api_key.get_secret_value(),
        base_url=gc.base_url,
        model=gc.model,
        dpi=gc.dpi,
        enable_thinking=ctx.thinking,
    )
    # Captured now, not re-read from ctx.selected_paper at confirm time: the
    # paper picker stays interactive while these results are on screen, so a
    # switch before confirming must not relabel this grading run's paper_id.
    graded_paper_id = (
        ctx.selected_paper if ctx.ms_source == "downloaded" else None
    )

    state.grading_error = None  # clear any prior failure banner
    # 清空上一轮的结果并立刻跳到「结果」步：那一步会把这一批题先画成待批的
    # 灰格子，然后一格格填上分数。盯着一条进度条看不出跑到哪了，看着格子亮
    # 起来能。
    state.grading_results = []
    state.score_overrides = {}
    state.grading_confirmed = False
    ctx.grading_queue = list(questions_to_grade)
    ctx.detail_question = None
    ctx.view_step = 2
    ctx.reached_step = 2

    def _on_result(result: QuestionResult) -> None:
        # grade_paper 把这两个回调都串行化了，所以直接改状态不用再上锁；
        # 同一题的 on_result 就在 on_progress 前一句，重绘交给它，这里只落数据。
        state.grading_results.append(result)
        state.score_overrides[result.question] = result.total

    def _on_progress(done: int, total: int, _qid: str) -> None:
        ctx.grade_progress = (done, total)
        ctx.rebuild()

    def _do_grade() -> None:
        try:
            outcome = grade_paper(
                config=grade_cfg,
                paper_config=pc,
                paper_type=state.paper_type or PaperType.MATH,
                # The path, not the bytes: the native renderer opens the file
                # itself, so a 35MB scan never crosses the Python↔Dart RPC.
                pdf_source=state.answer_pdf_path,  # type: ignore[arg-type]
                question_ids=questions_to_grade,
                assignments=assignments,
                clips=state.auto_clips,
                renderer=NativeRenderer(
                    state.pdf_renderer, ctx.page.session.connection.loop,
                ),
                syllabus_info=ctx.syllabus_info,
                # Only a downloaded paper has a real id, and the id is what
                # resolves the component → topic list. Uploading a mark
                # scheme therefore means no topic tagging *and* no mistake
                # record — deliberately the same condition, not two.
                paper_id=graded_paper_id,
                on_progress=_on_progress,
                on_result=_on_result,
            )
            # 结果已经由 _on_result 一题一题填进去了，这里只按 question_ids
            # 的顺序重排一次 —— 题目是并发跑的，回来的顺序不是卷子的顺序。
            state.grading_results = list(outcome.results)
            state.graded_paper_id = graded_paper_id
            if not outcome.ok:
                # Keep the message on screen as a banner until the next
                # grade — a toast auto-dismisses on a long run. Each
                # question fails independently, so there can be several.
                state.grading_error = "；".join(
                    f"{f.question}: {f.error}" for f in outcome.failures
                )
                ctx.show_snack(
                    f"{len(outcome.failures)} 题批改失败", theme.DANGER,
                )
        except Exception as exc:
            # to_pdf_bytes / renderer construction, i.e. before any question
            # was attempted.
            _log.exception("grading could not start")
            state.grading_error = f"批改失败: {exc}"
            ctx.show_snack(f"批改失败: {exc}", theme.DANGER)
        finally:
            state.grading_in_progress = False
            ctx.rebuild()

    state.grading_in_progress = True
    ctx.grade_progress = (0, len(questions_to_grade))
    # 先画一帧再开线程：第一题回来要几秒，这一帧就是「结果」步整页待批的灰
    # 格子。少了它，点完按钮到第一个分数出现之间屏幕是不动的。
    ctx.rebuild()
    ctx.page.run_thread(_do_grade)
