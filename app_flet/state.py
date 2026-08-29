from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.models import PaperType
from core.settings import GraderConfig, MailConfig
from core.storage import CSVStore
from modules.marking.ms_parser import PaperConfig
from modules.marking.page_segmenter import PageClip

if TYPE_CHECKING:
    from flet_pdf_render import PdfRenderer

    # Type-only: modules.marking.grader imports `openai` at module level, and
    # nothing else here should pull that in just to hold a result list.
    from modules.marking.grader import QuestionResult


@dataclass
class AppState:
    """Mutable application state shared across all tabs."""

    store: CSVStore = field(default_factory=CSVStore)

    # Native PDF renderer service (pdfrx-backed; added to page.services once).
    pdf_renderer: PdfRenderer | None = None

    # Credentials (loaded from .env on startup, editable via settings)
    mail_config: MailConfig | None = None
    grader_config: GraderConfig | None = None

    # Download tab
    last_downloaded_id: str | None = None
    last_downloaded_qp: str | None = None

    # Manage tab
    manage_view: str = "Database"
    hide_completed: bool = True

    # Mark tab — shared
    paper_config: PaperConfig | None = None
    #: How the current ``paper_config`` was parsed — not what the Step 1
    #: radio shows right now (``MarkTabContext.paper_type``).
    paper_type: PaperType | None = None
    # True when paper_config was served from the on-disk MS cache
    # (drives the "cached result — re-parse?" hint in Step 1).
    ms_from_cache: bool = False
    # Guard: at most one grading request (Math grade / MCQ detect) may be
    # in flight at a time — both hit the grader API from a worker thread.
    grading_in_progress: bool = False

    # Mark tab — Math grading
    answer_pdf_path: str | None = None
    answer_total_pages: int = 0
    auto_pages: dict[str, str] = field(default_factory=dict)
    auto_clips: dict[str, list[PageClip]] = field(default_factory=dict)
    auto_pages_done: bool = False
    # Questions the segmenter could not locate — the user must type their
    # page numbers by hand. Kept separate from auto_pages so the UI can
    # report the real shortfall instead of counting phantom entries.
    unmatched_questions: list[str] = field(default_factory=list)
    deleted_questions: set[str] = field(default_factory=set)
    grading_results: list[QuestionResult] = field(default_factory=list)
    #: paper_id the current grading_results actually belong to (None for an
    #: uploaded mark scheme). Captured when grading runs, not read from the
    #: paper picker at confirm time — the picker stays interactive after
    #: grading finishes, so it can no longer be trusted to name the paper
    #: these results were graded against.
    graded_paper_id: str | None = None
    score_overrides: dict[str, float] = field(default_factory=dict)
    grading_confirmed: bool = False
    # Last grading failure, shown as a persistent banner (a snackbar toast
    # auto-dismisses and is easy to miss on a long-running grade).
    grading_error: str | None = None

    # Mark tab — MCQ grading
    mcq_qp_path: str | None = None
    mcq_qp_filename: str | None = None
    mcq_detected: dict[str, str] = field(default_factory=dict)
    mcq_undetected: list[str] = field(default_factory=list)
    mcq_confirmed: bool = False
