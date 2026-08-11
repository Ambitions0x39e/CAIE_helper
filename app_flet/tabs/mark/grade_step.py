"""Step 2 — choose questions and run the grader over them."""
from __future__ import annotations

import logging
from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.tabs.mark.context import MarkTabContext
from core.models import PaperType
from core.settings import GraderConfig
from modules.marking.renderer import NativeRenderer, to_pdf_bytes
from modules.marking.workflow import collect_page_assignments, grade_paper

_log = logging.getLogger("cie_helper.mark")


def collect_assignments(ctx: MarkTabContext) -> dict[str, list[int]]:
    """Read the page-number boxes into question id → pages."""
    return collect_page_assignments({
        qid: tf.value or "" for qid, tf in ctx.page_inputs.items()
    })


# ── View ──────────────────────────────────────────────────────────

def build_grade_step(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    controls: list[ft.Control] = [
        ft.Divider(),
        ft.Text("Step 2 — 批改", size=18, weight=ft.FontWeight.BOLD),
    ]

    # Persistent failure banner — a grade that stalls/errors on one question
    # would otherwise only flash a toast and vanish.
    if state.grading_error:
        controls.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.ERROR, color=theme.DANGER, size=18),
                ft.Text(
                    state.grading_error,
                    color=theme.DANGER, size=13, expand=True,
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=8),
            bgcolor=theme.DANGER_TINT, border_radius=8, padding=12,
        ))

    if state.grader_config is None:
        controls.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.WARNING, color=theme.WARNING),
                ft.Text("请先在设置中配置 Grader API 凭证", color=theme.WARNING),
            ]),
            padding=8,
        ))
        return controls

    controls.append(ft.Switch(
        label="启用思考模式 (更慢但更准确)",
        value=ctx.thinking,
        on_change=lambda e: _on_thinking_change(ctx, e),
    ))

    pc = state.paper_config
    if pc is None:
        return controls

    available_qs = [
        qid for qid in pc.questions if qid not in state.deleted_questions
    ]
    if not ctx.grade_questions_seeded:
        ctx.grade_questions_seeded = True
        ctx.grade_questions = list(collect_assignments(ctx).keys())

    controls.append(ft.Row([
        ft.Text("选择要批改的题目:", size=13),
        ft.Container(expand=True),
        ft.TextButton(
            "全选",
            on_click=lambda _: _select_all(ctx, True),
        ),
        ft.TextButton(
            "全不选",
            on_click=lambda _: _select_all(ctx, False),
        ),
    ]))

    q_checks: list[ft.Control] = [
        ft.Container(
            ft.Checkbox(
                label=qid,
                label_style=ft.TextStyle(size=13),
                value=qid in ctx.grade_questions,
                on_change=_check_handler(ctx, qid),
            ),
            width=130,
        )
        for qid in available_qs
    ]
    controls.extend(ctx.responsive_grid(q_checks, 130))

    # Validation
    assignments = collect_assignments(ctx)
    selected = ctx.grade_questions
    missing = [q for q in selected if q not in assignments]
    if not selected:
        controls.append(ft.Text(
            "请至少勾选一个题目进行批改。", color=theme.WARNING, size=12,
        ))
    elif missing:
        controls.append(ft.Text(
            f"请为以下题目指定页码: {', '.join(missing)}",
            color=theme.WARNING, size=12,
        ))

    can_grade = (
        bool(selected) and not missing and not state.grading_in_progress
    )
    controls.append(ft.Button(
        "开始批改",
        icon=ft.Icons.ROCKET_LAUNCH,
        disabled=not can_grade,
        style=theme.filled_button(),
        on_click=lambda _: _on_grade_click(ctx),
    ))

    return controls


# ── Handlers ──────────────────────────────────────────────────────

def _on_thinking_change(
    ctx: MarkTabContext, e: ft.Event[ft.Switch],
) -> None:
    ctx.thinking = str(e.data).lower() == "true"


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

    state.grading_error = None  # clear any prior failure banner
    progress_bar = ft.ProgressBar(value=0, visible=True)
    progress_text = ft.Text("正在批改…", size=12, color=theme.MUTED)
    ctx.content.controls.extend([
        ft.Divider(), progress_bar, progress_text,
    ])
    ctx.page.update()

    def _on_progress(done: int, total: int, qid: str) -> None:
        progress_bar.value = done / total if total else 1.0
        progress_text.value = f"正在批改 {qid}…" if qid else "批改完成!"
        ctx.page.update()

    def _do_grade() -> None:
        try:
            outcome = grade_paper(
                config=grade_cfg,
                paper_config=pc,
                paper_type=PaperType(state.paper_type or "math"),
                pdf_bytes=to_pdf_bytes(state.answer_pdf_path),  # type: ignore[arg-type]
                question_ids=questions_to_grade,
                assignments=assignments,
                clips=state.auto_clips,
                renderer=NativeRenderer(
                    state.pdf_renderer, ctx.page.session.connection.loop,
                ),
                on_progress=_on_progress,
            )
            # Partial results are kept on failure, so publish either way.
            state.grading_results = list(outcome.results)
            state.score_overrides = {
                r.question: r.total for r in outcome.results
            }
            state.grading_confirmed = False
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
    ctx.page.run_thread(_do_grade)
