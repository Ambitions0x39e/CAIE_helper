"""Per-question grading results, score overrides, and recording the total.

:func:`record_score` is shared with the MCQ flow — both end the same way.
"""
from __future__ import annotations

import datetime
from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.components.widgets import (
    error_banner,
    metric_card,
    success_banner,
)
from app_flet.tabs.mark.context import MarkTabContext
from core.storage import MistakeStore
from modules.manager import PaperManager, ScoreUpdate
from modules.marking.grader import QuestionResult
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

#: 一行放几个分数格。跟核对步同一个数——两步看的是同一批题，列数一致才认得出
#: 是同一张表。格子用 ``expand`` 平分整行，所以窗口拉宽拉窄格子自己跟着变，
#: 不需要按 ``page.width`` 算列数。
_CELLS_PER_ROW = 6
#: 分数格高度。两行字（题号 + 得分）加上下留白。
_CELL_H = 84
#: 详情浮层宽度。够一行放下 ``M1: 一句判定理由`` 而不折成三行。
_PANEL_W = 380


def _score_color(got: float | None, max_marks: int) -> str:
    """按得分档给格子挑底色。``None`` = 这题还没批到。"""
    if got is None:
        return theme.SCORE_PENDING
    if got >= max_marks:
        return theme.SCORE_FULL
    if got <= 0:
        return theme.SCORE_ZERO
    return theme.SCORE_PARTIAL


def _grid(cells: list[ft.Control]) -> list[ft.Control]:
    """把格子切成每行 _CELLS_PER_ROW 个。

    最后一行不足一整行时补透明占位：格子靠 ``expand`` 平分整行，不补的话剩下
    那几个会被拉宽，跟上面几行对不齐。
    """
    rows: list[ft.Control] = []
    for i in range(0, len(cells), _CELLS_PER_ROW):
        row = cells[i : i + _CELLS_PER_ROW]
        row += [
            ft.Container(expand=True)
            for _ in range(_CELLS_PER_ROW - len(row))
        ]
        rows.append(ft.Row(row, spacing=theme.SPACE_MD))
    return rows


