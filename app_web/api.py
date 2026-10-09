"""The Python side of `window.pywebview.api`.

Every method here is a thin adapter and nothing more: take JSON, build the
Pydantic model the backend already validates against, call it, hand back
`model_dump(mode="json")`. The decisions live in `core/` and `modules/`, which
are covered by their own tests — anything resembling a business rule appearing
in this file means it was put in the wrong layer.

**One error channel.** The backend reports failure two different ways: the
operations return a result object with `success` / `error`, while constructing
a request model raises `ValidationError`. A raised exception would reach JS as
a rejected promise, so the frontend would need to handle both a rejection and a
`success: false` payload for the same class of user mistake — a mistyped paper
id. `_invalid` folds validation failures into the result shape instead, and the
frontend only ever reads `success`.
"""
from __future__ import annotations

import datetime
import logging
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import webview
from pydantic import ValidationError

from app_web.jobs import push, start
from core.config_store import ConfigStore
from core.gt_parser import GTParser
from core.models import ERROR_TYPES, AttemptRecord, MistakeRecord, PaperType
from core.settings import GraderConfig, MailConfig, app_settings
from core.storage import AttemptStore, CSVStore, ExportStore, MistakeStore
from modules.downloader import DownloadRequest, PaperDownloader, query_available
from modules.exports import build_record
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import DeleteRequest, PaperManager, ScoreUpdate
from modules.marking.answer_sheet import build_answer_sheet
from modules.marking.attempts import attempts_from_results
from modules.marking.grader import QuestionResult
from modules.marking.mcq_parser import (
    detect_student_answers,
    score_mcq_answers,
)
from modules.marking.mistakes import (
    distinct_topic_keys,
    mistakes_from_results,
    retag,
    subject_id_of,
    to_csv,
)
from modules.marking.ms_parser import (
    PaperConfig,
    downloaded_paper_id,
    ms_cache_exists,
    parse_mark_scheme,
    resolve_ms_start_page,
)
from modules.marking.page_segmenter import ScannedDocument, match_scanned, scan_document
from modules.marking.renderer import LocalRenderer
from modules.marking.sheet import Sheet, SheetItem, grade_sheet
from modules.marking.syllabus_fetch import fetch_syllabus
from modules.marking.syllabus_parser import (
    delete_syllabus,
    detect_subject_id,
    load_syllabus,
    parse_syllabus,
    resolve_grading_type,
    stored_syllabuses,
    syllabus_path,
)
from modules.marking.workflow import (
    collect_page_assignments,
    component_paper_number,
    merge_mcq_answers,
    regions_to_page_map,
    summarise_scores,
    topics_for_paper,
)
from modules.practice import PracticeRequest, build_practice, component_topics
from modules.tutor import read_notes, refresh_notes
from modules.updater import AppUpdater, current_app_version, format_progress

_log = logging.getLogger("cie_helper.api")

#: Serialises note rewrites: two papers of one component confirmed back to
#: back must not both read the same old note and race to replace it.
_notes_lock = threading.Lock()

#: What a failed call looks like. Mirrors DownloadResult/QueryResult so the
#: frontend has exactly one shape to read.
type Payload = dict[str, Any]

#: Bailian's OpenAI-compatible endpoint — the default the form offers.
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class _Analysis:
    """What one 解析 produced, held between the Mark tab's steps.

    Server-side rather than in the page: the parse costs a vision-model call,
    so a reload must not throw it away.
    """

    config: PaperConfig
    doc: ScannedDocument | None
    paper_type: PaperType
    answer_path: str | None

    @property
    def paper_id(self) -> str:
        """The downloaded id when the cover id converts, else the cover id."""
        return downloaded_paper_id(self.config.paper_id) or self.config.paper_id


def _invalid(exc: ValidationError) -> Payload:
    """A ValidationError as the same payload a failed operation returns.

    Pydantic reports every failing field; the frontend shows one line, so take
    the first message. `ctx.error` carries the message a custom validator
    raised (``paper_id must match …``) without Pydantic's "Value error, "
    prefix in front of it.
    """
    first = exc.errors()[0]
    ctx = first.get("ctx") or {}
    return {"success": False, "error": str(ctx.get("error") or first["msg"])}


