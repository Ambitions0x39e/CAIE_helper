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
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from core.config_store import ConfigStore
from core.settings import MailConfig, app_settings
from core.storage import CSVStore
from modules.downloader import DownloadRequest, PaperDownloader, query_available
from modules.mailer import GoodNotesMailer, MailRequest

#: What a failed call looks like. Mirrors DownloadResult/QueryResult so the
#: frontend has exactly one shape to read.
type Payload = dict[str, Any]


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