def build_results(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    results = state.grading_results
    by_qid = {r.question: r for r in results}
    # 铺格子照的是**送去批改的那一批**，不是已经回来的那些：批改跑起来的第一
    # 帧一题都还没回来，照 results 铺就是一片空白，看不出「在批了」。
    order = ctx.grading_queue or [r.question for r in results]
    if not order:
        return []

    overrides = state.score_overrides
    totals = summarise_scores(results, overrides)
    done, total = ctx.grade_progress
    controls: list[ft.Control] = [
        ft.Text("批改结果", size=theme.SECTION, weight=ft.FontWeight.BOLD),
        ft.Row(
            [
                metric_card(
                    "总分",
                    f"{totals.score:g}/{totals.max_score:g}",
                    theme.PRIMARY,
                ),
                metric_card(
                    "百分比", f"{totals.percentage:.1f}%", theme.SUCCESS,
                ),
                metric_card(
                    "题数", f"{len(results)}/{len(order)}", theme.CARD_PURPLE,
                ),
            ],
            spacing=theme.SPACE_MD, scroll=ft.ScrollMode.AUTO,
        ),
    ]

    if state.grading_in_progress:
        controls.append(ft.ProgressBar(
            value=done / total if total else None,
        ))
        controls.append(ft.Text(
            f"正在批改… {done}/{total}",
            size=theme.CAPTION, color=theme.MUTED,
        ))
    else:
        # 失败的题就落在这一步的格子里（写着「失败」的那些），横幅说明为什么。
        if state.grading_error:
            controls.append(error_banner(state.grading_error))
        controls.append(ft.Text(
            "点开任意一题看判分明细。",
            size=theme.CAPTION, color=theme.MUTED,
        ))

    controls.extend(_grid([
        _score_cell(
            ctx, qid, by_qid.get(qid), overrides,
            grading=state.grading_in_progress,
        )
        for qid in order
    ]))

    # Confirm & Log — 全部批完才给按钮：批到一半的总分不是这份卷子的分数。
    if state.grading_confirmed:
        controls.append(success_banner("分数已记录"))
    elif not state.grading_in_progress:
        controls.append(ft.Text(
            "检查结果，确认后记录分数。",
            size=theme.CAPTION, color=theme.MUTED,
        ))
        controls.append(ft.Button(
            "确认并记录分数",
            icon=ft.CupertinoIcons.CHECKMARK,
            style=theme.filled_button(theme.SUCCESS),
            on_click=lambda _: _on_confirm_click(ctx),
        ))

    return controls


def _score_cell(
    ctx: MarkTabContext,
    qid: str,
    qr: QuestionResult | None,
    overrides: dict[str, float],
    *,
    grading: bool,
) -> ft.Control:
    """一题一格：题号 + 得分，底色报告得分档，点开看明细。

    没有结果的格子有两种，靠 ``grading`` 分开——还在跑就是**还没轮到**（破折
    号），跑完了还没有就是**这题批失败了**（红字「失败」）。两者都是灰底，
    但灰底加破折号读作「等一下」，加「失败」才读得出要去看横幅。

    字色不写：主题已经把正文设成黑色，而这四档底色全是浅色 —— 见
    ``theme.SCORE_FULL`` 附近记的对比度实测。
    """
    pending = qr is None
    got = None if qr is None else overrides.get(qid, qr.total)
    max_marks = _max_marks(ctx, qid, qr)
    active = ctx.detail_question == qid
    if qr is not None:
        value, value_color = f"{got:g}/{max_marks}", None
    elif grading:
        value, value_color = "—", theme.MUTED
    else:
        value, value_color = "失败", theme.DANGER
    return ft.Container(
        ft.Column(
            [
                ft.Text(qid, size=theme.SUBHEAD, weight=ft.FontWeight.W_600),
                ft.Text(
                    value,
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=value_color,
                ),
            ],
            spacing=theme.SPACE_XS,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        expand=True,
        height=_CELL_H,
        bgcolor=_score_color(got, max_marks),
        border_radius=theme.CARD_RADIUS,
        # 边框常在，只换颜色：只在选中时加边框会让格子宽出 4px，整行跟着抖。
        border=ft.Border.all(
            2, theme.PRIMARY if active else ft.Colors.TRANSPARENT,
        ),
        alignment=ft.Alignment.CENTER,
        on_click=None if pending else _open_detail(ctx, qid),
    )


def _max_marks(
    ctx: MarkTabContext, qid: str, qr: QuestionResult | None,
) -> int:
    """这题的满分。还没批到时结果里没有，回 paper_config 拿。"""
    if qr is not None:
        return qr.max
    pc = ctx.state.paper_config
    if pc is None or qid not in pc.questions:
        return 0
    return pc.questions[qid].max_marks


# ── 详情浮层 ──────────────────────────────────────────────────────

def build_detail_panel(ctx: MarkTabContext) -> ft.Container:
    """建一次的浮层外壳，内容由 :func:`refresh_detail_panel` 填。

    调用方（``build_mark_tab``）把它放进 Stack 的上层，只定它贴哪个角，**不给
    高度** —— 面板贴着内容长，一题两条判定就只有那么高。定死高度会让短的那些
    题底下拖一大截空白。
    """
    body = ft.Column(spacing=theme.SPACE_XS, tight=True)
    ctx.detail_body = body
    return ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.CupertinoIcons.XMARK,
                            icon_size=16,
                            tooltip="收起",
                            on_click=lambda _: _close_detail(ctx),
                        ),
                    ],
                    spacing=0,
                ),
                body,
            ],
            spacing=0,
            tight=True,
        ),
        width=_PANEL_W,
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.card_shadow(),
        padding=ft.Padding(
            left=theme.SPACE_LG, right=theme.SPACE_LG,
            top=theme.SPACE_XS, bottom=theme.SPACE_LG,
        ),
        right=0,
        top=0,
        visible=False,
    )


