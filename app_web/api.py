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

import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import webview
from pydantic import ValidationError

from core.config_store import ConfigStore
from core.gt_parser import GTParser
from core.settings import GraderConfig, MailConfig, app_settings
from core.storage import CSVStore, MistakeStore
from modules.downloader import DownloadRequest, PaperDownloader, query_available
from modules.mailer import GoodNotesMailer, MailRequest
from modules.manager import DeleteRequest, PaperManager, ScoreUpdate
from modules.marking.mistake_pdf import build_export
from modules.marking.mistakes import (
    distinct_topic_keys,
    retag,
    subject_id_of,
    to_csv,
)
from modules.marking.syllabus_parser import (
    delete_syllabus,
    load_syllabus,
    stored_syllabuses,
    syllabus_path,
)
from modules.marking.workflow import topics_for_paper
from modules.updater import AppUpdater, current_app_version

#: What a failed call looks like. Mirrors DownloadResult/QueryResult so the
#: frontend has exactly one shape to read.
type Payload = dict[str, Any]

#: Bailian's OpenAI-compatible endpoint — the default the form offers.
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


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

    def export_mistakes_csv(
        self, paper_ids: list[str] | None = None,
    ) -> Payload:
        """Write the selection to a file the user picks. Same columns as the
        store's own file, so it reads back into anything that reads the store."""
        records = self._mistakes.load_all()
        if paper_ids:
            wanted = set(paper_ids)
            records = [r for r in records if r.paper_id in wanted]
        return _save_to_chosen_file(
            to_csv(records).encode("utf-8-sig"), "mistakes.csv", ("CSV (*.csv)",),
        )

    def export_mistakes_pdf(self, paper_ids: list[str], with_ms: bool) -> Payload:
        """Crop the selected questions out of their QPs into one PDF.

        Warnings come back alongside the file rather than instead of it:
        exporting nine of ten questions is worth doing as long as the tenth is
        named. Only a total failure is an error.
        """
        wanted = set(paper_ids)
        records = [r for r in self._mistakes.load_all() if r.paper_id in wanted]
        papers = {r.paper_id: r for r in self._store.load_all()}
        qp = {pid: papers[pid].qp_path for pid in wanted if pid in papers}
        ms = {pid: papers[pid].ms_path for pid in wanted if pid in papers}
        try:
            data, warnings = build_export(records, qp, ms if with_ms else None)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        saved = _save_to_chosen_file(data, "mistakes.pdf", ("PDF (*.pdf)",))
        return {**saved, "warnings": warnings}

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
