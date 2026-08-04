"""MCQ flow — detect answers on the annotated QP, correct, score, confirm.

The QP upload itself lives in Step 1, alongside the mark-scheme selection.
Detection stays a separate button because it is a paid LLM call.
"""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.components.widgets import metric_card, success_banner
from app_flet.tabs.mark.context import MarkTabContext
from app_flet.tabs.mark.results import record_score
from modules.marking.mcq_parser import detect_student_answers, score_mcq_answers
from modules.marking.renderer import NativeRenderer
from modules.marking.workflow import ScoreSummary, merge_mcq_answers


def collect_answers(ctx: MarkTabContext) -> dict[str, str]:
    return merge_mcq_answers(ctx.state.mcq_detected, ctx.manual_answer_values)


# ── View ──────────────────────────────────────────────────────────

def build_mcq_flow(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    pc = state.paper_config
    if pc is None:
        return []

    if not state.mcq_qp_path:
        return [
            ft.Divider(),
            ft.Text(
                "已解析 Mark Scheme。请在上方选择已批注的 QP PDF，"
                "再次点击解析后即可检测答案。",
                size=13, color=theme.MUTED,
            ),
        ]

    controls: list[ft.Control] = [
        ft.Divider(),
        ft.Text("Step 2 — 检测与批改", size=18, weight=ft.FontWeight.BOLD),
    ]

    if state.grader_config is None:
        controls.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.WARNING, color=theme.WARNING),
                ft.Text(
                    "请先在设置中配置 Grader API 凭证以启用自动检测",
                    color=theme.WARNING,
                ),
            ]),
            padding=8,
        ))

    controls.append(ft.Button(
        "检测答案",
        icon=ft.Icons.SEARCH,
        disabled=(
            state.grader_config is None or state.grading_in_progress
        ),
        style=theme.filled_button(),
        on_click=lambda _: _on_detect_click(ctx),
    ))

    if state.mcq_undetected:
        controls.append(ft.Text(
            f"未能检测到 {len(state.mcq_undetected)} 题: "
            f"{', '.join(state.mcq_undetected)}。请在下方手动填写。",
            color=theme.WARNING, size=12,
        ))
        controls.append(ft.Text(
            "手动填写未检测题目:", size=13, weight=ft.FontWeight.BOLD,
        ))
        ctx.mcq_manual_inputs.clear()
        manual_fields: list[ft.Control] = []
        for qid in state.mcq_undetected:
            tf = ft.TextField(
                label=qid[1:],
                label_style=theme.field_label_style(),
                value=ctx.manual_answer_values.get(qid, ""),
                max_length=1,
                width=70,
                dense=True,
                text_align=ft.TextAlign.CENTER,
                on_change=_manual_change_handler(ctx, qid),
            )
            ctx.mcq_manual_inputs[qid] = tf
            manual_fields.append(tf)
        controls.append(ft.Row(manual_fields, wrap=True, spacing=8))

    merged_answers = collect_answers(ctx)
    if not merged_answers:
        return controls

    controls.append(ft.Divider())
    score, total, per_q = score_mcq_answers(pc, merged_answers)
    pct = (score / total * 100) if total > 0 else 0
    controls.append(ft.Row(
        [
            metric_card("得分", f"{score}/{total}", theme.PRIMARY),
            metric_card("百分比", f"{pct:.1f}%", theme.SUCCESS),
            metric_card(
                "已检测", str(len(merged_answers)), theme.CARD_PURPLE,
            ),
        ],
        spacing=12, scroll=ft.ScrollMode.AUTO,
    ))

    controls.append(ft.Text(
        "逐题结果:", size=13, weight=ft.FontWeight.BOLD,
    ))
    q_cards: list[ft.Control] = []
    for qid in pc.questions:
        student_ans = merged_answers.get(qid, "–")
        if qid in merged_answers:
            is_correct = per_q.get(qid, False)
            icon = ft.Icons.CHECK_CIRCLE if is_correct else ft.Icons.CANCEL
            icon_color = theme.SUCCESS if is_correct else theme.DANGER
        else:
            icon = ft.Icons.REMOVE
            icon_color = theme.MUTED
        q_cards.append(ft.Container(
            ft.Column([
                ft.Text(qid[1:], weight=ft.FontWeight.BOLD, size=13),
                ft.Icon(icon, color=icon_color, size=16),
                ft.Text(student_ans, size=12),
                ft.Text(
                    pc.questions[qid].mark_scheme,
                    color=theme.MUTED, size=11,
                ),
            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=60, padding=6,
            border=ft.Border.all(1, theme.HAIRLINE),
            border_radius=6,
        ))
    controls.append(ft.Row(q_cards, wrap=True, spacing=6))

    controls.append(ft.Divider())
    if state.mcq_confirmed:
        controls.append(success_banner("分数已记录"))
    else:
        controls.append(ft.Text(
            "检查上方结果，确认后记录分数。", size=12, color=theme.MUTED,
        ))
        controls.append(ft.Button(
            "确认并记录分数",
            icon=ft.Icons.CHECK,
            style=theme.filled_button(theme.SUCCESS),
            on_click=lambda _: _on_confirm_click(ctx),
        ))

    return controls


# ── Handlers ──────────────────────────────────────────────────────

def _manual_change_handler(
    ctx: MarkTabContext, qid: str,
) -> Callable[[ft.Event[ft.TextField]], None]:
    def _handler(e: ft.Event[ft.TextField]) -> None:
        ctx.manual_answer_values[qid] = str(e.data or "").strip().upper()
        ctx.rebuild()

    return _handler


def _on_detect_click(ctx: MarkTabContext) -> None:
    state = ctx.state
    if state.grading_in_progress:
        ctx.show_snack("已有批改请求进行中，请等待完成", theme.WARNING)
        return
    gc = state.grader_config
    pc = state.paper_config
    if gc is None or pc is None or state.mcq_qp_path is None:
        return

    progress_bar = ft.ProgressBar(value=0, visible=True)
    progress_text = ft.Text("正在检测答案…", size=12, color=theme.MUTED)
    ctx.content.controls.extend([progress_bar, progress_text])
    ctx.page.update()

    def _on_progress(cur: int, tot: int) -> None:
        progress_bar.value = cur / tot
        progress_text.value = f"第 {cur}/{tot} 页…"
        ctx.page.update()

    def _do_detect() -> None:
        try:
            detected, undetected = detect_student_answers(
                state.mcq_qp_path,  # type: ignore[arg-type]
                pc,
                gc,
                NativeRenderer(
                    state.pdf_renderer, ctx.page.session.connection.loop,
                ),
                on_progress=_on_progress,
                source_filename=state.mcq_qp_filename,
            )
            state.mcq_detected = detected
            state.mcq_undetected = undetected
            ctx.manual_answer_values.clear()
        except Exception as exc:
            ctx.show_snack(f"检测失败: {exc}", theme.DANGER)
        finally:
            state.grading_in_progress = False
            ctx.rebuild()

    state.grading_in_progress = True
    ctx.page.run_thread(_do_detect)


def _on_confirm_click(ctx: MarkTabContext) -> None:
    pc = ctx.state.paper_config
    if pc is None:
        return
    score, total, _per_q = score_mcq_answers(pc, collect_answers(ctx))
    if record_score(ctx, ScoreSummary(score=score, max_score=total)):
        ctx.state.mcq_confirmed = True
    ctx.rebuild()
