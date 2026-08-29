"""Assembles the Mark tab from its sections and owns the rebuild loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

from app_flet.tabs.mark.answer_pages import build_answer_pages
from app_flet.tabs.mark.context import MarkTabContext
from app_flet.tabs.mark.grade_step import build_grade_step
from app_flet.tabs.mark.mcq import build_mcq_flow
from app_flet.tabs.mark.results import build_results
from app_flet.tabs.mark.setup_step import build_setup_step
from core.models import PaperType

if TYPE_CHECKING:
    from app_flet.state import AppState


def build_mark_tab(
    page: ft.Page,
    state: AppState,
    show_snack: Callable[[str, str], None],
    ms_picker: ft.FilePicker,
    answer_picker: ft.FilePicker,
) -> ft.Container:
    content = ft.Column(spacing=12)
    ctx = MarkTabContext(
        page=page,
        state=state,
        show_snack=show_snack,
        ms_picker=ms_picker,
        answer_picker=answer_picker,
        content=content,
        thinking=(
            state.grader_config.enable_thinking
            if state.grader_config else False
        ),
    )

    def rebuild() -> None:
        ctx.sync_page_inputs()
        content.controls.clear()
        content.controls.extend(build_setup_step(ctx))

        if ctx.parsing:
            # Analysis in flight: show only the progress controls, nothing
            # below — the sections underneath describe a stale paper.
            content.controls.extend(
                c for c in (ctx.parse_bar, ctx.parse_text, ctx.scan_text)
                if c is not None
            )
            page.update()
            return

        if state.paper_config:
            if state.paper_type is PaperType.MATH:
                if state.answer_pdf_path and state.auto_pages_done:
                    content.controls.extend(build_answer_pages(ctx))
                    content.controls.extend(build_grade_step(ctx))
                if state.grading_results:
                    content.controls.extend(build_results(ctx))
            elif state.paper_type is PaperType.MCQ:
                content.controls.extend(build_mcq_flow(ctx))

        page.update()

    ctx.rebuild = rebuild
    rebuild()
    return ft.Container(content, padding=20)
