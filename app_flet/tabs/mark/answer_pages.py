"""The answer paper's per-question page assignment — Step 1's other output.

Segmentation runs as part of Step 1 (alongside the mark-scheme parse), so
this section only reports what it found and lets the user correct it.
"""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app_flet import theme
from app_flet.tabs.mark.context import MarkTabContext


def build_answer_pages(ctx: MarkTabContext) -> list[ft.Control]:
    state = ctx.state
    controls: list[ft.Control] = [
        ft.Divider(),
        ft.Text("答卷分页", size=18, weight=ft.FontWeight.BOLD),
    ]

    matched_count = len(state.auto_pages)
    total_q = (
        len(state.paper_config.questions) if state.paper_config else 0
    )
    # Partial detection is the common failure, not an edge case — warn on any
    # shortfall rather than only when nothing at all was found.
    incomplete = matched_count < total_q
    controls.append(ft.Container(
        ft.Row([
            ft.Icon(
                ft.CupertinoIcons.EXCLAMATIONMARK_CIRCLE_FILL if incomplete
                else ft.CupertinoIcons.INFO_CIRCLE_FILL,
                color=theme.WARNING if incomplete else theme.PRIMARY,
                size=18,
            ),
            ft.Text(
                f"PDF 共 {state.answer_total_pages} 页"
                f" | 自动识别 {matched_count}/{total_q} 题",
                size=13,
            ),
        ]),
        bgcolor=theme.WARNING_TINT if incomplete else theme.PRIMARY_TINT,
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
            color=theme.WARNING, size=12,
        ))

    controls.append(ft.Text(
        "为每题指定页码:", size=14, weight=ft.FontWeight.BOLD,
    ))

    pc = state.paper_config
    if pc is None:
        return controls

    ctx.page_inputs.clear()
    cells: list[ft.Control] = []
    for qid, qcfg in pc.questions.items():
        if qid in state.deleted_questions:
            continue
        default_val = state.auto_pages.get(qid, "")
        # An empty box here means detection failed for this question — colour
        # it so it reads as "type a page number", not as a glitch.
        needs_input = not default_val
        tf = ft.TextField(
            label=f"{qid} ({qcfg.max_marks}m)",
            label_style=ft.TextStyle(
                color=theme.WARNING_STRONG if needs_input else None,
            ),
            value=default_val,
            hint_text="待填" if needs_input else "例: 2,3",
            border_color=theme.WARNING if needs_input else None,
            expand=True,
            dense=True,
        )
        ctx.page_inputs[qid] = tf

        # Fixed-width cell so the responsive grid can compute columns; the
        # TextField expands to fill it, leaving room for the delete button.
        cells.append(ft.Container(
            ft.Row([
                tf,
                ft.IconButton(
                    ft.CupertinoIcons.XMARK, tooltip=f"移除 {qid}",
                    icon_size=18, on_click=_delete_handler(ctx, qid),
                ),
            ], spacing=0),
            width=158,  # TextField + IconButton (~48)
        ))

    controls.extend(ctx.responsive_grid(cells, 158))
    return controls


def _delete_handler(
    ctx: MarkTabContext, qid: str,
) -> Callable[[ft.Event[ft.IconButton]], None]:
    def _handler(_: ft.Event[ft.IconButton]) -> None:
        ctx.state.deleted_questions.add(qid)
        ctx.rebuild()

    return _handler
