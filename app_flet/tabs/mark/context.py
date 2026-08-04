"""Shared state for the Mark tab's sections.

``build_mark_tab`` used to be one ~1,500-line closure in which every helper
reached its neighbours' state through ``list``-of-one refs — the only way a
nested function can rebind an outer name. Now that the sections live in
separate modules that trick is neither needed nor readable: the refs are
plain attributes on this object, which each section takes as its first
argument.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import flet as ft

from core.models import PaperType

if TYPE_CHECKING:
    from app_flet.state import AppState
    from modules.marking.page_segmenter import ScannedDocument


def _noop() -> None:
    """Placeholder ``rebuild`` until :func:`build_mark_tab` wires the real one."""


@dataclass
class MarkTabContext:
    """Everything the Mark tab's sections share."""

    # ── Handed in by the app shell ─────────────────────────────────
    page: ft.Page
    state: AppState
    show_snack: Callable[[str, str], None]
    ms_picker: ft.FilePicker
    answer_picker: ft.FilePicker
    content: ft.Column

    #: Rebuilds the whole tab; assigned once the section builders are known.
    #: Every handler calls it after mutating state.
    rebuild: Callable[[], None] = _noop

    # ── Step 1 — what to analyse ───────────────────────────────────
    ms_source: str = "downloaded"
    paper_type: PaperType = PaperType.MATH
    #: ``None`` = auto-detect from the MS PDF; a number is a manual override.
    start_page: int | None = None
    selected_syllabus: str | None = None
    selected_paper: str | None = None
    ms_upload_path: str | None = None
    #: The answer PDF picked in Step 1 (Math: the answer paper; MCQ: the
    #: annotated QP). Kept here rather than pushed into AppState until the
    #: analysis succeeds, so switching paper type keeps the chosen file.
    answer_path: str | None = None
    #: Last ``scan_document`` result, keyed by path — re-pressing 解析 after
    #: only the mark scheme changed shouldn't re-read the whole answer PDF.
    scanned: tuple[str, ScannedDocument] | None = None

    # ── Step 1 — analysis in flight ────────────────────────────────
    #: While an analysis runs, the tab collapses to Step 1 plus these
    #: controls — otherwise a re-parse from the last step would append them
    #: below the stale question list, buried off-screen.
    parsing: bool = False
    parse_bar: ft.ProgressBar | None = None
    parse_text: ft.Text | None = None
    #: Status line for the answer scan running alongside the MS parse.
    scan_text: ft.Text | None = None

    # ── Step 2 — grading ───────────────────────────────────────────
    thinking: bool = False
    grade_questions: list[str] = field(default_factory=list)
    grade_questions_seeded: bool = False

    # ── Live widgets that get read back on rebuild ─────────────────
    page_inputs: dict[str, ft.TextField] = field(default_factory=dict)
    mcq_manual_inputs: dict[str, ft.TextField] = field(default_factory=dict)
    manual_answer_values: dict[str, str] = field(default_factory=dict)

    #: Step 1 pushes UI updates from two worker threads at once. Flet's
    #: ``Session.patch_control`` diffs the control subtree and mutates its
    #: control index with no locking of its own, so concurrent
    #: ``page.update()`` calls would race — see :meth:`ui_update`.
    _ui_lock: threading.Lock = field(default_factory=threading.Lock)

    # ── Helpers every section needs ────────────────────────────────

    def ui_update(self) -> None:
        """``page.update()``, safe to call from any worker thread."""
        with self._ui_lock:
            self.page.update()

    def sync_page_inputs(self) -> None:
        """Snapshot live page-number edits back into ``AppState``.

        The answer-pages section rebuilds fresh TextFields from
        ``state.auto_pages`` on every rebuild, so without this an unrelated
        rebuild (a checkbox toggle, a deleted question) would wipe out page
        numbers the user had just typed.
        """
        for qid, tf in self.page_inputs.items():
            val = (tf.value or "").strip()
            if val:
                self.state.auto_pages[qid] = val

    def responsive_grid(
        self,
        cells: list[ft.Control],
        cell_width: int,
        spacing: int = 8,
    ) -> list[ft.Control]:
        """Chunk fixed-width cells into as many columns as the screen fits.

        Deterministic, unlike ``Row(wrap=True)`` — which collapsed the
        nested-Row page inputs into a single overlapping column on iPad. The
        column count tracks ``page.width``, so it adapts from phone (2 cols)
        to iPad Pro (5-7).
        """
        avail = int(self.page.width or 1024) - 40  # tab padding, 20/side
        cols = max(1, (avail + spacing) // (cell_width + spacing))
        return [
            ft.Row(cells[i : i + cols], spacing=spacing)
            for i in range(0, len(cells), cols)
        ]

    def ms_path(self) -> str | None:
        """Path of the mark scheme to parse, per the current source choice."""
        if self.ms_source == "upload":
            return self.ms_upload_path
        if self.selected_paper is None:
            return None
        try:
            records = self.state.store.load_all()
        except ValueError:
            return None
        target = next(
            (r for r in records if r.paper_id == self.selected_paper),
            None,
        )
        return target.ms_path if target else None
