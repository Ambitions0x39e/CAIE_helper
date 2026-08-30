"""Per-question grading results, score overrides, and recording the total.

:func:`record_score` is shared with the MCQ flow — both end the same way.
"""
from __future__ import annotations

import datetime
from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.components.widgets import metric_card, success_banner
from app_flet.tabs.mark.context import MarkTabContext
from core.storage import MistakeStore
from modules.manager import PaperManager, ScoreUpdate
from modules.marking.mistakes import mistakes_from_results
from modules.marking.workflow import (
    ScoreSummary,
    summarise_scores,
    topics_for_paper,
)


def record_score(ctx: MarkTabContext, totals: ScoreSummary) -> bool:
    """Write the paper's score to the store; True if it counts as done.

    An uploaded mark scheme has no record to attach to, so the score is only
    reported back to the user.
    """
    paper_id = ctx.state.graded_paper_id
    if paper_id is None:
        ctx.show_snack(
            f"分数: {totals.score:g}/{totals.max_score:g} "
            f"({totals.percentage:.1f}%) — 使用管理页面手动记录",
            theme.ACCENT,
        )
        return True

    # Goes through PaperManager rather than a hand-rolled
    # store.update(model_copy(...)): it validates via ScoreUpdate and stamps
    # `timestamp`, which the two inline versions here used to skip — Mark-tab
    # papers ended up Completed but undated, unlike every paper scored
    # through the 登记成绩 dialog.
    try:
        update = ScoreUpdate(
            paper_id=paper_id,
            score_raw=float(totals.score),
            score_total=float(totals.max_score),
        )
    except ValueError as exc:
        ctx.show_snack(f"记录失败: {exc}", theme.DANGER)
        return False

    result = PaperManager(store=ctx.state.store).submit_score(update)
    if not result.success:
        ctx.show_snack(f"记录失败: {result.error}", theme.DANGER)
        return False
    ctx.show_snack(
        f"已记录 {totals.score:g}/{totals.max_score:g} → {paper_id}",
        theme.SUCCESS,
    )
    return True


def record_mistakes(ctx: MarkTabContext) -> None:
    """File every question that lost marks into the 错题本.

    Gated on ``state.graded_paper_id`` being set, exactly like
    :func:`record_score`, and for the same reason: an uploaded mark scheme
    has no real paper_id, and paper_id is how the notebook reconstructs
    subject / session / component downstream.

    Failure here never blocks the score that was just recorded — the mistake
    notebook is a bonus, so a broken CSV gets a warning, not an error path.
    """
    paper_id = ctx.state.graded_paper_id
    if paper_id is None:
        return
    records = mistakes_from_results(
        ctx.state.grading_results,
        paper_id=paper_id,
        topics=topics_for_paper(ctx.syllabus_info, paper_id),
        timestamp=datetime.datetime.now(),
    )
    if not records:
        return
    try:
        MistakeStore().append_many(records)
    except (OSError, ValueError) as exc:
        ctx.show_snack(f"错题记录写入失败: {exc}", theme.WARNING)
        return
    ctx.show_snack(f"已记入错题本 {len(records)} 题", theme.SUCCESS)


# ── View ──────────────────────────────────────────────────────────

