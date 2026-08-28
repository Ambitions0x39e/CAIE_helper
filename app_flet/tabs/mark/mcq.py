"""MCQ flow — detect answers on the annotated QP, correct, score, confirm.

The QP upload itself lives in Step 1, alongside the mark-scheme selection.
Detection stays a separate button because it is a paid LLM call.
"""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.components.widgets import (
    data_table,
    metric_card,
    success_banner,
)
from app_flet.tabs.mark.context import MarkTabContext
from app_flet.tabs.mark.results import record_score
from modules.marking.mcq_parser import detect_student_answers, score_mcq_answers
from modules.marking.ms_parser import PaperConfig
from modules.marking.renderer import NativeRenderer
from modules.marking.workflow import ScoreSummary, merge_mcq_answers


def collect_answers(ctx: MarkTabContext) -> dict[str, str]:
    return merge_mcq_answers(ctx.state.mcq_detected, ctx.manual_answer_values)


# ── Answer sheet ──────────────────────────────────────────────────

#: 一张表放 8 题。桌面窗口下 8 列还能让每格宽到放下「✓ B」而不挤，40 题正好
#: 五张表；再多一列，窄窗口就开始压字。
_QUESTIONS_PER_ROW = 8


def _given_cell(
    qid: str, answers: dict[str, str], per_q: dict[str, bool],
) -> ft.Control:
    """学生作答格：对错既给颜色也给图标，不靠单一颜色区分。"""
    if qid not in answers:
        return ft.Row(
            [
                ft.Icon(ft.Icons.REMOVE, size=13, color=theme.MUTED),
                ft.Text("–", size=theme.CAPTION, color=theme.MUTED),
            ],
            spacing=2, tight=True,
        )
    correct = per_q.get(qid, False)
    color = theme.SUCCESS if correct else theme.DANGER
    return ft.Row(
        [
            ft.Icon(
                ft.Icons.CHECK if correct else ft.Icons.CLOSE,
                size=13, color=color,
            ),
            ft.Text(
                answers[qid], size=theme.CAPTION,
                weight=ft.FontWeight.W_600, color=color,
            ),
        ],
        spacing=2, tight=True,
    )


def answer_sheet_table(
    pc: PaperConfig,
    answers: dict[str, str] | None = None,
    per_q: dict[str, bool] | None = None,
) -> ft.Control:
    """把 MCQ 答案排成答题卡：每张表 8 题，题号 / 作答 / 答案逐列对齐。

    之前是 40 个 60px 小卡片 wrap 成一片，每格自己竖着堆四行字，既没有对齐基准，
    也看不出第几题在哪。现在一竖列就是一题：题号在上、作答在中、正确答案在下，
    错在哪一题一眼扫到。

    ``answers`` 为 None 时只出题号 + 答案两行 —— Step 1 解析完 Mark Scheme 后的
    答案预览用这一档，那时还没有学生作答。两处共用一份实现，改 8 列改一个地方。

    不足 8 题的最后一段补空列，好让各段的列宽一致 —— 否则末段的几列会被
    ``expand`` 拉宽，跟上面几段错位。
    """
    qids = list(pc.questions)
    bands: list[ft.Control] = []
    for start in range(0, len(qids), _QUESTIONS_PER_ROW):
        chunk = qids[start:start + _QUESTIONS_PER_ROW]
        blanks = _QUESTIONS_PER_ROW - len(chunk)

        columns = [_label_column("题号")]
        columns += [
            ft.DataColumn(label=ft.Text(
                qid[1:], size=theme.CAPTION, weight=ft.FontWeight.W_600,
            ))
            for qid in chunk
        ]
        columns += [_label_column("") for _ in range(blanks)]

        rows: list[ft.DataRow] = []
        if answers is not None:
            given = [_label_cell("作答")]
            given += [
                ft.DataCell(_given_cell(qid, answers, per_q or {}))
                for qid in chunk
            ]
            given += [_label_cell("") for _ in range(blanks)]
            rows.append(ft.DataRow(given))

        key = [_label_cell("答案")]
        key += [
            ft.DataCell(ft.Text(
                pc.questions[qid].mark_scheme,
                size=theme.CAPTION,
                color=theme.MUTED if answers is not None else None,
                weight=(
                    ft.FontWeight.W_600 if answers is None else None
                ),
            ))
            for qid in chunk
        ]
        key += [_label_cell("") for _ in range(blanks)]
        rows.append(ft.DataRow(key))

        bands.append(data_table(columns, rows, compact=True))

    return ft.Column(bands, spacing=6)


def _label_column(text: str) -> ft.DataColumn:
    return ft.DataColumn(
        label=ft.Text(text, size=theme.CAPTION, color=theme.MUTED),
    )


def _label_cell(text: str) -> ft.DataCell:
    return ft.DataCell(
        ft.Text(text, size=theme.CAPTION, color=theme.MUTED),
    )


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
        "逐题结果:", size=theme.BODY, weight=ft.FontWeight.BOLD,
    ))
    controls.append(answer_sheet_table(pc, merged_answers, per_q))

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
