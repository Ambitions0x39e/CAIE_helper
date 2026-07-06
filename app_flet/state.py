from __future__ import annotations

from dataclasses import dataclass, field

from core.settings import GraderConfig, MailConfig
from core.storage import CSVStore
from modules.ms_parser import PaperConfig
from modules.page_segmenter import PageClip


@dataclass
class AppState:
    """Mutable application state shared across all tabs."""

    store: CSVStore = field(default_factory=CSVStore)

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
    paper_type: str | None = None

    # Mark tab — Math grading
    answer_pdf_path: str | None = None
    answer_total_pages: int = 0
    auto_pages: dict[str, str] = field(default_factory=dict)
    auto_clips: dict[str, list[PageClip]] = field(default_factory=dict)
    auto_pages_done: bool = False
    deleted_questions: set[str] = field(default_factory=set)
    grading_results: list[object] = field(default_factory=list)
    score_overrides: dict[str, float] = field(default_factory=dict)
    grading_confirmed: bool = False

    # Mark tab — MCQ grading
    mcq_qp_path: str | None = None
    mcq_qp_filename: str | None = None
    mcq_detected: dict[str, str] = field(default_factory=dict)
    mcq_undetected: list[str] = field(default_factory=list)
    mcq_confirmed: bool = False
