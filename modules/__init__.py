from modules.mcq_parser import detect_student_answers, parse_mcq_mark_scheme, score_mcq_answers
from modules.downloader import (
    DownloadRequest,
    DownloadResult,
    DownloadSource,
    PaperDownloader,
)
from modules.mailer import GoodNotesMailer, MailRequest, MailResult
from modules.manager import (
    DeleteRequest,
    DeleteResult,
    OpenResult,
    PaperManager,
    ScoreUpdate,
    UpdateResult,
)
from modules.page_segmenter import (
    PageClip,
    QuestionRegion,
    segment_questions,
    validate_regions,
)
from modules.pdf_renderer import render_pages_from_path, render_pdf_pages
from modules.visualizer import PaperVisualizer

__all__ = [
    "detect_student_answers",
    "parse_mcq_mark_scheme",
    "score_mcq_answers",
    "DownloadRequest",
    "DownloadResult",
    "DownloadSource",
    "PaperDownloader",
    "GoodNotesMailer",
    "MailRequest",
    "MailResult",
    "DeleteRequest",
    "DeleteResult",
    "OpenResult",
    "PaperManager",
    "ScoreUpdate",
    "UpdateResult",
    "PageClip",
    "QuestionRegion",
    "segment_questions",
    "validate_regions",
    "PaperVisualizer",
    "render_pdf_pages",
    "render_pages_from_path",
]