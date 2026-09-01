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
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

import webview
from pydantic import ValidationError

from app_web.jobs import current, push, start
from core.config_store import ConfigStore
from core.gt_parser import GTParser
from core.models import MistakeRecord, PaperType
from core.settings import GraderConfig, MailConfig, app_settings
from core.storage import CSVStore, MistakeStore
from modules.downloader import DownloadRequest, PaperDownloader, query_available
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import DeleteRequest, PaperManager, ScoreUpdate
from modules.marking.answer_sheet import build_answer_sheet
from modules.marking.mcq_parser import (
    detect_student_answers,
    score_mcq_answers,
)
from modules.marking.mistake_pdf import build_export
from modules.marking.mistakes import (
    distinct_topic_keys,
    mistakes_from_results,
    retag,
    subject_id_of,
    to_csv,
)
from modules.marking.ms_parser import (
    PaperConfig,
    ms_cache_exists,
    parse_mark_scheme,
    resolve_ms_start_page,
)
from modules.marking.page_segmenter import ScannedDocument, match_scanned, scan_document
from modules.marking.renderer import LocalRenderer
from modules.marking.syllabus_parser import (
    delete_syllabus,
    load_syllabus,
    stored_syllabuses,
    syllabus_path,
)
from modules.marking.workflow import (
    collect_page_assignments,
    grade_paper,
    merge_mcq_answers,
    regions_to_page_map,
    summarise_scores,
    topics_for_paper,
)
from modules.updater import AppUpdater, current_app_version

if TYPE_CHECKING:
    from modules.marking.renderer import NativeRenderer

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
    picked and cancelling is a normal outcome rather than an error — same
    contract the Flet tab's save picker had.
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
        self._updater = AppUpdater()
        # None when .env carries no SMTP credentials — a normal state, not an
        # error. The UI hides the GoodNotes affordance rather than failing it.
        self._mail = MailConfig.try_load()
        self._analysis: _Analysis | None = None
        self._results: list[Any] = []
        #: Letters the VL read off the annotated QP, before any manual
        #: overlay. Kept apart from the manual boxes so re-scoring does
        #: not need another detection pass.
        self._mcq_detected: dict[str, str] = {}

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
        rewritten with the one row replaced — matching what the Flet tab does.
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
        """Crop the selected questions out of their QPs into one PDF.

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
        try:
            data, warnings = build_export(chosen, qp, ms)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        saved = _save_to_chosen_file(data, "mistakes.pdf", ("PDF (*.pdf)",))
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

    # -- mark ----------------------------------------------------------------

    def pick_pdf(self, title: str = "选择 PDF") -> str | None:
        """Host file dialog. Returns the chosen path, or None if cancelled."""
        window = webview.active_window()
        if window is None:
            return None
        chosen = window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=(f"{title} (*.pdf)",),
        )
        if not chosen:
            return None
        return chosen if isinstance(chosen, str) else chosen[0]

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
                doc = scan_future.result() if scan_future is not None else None

            self._analysis = _Analysis(config, doc, pt, answer_path)
            push({"type": "analysis", **self._analysis_payload()})

        return start("解析", work)

    def _parse_ms(
        self, ms_path: str, pt: PaperType, start_page: int | None, force: bool,
    ) -> PaperConfig:
        resolved = (
            resolve_ms_start_page(ms_path, start_page)
            if pt is PaperType.MATH
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
            # ms_parser annotates this parameter as the concrete
            # NativeRenderer, but only calls render_pages on it — the
            # Renderer protocol's shape, which LocalRenderer satisfies.
            # Widening that annotation means editing modules/, which this
            # migration does not do; the cast goes away in M5 when
            # NativeRenderer does.
            renderer=cast("NativeRenderer", LocalRenderer()),
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
            "paper_id": a.config.paper_id,
            "total_marks": a.config.total_marks,
            "questions": {
                qid: {"max_marks": q.max_marks, "mark_scheme": q.mark_scheme}
                for qid, q in a.config.questions.items()
            },
            "answer_path": a.answer_path,
            "matched": report.matched if report else [],
            "unmatched": report.unmatched if report else list(a.config.questions),
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

        def work() -> None:
            outcome = grade_paper(
                config=config,
                paper_config=a.config,
                paper_type=a.paper_type,
                pdf_source=answer_path,
                question_ids=question_ids,
                assignments=assignments,
                clips=clips,
                renderer=LocalRenderer(),
                syllabus_info=load_syllabus(subject_id_of(a.config.paper_id)),
                paper_id=a.config.paper_id,
                on_progress=lambda done, total, qid: push(
                    {"type": "progress", "done": done, "total": total, "question": qid},
                ),
                on_result=lambda r: push(
                    {"type": "result", "result": r.model_dump(mode="json")},
                ),
            )
            self._results = outcome.results
            push({
                "type": "graded",
                "results": [r.model_dump(mode="json") for r in outcome.results],
                "failures": [
                    {"question": f.question, "error": f.error}
                    for f in outcome.failures
                ],
            })

        return start("批改", work)

    def job_running(self) -> str | None:
        return current()

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
                renderer=cast("NativeRenderer", LocalRenderer()),
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
        self, paper_id: str, overrides: dict[str, float] | None = None,
    ) -> Payload:
        """Write the graded scores to the paper's row and file its lost marks.

        The mistake rows are appended, never replaced: re-grading a paper adds
        a second set rather than editing the first, which is what makes the
        错题本 a history instead of a snapshot.
        """
        if not self._results:
            return {"success": False, "error": "没有可确认的批改结果"}
        a = self._analysis
        summary = summarise_scores(self._results, overrides or {})
        update = self.submit_score(paper_id, summary.score, summary.max_score)
        if not update.get("success"):
            return update
        self._mistakes.append_many(
            mistakes_from_results(
                self._results,
                paper_id=paper_id,
                topics=self.topics_for(paper_id),
                timestamp=datetime.datetime.now(datetime.UTC),
            ),
        )
        self._results = []
        self._analysis = a
        return {
            "success": True,
            "score": summary.score,
            "max_score": summary.max_score,
        }

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
                "components": sorted(s.component_topics),
                "path": str(syllabus_path(s.subject_id)),
            }
            for s in stored_syllabuses()
        ]

    def forget_syllabus(self, subject_id: str) -> Payload:
        """Drop a stored syllabus. Re-parsing one costs a VL call, so this is
        the only way back to that spend — it stays an explicit action."""
        return {"success": delete_syllabus(subject_id)}

    def app_version(self) -> str:
        return current_app_version()

    def check_update(self) -> Payload:
        return self._updater.check().model_dump(mode="json")

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