def _save_to_chosen_file(
    data: bytes, suggested: str, file_types: tuple[str, ...],
) -> Payload:
    """Ask the user where to put *data*, then write it there.

    The dialog is the host's own, so nothing is written until a destination is
    picked and cancelling is a normal outcome rather than an error.
    """
    window = webview.active_window()
    if window is None:
        return {"success": False, "error": "没有窗口可以弹出保存对话框。"}
    chosen = window.create_file_dialog(
        webview.FileDialog.SAVE, save_filename=suggested, file_types=file_types,
    )
    if not chosen:
        return {"success": False, "cancelled": True, "error": None}
    path = chosen if isinstance(chosen, str) else chosen[0]
    Path(path).write_bytes(data)
    return {"success": True, "path": path}


class Api:
    """Exposed to JS as `window.pywebview.api.*` — public methods only."""

    def __init__(self) -> None:
        # Built once and shared: CSVStore reads ~/.cie_helper/data.csv and
        # ConfigStore reads data/syllabus_config.json, and neither wants to be
        # re-read per call.
        app_settings.init_dirs()
        self._store = CSVStore()
        self._config = ConfigStore()
        self._downloader = PaperDownloader(self._store)
        self._manager = PaperManager(self._store)
        self._mistakes = MistakeStore()
        self._attempts = AttemptStore()
        self._exports = ExportStore()
        self._updater = AppUpdater()
        #: The installer the last check pointed at. The page never names a
        #: URL itself, so it cannot make the app download anything else.
        self._update_url: str | None = None
        # None when .env carries no SMTP credentials — a normal state, not an
        # error. The UI hides the GoodNotes affordance rather than failing it.
        self._mail = MailConfig.try_load()
        self._analysis: _Analysis | None = None
        #: The last run graded and what came back, held until confirmed.
        self._sheet: Sheet | None = None
        self._results: list[QuestionResult] = []
        #: Letters the VL read off the annotated QP, before any manual
        #: overlay. Kept apart from the manual boxes so re-scoring does
        #: not need another detection pass.
        self._mcq_detected: dict[str, str] = {}
        #: The last practice set built, held until the user picks where to
        #: save it — the build is minutes of work a cancelled dialog must not
        #: throw away.
        self._practice_pdf: bytes | None = None
        self._practice_name = "practice.pdf"

    # -- health --------------------------------------------------------------

    def ping(self) -> str:
        return "pong"

    # -- shell ---------------------------------------------------------------

    def open_external(self, url: str) -> bool:
        """Open *url* in the user's browser. Never navigates this window.

        Only http(s) gets through: ``file:`` would hand the page a way to launch
        local content, and ``javascript:`` a way to run in whatever the browser
        opens it with.
        """
        if urlparse(url).scheme not in ("http", "https"):
            return False
        webbrowser.open(url)
        return True

    # -- download ------------------------------------------------------------

    def syllabuses(self) -> list[Payload]:
        """Every configured syllabus, for the subject picker."""
        return [s.model_dump(mode="json") for s in self._config.load_all()]

    def query_session(self, subject: str, year: str, season: str) -> Payload:
        """List what one subject/year/season holds, marking what we already have."""
        result = query_available(subject, year, season, self._store)  # type: ignore[arg-type]
        return result.model_dump(mode="json")

    def download_paper(
        self, paper_id: str, source: str = "CIEFrank", insert: bool = False,
    ) -> Payload:
        """Fetch a paper's QP and MS (and its insert when asked), then record it."""
        try:
            request = DownloadRequest(paper_id=paper_id, source=source)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _invalid(exc)
        return self._downloader.download(request, insert=insert).model_dump(
            mode="json",
        )

    def record_paper(self, paper_id: str) -> Payload:
        """Register a paper already sitting in the store without downloading."""
        return self._downloader.record_only(paper_id).model_dump(mode="json")

    def downloaded_ids(self) -> list[str]:
        """Paper ids already in the store, for marking what is on disk."""
        try:
            return [r.paper_id for r in self._store.load_all()]
        except ValueError:
            # A malformed row is the store's problem to report elsewhere; here
            # it only means "cannot mark anything", which is not worth failing.
            return []

    # -- manage: papers ------------------------------------------------------

    def papers(self) -> list[Payload]:
        """Every stored paper. Drives 总览's tally and 整理's list alike."""
        return [r.model_dump(mode="json") for r in self._store.load_all()]

    def submit_score(
        self, paper_id: str, score_raw: float, score_total: float,
    ) -> Payload:
        """Record a paper's marks, which also moves it to Completed."""
        try:
            update = ScoreUpdate(
                paper_id=paper_id, score_raw=score_raw, score_total=score_total,
            )
        except ValidationError as exc:
            return _invalid(exc)
        return self._manager.submit_score(update).model_dump(mode="json")

    def delete_paper(
        self, paper_id: str, delete_local_files: bool = False,
    ) -> Payload:
        """Drop a paper's row, and its PDFs when asked."""
        try:
            request = DeleteRequest(
                paper_id=paper_id, delete_local_files=delete_local_files,
            )
        except ValidationError as exc:
            return _invalid(exc)
        return self._manager.delete(request).model_dump(mode="json")

    def open_pdf(self, path: str) -> Payload:
        """Hand a stored PDF to the OS viewer."""
        return self._manager.open_pdf(path).model_dump(mode="json")

    # -- manage: mistakes ----------------------------------------------------

    def mistakes(self) -> list[Payload]:
        """Every recorded lost mark, oldest first (the store is append-only)."""
        return [r.model_dump(mode="json") for r in self._mistakes.load_all()]

    def mistake_topic_keys(self) -> list[str]:
        """The filter list: every `<syllabus> · <topic>` present, 未分类 last."""
        return distinct_topic_keys(self._mistakes.load_all())

    def topics_for(self, paper_id: str) -> dict[str, str] | None:
        """Topic id → name for one paper, for the retag picker.

        None (not an empty dict) whenever topics cannot be resolved — no stored
        syllabus, or a component the syllabus does not map, such as a practical.
        """
        return topics_for_paper(load_syllabus(subject_id_of(paper_id)), paper_id)

    def retag_mistake(
        self, paper_id: str, question_id: str, topic_id: str | None,
    ) -> Payload:
        """Re-file one mistake under a different topic; None clears the tag.

        The store is append-only and has no update, so the whole file is
        rewritten with the one row replaced. The question's attempt rows are
        re-filed with it, or a topic's loss rate would count the mistake under
        one topic and the attempt under another.
        """
        records = self._mistakes.load_all()
        topics = self.topics_for(paper_id) or {}
        hit = False
        rewritten = []
        for record in records:
            if record.paper_id == paper_id and record.question_id == question_id:
                rewritten.append(retag(record, topic_id, topics))
                hit = True
            else:
                rewritten.append(record)
        if not hit:
            return {
                "success": False,
                "error": f"找不到这条错题：{paper_id} {question_id}",
            }
        self._mistakes.save_all(rewritten)
        self._attempts.save_all([
            retag(a, topic_id, topics)
            if a.paper_id == paper_id and a.question_id == question_id else a
            for a in self._attempts.load_all()
        ])
        return {"success": True}

    def _chosen_mistakes(self, indices: list[int]) -> list[MistakeRecord]:
        """The ticked rows, in store order.

        Keyed by position rather than by `paper_id`/`question_id`: the store is
        append-only, so a position is stable, while a re-grade repeats the same
        paper and question and would make a key ambiguous.
        """
        records = self._mistakes.load_all()
        return [records[i] for i in sorted(indices) if 0 <= i < len(records)]

    def export_mistakes_csv(self, indices: list[int]) -> Payload:
        """Write the selection to a file the user picks. Same columns as the
        store's own file, so it reads back into anything that reads the store."""
        chosen = self._chosen_mistakes(indices)
        if not chosen:
            return {"success": False, "error": "请先勾选要导出的错题"}
        # utf-8-sig: Excel reads a plain UTF-8 CSV as mojibake, and every
        # comment in here is Chinese.
        return _save_to_chosen_file(
            to_csv(chosen).encode("utf-8-sig"), "mistakes.csv", ("CSV (*.csv)",),
        )

    def export_mistakes_pdf(self, indices: list[int]) -> Payload:
        """Crop the selected questions out of their QPs into a paper to redo,
        record the export, and save the paper where the user picks.

        Warnings come back alongside the file rather than instead of it:
        exporting nine of ten questions is worth doing as long as the tenth is
        named. Only a total failure is an error.
        """
        chosen = self._chosen_mistakes(indices)
        if not chosen:
            return {"success": False, "error": "请先勾选要导出的错题"}
        papers = self._store.load_all()
        qp = {r.paper_id: r.qp_path for r in papers}
        ms = {r.paper_id: r.ms_path for r in papers}
        subjects = sorted({subject_id_of(r.paper_id) for r in chosen})
        try:
            manifest, data, warnings = build_record(
                "mistakes", f"错题 · {' '.join(subjects)}", chosen, qp, ms,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        self._exports.write(manifest, data)
        saved = _save_to_chosen_file(
            data, f"{manifest.export_id}.pdf", ("PDF (*.pdf)",),
        )
        return {**saved, "warnings": warnings}

    def export_mistakes_answers(self, indices: list[int]) -> Payload:
        """Lay the selected questions' mark scheme out as an answer sheet.

        Reads the parse cached during grading — no PDF work and no second
        vision-model call.
        """
        chosen = self._chosen_mistakes(indices)
        if not chosen:
            return {"success": False, "error": "请先勾选要导出的错题"}
        ms = {r.paper_id: r.ms_path for r in self._store.load_all()}
        try:
            data, warnings = build_answer_sheet(chosen, ms)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        saved = _save_to_chosen_file(data, "answers.pdf", ("PDF (*.pdf)",))
        return {**saved, "warnings": warnings}

    # -- practice ------------------------------------------------------------

    def practice_topics(self, subject: str, component: str) -> Payload:
        """The topics this component examines, fetching the syllabus if needed."""
        syllabus = load_syllabus(subject)
        if syllabus is None and subject.isdigit():
            syllabus = fetch_syllabus(subject)
        topics = component_topics(syllabus, component)
        if not topics:
            return {
                "success": False,
                "error": f"{subject} 的大纲里没有卷 {component} 的 topic",
            }
        return {"success": True, "topics": topics}

    def start_practice(
        self,
        subject: str,
        component: str,
        from_year: int,
        from_season: str,
        to_year: int,
        to_season: str,
        topic_ids: list[str],
    ) -> Payload:
        """Build the set on a worker thread; the PDF waits for save_practice."""
        try:
            request = PracticeRequest(
                subject=subject, component=component,
                from_year=from_year, from_season=from_season,
                to_year=to_year, to_season=to_season, topic_ids=topic_ids,
            )
        except ValidationError as exc:
            return _invalid(exc)
        config = GraderConfig.try_load()
        if config is None:
            return {
                "success": False,
                "error": "还没有配置 Grader API，先去【设置】填。",
            }
        topics = self.practice_topics(subject, component)
        if not topics["success"]:
            return topics

        def work() -> None:
            self._practice_pdf = None
            manifest, data, warnings = build_practice(
                request, topics["topics"],
                store=self._store, downloader=self._downloader,
                config=config, renderer=LocalRenderer(),
                on_progress=lambda stage, done, total, paper: push({
                    "type": "practice_progress", "stage": stage,
                    "done": done, "total": total, "paper": paper,
                }),
            )
            self._exports.write(manifest, data)
            self._practice_pdf = data
            self._practice_name = f"{manifest.export_id}.pdf"
            push({
                "type": "practice_ready",
                "count": len(manifest.questions),
                "warnings": warnings,
            })

        return start("练习", work)

    def save_practice(self) -> Payload:
        """Ask where to put the last practice set, then write it."""
        if self._practice_pdf is None:
            return {"success": False, "error": "还没有生成练习"}
        return _save_to_chosen_file(
            self._practice_pdf, self._practice_name, ("PDF (*.pdf)",),
        )

    # -- exports -------------------------------------------------------------

    def exports(self) -> list[Payload]:
        """Every export record, newest first — without the snapshot, which
        only grading reads."""
        return [
            {
                **m.model_dump(mode="json", exclude={"papers"}),
                "question_count": len(m.questions),
            }
            for m in self._exports.load_all()
        ]

    def save_export_blank(self, export_id: str) -> Payload:
        """Save an export's blank paper again, where the user picks."""
        try:
            data = self._exports.blank_pdf(export_id)
        except (OSError, ValueError, KeyError) as exc:
            return {"success": False, "error": f"读不了这条导出记录：{exc}"}
        return _save_to_chosen_file(data, f"{export_id}.pdf", ("PDF (*.pdf)",))

    # -- mark ----------------------------------------------------------------

    def pick_pdf(self) -> str | None:
        """Host file dialog. Returns the chosen path, or None if cancelled.

        The filter is fixed, and has to be. `file_types` entries are validated
        against ``^([\\w ]+)\\(...\\)$``, so the description may hold word
        characters and spaces and nothing else — a bracket anywhere in it
        raises `ValueError` before a dialog is ever shown. It reads like a
        place to put a caption, and it is not one: `create_file_dialog` takes
        no title, so what the user is choosing is said by the button that
        opened this and by the filename shown beside it.
        """
        window = webview.active_window()
        if window is None:
            return None
        chosen = window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("PDF (*.pdf)",),
        )
        if not chosen:
            return None
        return chosen if isinstance(chosen, str) else chosen[0]

    def grading_type(self, ms_path: str) -> str | None:
        """The grading path recorded for this mark scheme, if any.

        Read off the file name (``9702_s25_ms_21``), so an upload saved under
        its CIE name resolves too. None leaves the choice to the user.
        """
        pt = resolve_grading_type(Path(ms_path).stem)
        return pt.value if pt else None

    def start_analysis(
        self,
        ms_path: str,
        paper_type: str,
        answer_path: str | None = None,
        start_page: int | None = None,
        force: bool = False,
    ) -> Payload:
        """Parse the mark scheme and scan the answer paper, concurrently.

        The two are independent — `scan_document` needs only the PDF, since
        question ids first matter in `match_scanned` — so the answer scan runs
        while the (slower) parse is still going, and reports the moment it
        lands rather than waiting for the parse.
        """
        _log.info(
            "start_analysis ms=%s type=%s answer=%s page=%s force=%s",
            ms_path, paper_type, answer_path, start_page, force,
        )
        pt = PaperType(paper_type)

        def work() -> None:
            with ThreadPoolExecutor(max_workers=2) as pool:
                ms_future = pool.submit(
                    self._parse_ms, ms_path, pt, start_page, force,
                )
                scan_future = (
                    pool.submit(scan_document, answer_path)
                    if answer_path
                    else None
                )
                if scan_future is not None:
                    scan_future.add_done_callback(
                        lambda f: push({
                            "type": "scan",
                            "ok": f.exception() is None,
                            "error": str(f.exception() or ""),
                        })
                    )
                config = ms_future.result()
                push({"type": "ms_done"})
                doc = scan_future.result() if scan_future is not None else None

            self._analysis = _Analysis(config, doc, pt, answer_path)
            push({"type": "analysis", **self._analysis_payload()})

        return start("解析", work)

    def _parse_ms(
        self, ms_path: str, pt: PaperType, start_page: int | None, force: bool,
    ) -> PaperConfig:
        resolved = (
            resolve_ms_start_page(ms_path, start_page)
            if pt is not PaperType.MCQ
            else None
        )
        from_cache = not force and ms_cache_exists(ms_path, pt, resolved)
        push({"type": "ms_cache", "cached": from_cache})
        return parse_mark_scheme(
            ms_path,
            paper_type=pt,
            grader_config=GraderConfig.try_load(),
            start_page=resolved,
            on_progress=lambda batch, total: push(
                {"type": "ms_progress", "batch": batch, "total": total},
            ),
            renderer=LocalRenderer(),
            force=force,
        )

    def _analysis_payload(self) -> Payload:
        a = self._analysis
        if a is None:
            return {"ready": False}
        regions, report = (
            match_scanned(a.doc, list(a.config.questions.keys()))
            if a.doc is not None
            else ([], None)
        )
        clips = {r.question_id: [c.model_dump() for c in r.clips] for r in regions}
        return {
            "ready": True,
            "paper_type": a.paper_type.value,
            "paper_id": a.paper_id,
            "total_marks": a.config.total_marks,
            "questions": {
                qid: {"max_marks": q.max_marks, "mark_scheme": q.mark_scheme}
                for qid, q in a.config.questions.items()
            },
            "answer_path": a.answer_path,
            "total_pages": a.doc.page_count if a.doc is not None else 0,
            "matched": report.matched if report else [],
            "clips": clips,
        }

    def analysis(self) -> Payload:
        """The current analysis, so a reload does not lose it."""
        return self._analysis_payload()

    def start_grading(self, question_ids: list[str]) -> Payload:
        """Grade the listed questions, pushing each result as it lands."""
        a = self._analysis
        if a is None:
            return {"success": False, "error": "还没有解析结果"}
        if not a.answer_path:
            return {"success": False, "error": "还没有选择答卷 PDF"}
        config = GraderConfig.try_load()
        if config is None:
            return {
                "success": False,
                "error": "还没有配置 Grader API，先去【设置】填。",
            }

        answer_path = a.answer_path
        regions, _ = (
            match_scanned(a.doc, list(a.config.questions.keys()))
            if a.doc is not None
            else ([], None)
        )
        page_map, clips = regions_to_page_map(regions)
        assignments = collect_page_assignments(page_map)
        sheet = Sheet(
            kind="paper",
            pdf_path=answer_path,
            items=[
                SheetItem(
                    paper_id=a.paper_id, question_id=q,
                    pages=assignments.get(q, []), clips=clips.get(q, []),
                )
                for q in question_ids
            ],
        )

        def work() -> None:
            subject_id = subject_id_of(a.paper_id)
            # A subject nobody imported a syllabus for would grade with every
            # question 未分类, and nothing tells the student to go import one.
            syllabus = load_syllabus(subject_id)
            if syllabus is None and subject_id.isdigit():
                push({"type": "syllabus_fetch", "subject_id": subject_id})
                syllabus = fetch_syllabus(subject_id)
            outcome = grade_sheet(
                config=config,
                sheet=sheet,
                paper_configs={a.paper_id: (a.config, a.paper_type)},
                topics_of=lambda pid: topics_for_paper(syllabus, pid),
                renderer=LocalRenderer(),
                on_progress=lambda done, total, qid: push(
                    {"type": "progress", "done": done, "total": total, "question": qid},
                ),
                on_result=lambda r: push(
                    {"type": "result", "result": r.model_dump(mode="json")},
                ),
            )
            self._sheet = sheet
            self._results = outcome.results
            push({
                "type": "graded",
                "results": [r.model_dump(mode="json") for r in outcome.results],
                "failures": [
                    {"paper_id": f.paper_id, "question": f.question, "error": f.error}
                    for f in outcome.failures
                ],
            })

        return start("批改", work)

    # -- mark: MCQ -----------------------------------------------------------

    def start_mcq_detection(self, qp_path: str, source_filename: str = "") -> Payload:
        """Read the student's ticked letters off an annotated MCQ question paper.

        `source_filename` matters when it differs from `qp_path`: the per-subject
        skip-pages lookup keys off the original name, and a GoodNotes export
        often arrives as a temp file with a random one.
        """
        a = self._analysis
        if a is None:
            return {"success": False, "error": "还没有解析答案键"}
        config = GraderConfig.try_load()
        if config is None:
            return {
                "success": False,
                "error": "还没有配置 Grader API，先去【设置】填。",
            }

        def work() -> None:
            detected, undetected = detect_student_answers(
                qp_path,
                a.config,
                config,
                renderer=LocalRenderer(),
                dpi=config.dpi,
                on_progress=lambda batch, total: push(
                    {"type": "mcq_progress", "batch": batch, "total": total},
                ),
                source_filename=source_filename or None,
            )
            self._mcq_detected = detected
            push({
                "type": "mcq_detected",
                "detected": detected,
                "undetected": undetected,
                "answer_key": {
                    qid: q.mark_scheme for qid, q in a.config.questions.items()
                },
            })

        return start("识别答案", work)

    def score_mcq(self, manual: dict[str, str] | None = None) -> Payload:
        """Score the detected answers, with hand-typed ones laid over them.

        `merge_mcq_answers` drops anything that is not a single A–D letter, so
        a half-typed box cannot silently overwrite a detected answer.
        """
        a = self._analysis
        if a is None:
            return {"success": False, "error": "还没有解析答案键"}
        merged = merge_mcq_answers(self._mcq_detected, manual or {})
        score, total, per_question = score_mcq_answers(a.config, merged)
        return {
            "success": True,
            "score": score,
            "total": total,
            "per_question": per_question,
            "answers": merged,
        }

    def confirm_mcq(
        self, paper_id: str, manual: dict[str, str] | None = None,
    ) -> Payload:
        """Record an MCQ paper's score. No mistake rows: a wrong tick carries no
        mark scheme to explain it, so there is nothing to file under a topic."""
        scored = self.score_mcq(manual)
        if not scored.get("success"):
            return scored
        update = self.submit_score(paper_id, scored["score"], scored["total"])
        if not update.get("success"):
            return update
        return {
            "success": True,
            "score": scored["score"],
            "total": scored["total"],
        }

    def confirm_results(
        self,
        paper_id: str,
        overrides: dict[str, float] | None = None,
        topic_overrides: dict[str, str | None] | None = None,
        error_overrides: dict[str, str | None] | None = None,
    ) -> Payload:
        """Write the graded scores to the paper's row, file its lost marks and
        record every question as an attempt.

        The three override maps are keyed ``"<paper_id>:<question>"`` by the
        paper each question was graded under: a score, or the topic id / error
        type the student picked in place of the model's (None clears it). A
        whole paper is then recorded under *paper_id*, which the student may
        have corrected on the results page.

        The mistake rows are appended, never replaced: re-grading a paper adds
        a second set rather than editing the first, which is what makes the
        错题本 a history instead of a snapshot.
        """
        sheet = self._sheet
        if sheet is None or not self._results:
            return {"success": False, "error": "没有可确认的批改结果"}
        overrides = overrides or {}
        topic_picks = topic_overrides or {}
        # model_copy skips validation, so an error type the page made up
        # would only fail when the attempt row is built — after the score
        # was already written.
        error_picks = {
            k: e for k, e in (error_overrides or {}).items()
            if e is None or e in ERROR_TYPES
        }

        by_paper: dict[str, list[QuestionResult]] = {}
        for r in self._results:
            by_paper.setdefault(r.paper_id, []).append(r)

        now = datetime.datetime.now(datetime.UTC)
        mistakes: list[MistakeRecord] = []
        run: list[AttemptRecord] = []
        filed: list[tuple[str, str]] = []
        score = max_score = 0.0
        for graded_as, model_results in by_paper.items():
            pid = paper_id if sheet.kind == "paper" else graded_as
            scores: dict[str, float] = {}
            results = []
            for r in model_results:
                key = f"{graded_as}:{r.question}"
                if key in overrides:
                    scores[r.question] = overrides[key]
                picked: dict[str, Any] = {}
                if key in topic_picks:
                    picked["topic"] = topic_picks[key]
                if key in error_picks:
                    picked["error_type"] = error_picks[key]
                results.append(r.model_copy(update=picked) if picked else r)
            summary = summarise_scores(results, scores)
            score += summary.score
            max_score += summary.max_score
            if sheet.kind == "paper":
                update = self.submit_score(pid, summary.score, summary.max_score)
                if not update.get("success"):
                    return update
            topics = self.topics_for(pid)
            mistakes += mistakes_from_results(
                results, paper_id=pid, topics=topics, scores=scores,
                timestamp=now,
            )
            run += attempts_from_results(
                results, model_results=model_results, paper_id=pid,
                topics=topics, scores=scores, timestamp=now,
            )
            filed += [(pid, r.question) for r in results]

        self._mistakes.append_many(mistakes)
        self._attempts.append_many(run)
        self._sheet = None
        self._results = []
        self._refresh_notes_later(filed)
        return {"success": True, "score": score, "max_score": max_score}

    def _refresh_notes_later(self, questions: list[tuple[str, str]]) -> None:
        """File the confirmed questions into their components' tutor notes,
        on a thread of its own.

        Not a `jobs.start` job: that allows one job at a time, and a note
        rewrite must not block parsing the next paper. A failure is logged
        and the old note stays — the scores are already recorded.
        """
        config = GraderConfig.try_load()
        if config is None:
            return
        by_component: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for paper_id, question in questions:
            component = component_paper_number(paper_id)
            if component is not None:
                key = (subject_id_of(paper_id), component)
                by_component.setdefault(key, []).append((paper_id, question))
        if not by_component:
            return
        records = self._attempts.load_all()
        # Appended in time order, so a re-graded question's latest comment wins.
        comments = {
            (m.paper_id, m.question_id): m.comment for m in self._mistakes.load_all()
        }

        def work() -> None:
            for (subject_id, component), filed in by_component.items():
                try:
                    with _notes_lock:
                        refresh_notes(
                            config, records, comments,
                            subject_id=subject_id, component=component,
                            questions=filed,
                        )
                except Exception:
                    _log.exception(
                        "tutor note for %s P%s failed", subject_id, component,
                    )

        threading.Thread(target=work, name="tutor-notes", daemon=True).start()

    def tutor_notes(self, subject_id: str, component: str) -> str | None:
        """The tutor's note on one syllabus's Paper *component*, if written."""
        return read_notes(subject_id, component)

    # -- settings ------------------------------------------------------------

    def mail_settings(self) -> Payload:
        """Current SMTP config for the form. The password is never sent back —
        a write-only field is the point of storing it as a SecretStr."""
        c = self._mail
        if c is None:
            return {"configured": False}
        return {
            "configured": True,
            "smtp_server": c.smtp_server or "",
            "smtp_port": c.smtp_port,
            "sender_email": str(c.sender_email),
            "goodnotes_email": str(c.goodnotes_email),
        }

    def save_mail_settings(
        self,
        smtp_server: str,
        smtp_port: int,
        sender_email: str,
        sender_app_password: str,
        goodnotes_email: str,
    ) -> Payload:
        try:
            config = MailConfig(
                smtp_server=smtp_server,
                smtp_port=int(smtp_port),
                sender_email=sender_email,
                sender_app_password=sender_app_password,
                goodnotes_email=goodnotes_email,
            )
            config.save_to_env()
        except ValidationError as exc:
            return _invalid(exc)
        except (OSError, ValueError) as exc:
            return {"success": False, "error": f"保存失败：{exc}"}
        self._mail = config
        return {"success": True}

    def grader_settings(self) -> Payload:
        """Current grader config. Same rule: the key does not come back."""
        c = GraderConfig.try_load()
        if c is None:
            return {"configured": False, "base_url": _DEFAULT_BASE_URL}
        return {
            "configured": True,
            "base_url": c.base_url,
            "model": c.model,
            "dpi": c.dpi,
            "enable_thinking": c.enable_thinking,
        }

    def save_grader_settings(
        self, api_key: str, base_url: str, model: str,
    ) -> Payload:
        try:
            config = GraderConfig(
                api_key=api_key,
                base_url=base_url or _DEFAULT_BASE_URL,
                model=model or "qwen3.6-flash",
            )
            config.save_to_env()
        except ValidationError as exc:
            return _invalid(exc)
        except OSError as exc:
            return {"success": False, "error": f"保存失败：{exc}"}
        return {"success": True}

    def syllabuses_stored(self) -> list[Payload]:
        """Parsed syllabuses on disk, with what each one covers."""
        return [
            {
                "subject_id": s.subject_id,
                "topic_count": len(s.topics),
                "components": sorted(
                    set(s.component_topics) | set(s.component_grading)
                ),
                "path": str(syllabus_path(s.subject_id)),
            }
            for s in stored_syllabuses()
        ]

    def forget_syllabus(self, subject_id: str) -> Payload:
        """Drop a stored syllabus. Getting it back means picking the PDF
        again, so it stays an explicit action."""
        return {"success": delete_syllabus(subject_id)}

    def import_syllabus(self, pdf_path: str) -> Payload:
        """Parse a syllabus PDF and store it under the code on its cover."""
        try:
            subject_id = detect_subject_id(pdf_path)
            if subject_id is None:
                return {"success": False, "error": "封面上没有认得出的科目代码"}
            info = parse_syllabus(pdf_path, subject_id, force=True)
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            _log.exception("syllabus import failed: %s", pdf_path)
            return {"success": False, "error": str(exc)}
        return {
            "success": True,
            "subject_id": subject_id,
            "topic_count": len(info.topics),
        }

    def app_version(self) -> str:
        return current_app_version()

    def check_update(self) -> Payload:
        result = self._updater.check()
        self._update_url = result.download_url if result.update_available else None
        return result.model_dump(mode="json")

    def install_update(self) -> Payload:
        """Download the installer the last check found, run it, and quit.

        Quitting is not optional: the installer cannot replace the app while
        it is still running. The installer reopens it once it is done.
        """
        url = self._update_url
        if url is None:
            return {"success": False, "error": "先检查更新"}

        def work() -> None:
            downloaded = self._updater.download(
                url,
                lambda p: push({
                    "type": "update_progress",
                    "fraction": p.downloaded / p.total if p.total else None,
                    "text": format_progress(p),
                }),
            )
            if not downloaded.success or downloaded.local_path is None:
                raise RuntimeError(downloaded.error or "下载失败")
            installed = self._updater.install(Path(downloaded.local_path))
            if not installed.success:
                raise RuntimeError(installed.error or "安装程序没能启动")
            window = webview.active_window()
            if window is not None:
                window.destroy()

        return start("更新", work)

    # -- grade thresholds ----------------------------------------------------

    def parse_gt(self, pdf_path: str, session: str) -> Payload:
        """Read a downloaded grade-threshold PDF into its option rows.

        Parsing is the one place in this file that catches broadly: `GTParser`
        walks ruling lines and CID-decoded glyphs out of a third-party PDF, so
        the failure modes are open-ended and every one of them is a message for
        the user rather than a crash.
        """
        try:
            doc = GTParser().parse(Path(pdf_path), session)
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            return {"success": False, "error": f"分数线解析失败：{exc}"}
        return {"success": True, **doc.model_dump(mode="json")}

    # -- GoodNotes -----------------------------------------------------------

    def mail_ready(self) -> bool:
        """Whether .env carries enough SMTP config to offer the send at all."""
        return self._mail is not None

    def send_to_goodnotes(self, paper_id: str, qp_path: str) -> Payload:
        """Mail a downloaded QP to the GoodNotes import address."""
        if self._mail is None:
            return {"success": False, "error": "没有配置 SMTP，先在设置里填邮箱。"}
        try:
            request = MailRequest(paper_id=paper_id, qp_path=qp_path)
        except ValidationError as exc:
            return _invalid(exc)
        mailer = GoodNotesMailer(config=self._mail, store=self._store)
        return mailer.send(request).model_dump(mode="json")