def refresh_detail_panel(ctx: MarkTabContext) -> None:
    """把 ``ctx.detail_question`` 那一题的明细填进浮层，或收起浮层。

    每次 ``rebuild()`` 都要调一次：浮层活在 content 之外，rebuild 重画不到它，
    而调分改的正是浮层里显示的数字。
    """
    panel, body = ctx.detail_panel, ctx.detail_body
    if panel is None or body is None:
        return
    qr = next(
        (
            r for r in ctx.state.grading_results
            if r.question == ctx.detail_question
        ),
        None,
    )
    if qr is None:
        # 选中的题没了（换了卷子、重批一遍）——收起，别留着一块过期的明细。
        ctx.detail_question = None
        panel.visible = False
        return
    body.controls.clear()
    body.controls.extend(_detail_controls(ctx, qr))
    panel.visible = True


def _detail_controls(ctx: MarkTabContext, qr: QuestionResult) -> list[ft.Control]:
    question = qr.question
    max_marks = qr.max
    ov = ctx.state.score_overrides.get(question, qr.total)

    controls: list[ft.Control] = [
        ft.Row(
            [
                ft.Container(
                    ft.Text(
                        question,
                        size=theme.BODY, weight=ft.FontWeight.BOLD,
                    ),
                    bgcolor=_score_color(ov, max_marks),
                    border_radius=theme.CARD_RADIUS,
                    padding=ft.Padding(
                        left=10, right=10, top=3, bottom=3,
                    ),
                ),
                ft.Text(
                    f"{ov:g}/{max_marks}",
                    size=theme.SECTION, weight=ft.FontWeight.BOLD,
                ),
            ],
            spacing=theme.SPACE_SM,
        ),
        ft.Divider(height=theme.SPACE_LG),
    ]

    for m in qr.marks:
        controls.append(ft.Row(
            [
                ft.Icon(
                    ft.CupertinoIcons.CHECKMARK_CIRCLE_FILL if m.awarded
                    else ft.CupertinoIcons.XMARK_CIRCLE_FILL,
                    color=theme.SUCCESS if m.awarded else theme.DANGER,
                    size=18,
                ),
                ft.Text(
                    f"{m.code}: {m.reason}",
                    size=theme.BODY,
                    expand=True,  # wrap long reasons, don't overflow
                ),
            ],
            spacing=theme.SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ))

    if qr.comment:
        controls.append(ft.Container(
            ft.Row(
                [
                    ft.Icon(
                        ft.CupertinoIcons.CHAT_BUBBLE,
                        color=theme.PRIMARY, size=16,
                    ),
                    ft.Text(
                        qr.comment,
                        color=theme.MUTED, size=theme.CAPTION,
                        expand=True,  # wrap long comments
                    ),
                ],
                spacing=theme.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.Padding(
                left=0, right=0, top=theme.SPACE_SM, bottom=theme.SPACE_SM,
            ),
        ))

    override_handler = _override_handler(ctx, question, max_marks)
    controls.append(ft.TextField(
        label="调分", value=f"{ov:g}", width=110,
        label_style=theme.field_label_style(),
        keyboard_type=ft.KeyboardType.NUMBER,
        dense=True,
        on_submit=override_handler,
        on_blur=override_handler,
    ))
    return controls


def _open_detail(
    ctx: MarkTabContext, question: str,
) -> Callable[[ft.Event[ft.Container]], None]:
    def _click(_: ft.Event[ft.Container]) -> None:
        ctx.detail_question = question
        ctx.rebuild()  # 重画格子的选中边框；浮层由 rebuild 顺带刷新

    return _click


def _close_detail(ctx: MarkTabContext) -> None:
    ctx.detail_question = None
    ctx.rebuild()


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