def build_results(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    results = state.grading_results
    if not results:
        return []

    controls: list[ft.Control] = [
        ft.Divider(),
        ft.Text(
            "批改结果", size=theme.SECTION, weight=ft.FontWeight.BOLD,
            style=theme.section_style(),
        ),
    ]

    overrides = state.score_overrides
    totals = summarise_scores(results, overrides)
    controls.append(ft.Row(
        [
            metric_card(
                "总分",
                f"{totals.score:g}/{totals.max_score:g}",
                theme.PRIMARY,
            ),
            metric_card(
                "百分比", f"{totals.percentage:.1f}%", theme.SUCCESS,
            ),
            metric_card("题数", str(len(results)), theme.CARD_PURPLE),
        ],
        spacing=12, scroll=ft.ScrollMode.AUTO,
    ))

    for qr in results:
        ov = overrides.get(qr.question, qr.total)
        mark_controls: list[ft.Control] = [
            ft.Text(
                f"{qr.question} — {ov}/{qr.max}",
                weight=ft.FontWeight.BOLD, size=15,
            ),
        ]
        for m in qr.marks:
            mark_controls.append(ft.Row(
                [
                    ft.Icon(
                        ft.CupertinoIcons.CHECKMARK_CIRCLE_FILL if m.awarded
                        else ft.CupertinoIcons.XMARK_CIRCLE_FILL,
                        color=theme.SUCCESS if m.awarded else theme.DANGER,
                        size=18,
                    ),
                    ft.Text(
                        f"{m.code}: {m.reason}",
                        size=13,
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
                            ft.CupertinoIcons.CHAT_BUBBLE,
                            color=theme.PRIMARY, size=16,
                        ),
                        ft.Text(
                            qr.comment,
                            color=theme.MUTED, size=theme.CAPTION,
                            style=theme.caption_style(),
                            expand=True,  # wrap long comments
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=ft.Padding(left=0, right=0, top=4, bottom=0),
            ))

        override_handler = _override_handler(ctx, qr.question, qr.max)
        controls.append(ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Column(mark_controls, spacing=4), expand=4,
                    ),
                    ft.VerticalDivider(width=1),
                    ft.Container(
                        ft.TextField(
                            label="调分", value=str(ov), width=90,
                            label_style=theme.field_label_style(),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            dense=True,
                            on_submit=override_handler,
                            on_blur=override_handler,
                        ),
                        expand=1,
                        alignment=ft.Alignment(0, 0),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=12,
            ),
            padding=12,
            border=ft.Border.all(1, theme.HAIRLINE),
            border_radius=8,
        ))

    # Confirm & Log
    if state.grading_confirmed:
        controls.append(success_banner("分数已记录"))
    else:
        controls.append(ft.Text(
            "检查上方结果，确认后记录分数。", size=theme.CAPTION,
            color=theme.MUTED, style=theme.caption_style(),
        ))
        controls.append(ft.Button(
            "确认并记录分数",
            icon=ft.CupertinoIcons.CHECKMARK,
            style=theme.filled_button(theme.SUCCESS),
            on_click=lambda _: _on_confirm_click(ctx),
        ))

    return controls


# ── Handlers ──────────────────────────────────────────────────────

def _override_handler(
    ctx: MarkTabContext, question: str, max_marks: int,
) -> Callable[[ft.Event[ft.TextField]], None]:
    """Accept a manual score for one question, bounded by its max marks.

    Out-of-range values are rejected rather than stored: a total above the
    paper's own maximum cannot be written to data.csv (PaperRecord rejects
    it), so letting one sit in the UI only produces a confusing failure at
    「确认并记录分数」. The rebuild restores the last good value.
    """
    def _handler(e: ft.Event[ft.TextField]) -> None:
        try:
            value = int(e.data or 0)
        except ValueError:
            ctx.show_snack(f"{question} 的分数需为整数", theme.WARNING)
            ctx.rebuild()
            return
        if not 0 <= value <= max_marks:
            ctx.show_snack(
                f"{question} 的分数需在 0–{max_marks} 之间", theme.WARNING,
            )
            ctx.rebuild()
            return
        ctx.state.score_overrides[question] = value
        ctx.rebuild()

    return _handler


def _on_confirm_click(ctx: MarkTabContext) -> None:
    results = ctx.state.grading_results
    if not results:
        return
    totals = summarise_scores(results, ctx.state.score_overrides)
    if record_score(ctx, totals):
        ctx.state.grading_confirmed = True
        # Hooked to the confirm button, not to the end of grading: a re-grade
        # the user never confirms shouldn't leave rows behind, and the store
        # is append-only (no dedup) so every extra write would show up.
        record_mistakes(ctx)
    ctx.rebuild()
