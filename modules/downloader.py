from __future__ import annotations

import re
from pathlib import Path
from typing import Final, Literal

import requests
from pydantic import BaseModel, field_validator, model_validator

from core.models import PaperRecord
from core.settings import app_settings
from core.storage import CSVStore

_REQUEST_TIMEOUT: Final[tuple[int, int]] = (10, 30)
_CHUNK_SIZE: Final[int] = 8192

# Source base URLs
_URL_CIEFRANK: Final[str] = "https://cie.fraft.cn/obj/common/Fetch/redir"
_URL_PAPACAMBRIDGE: Final[str] = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"

DownloadSource = Literal["CIEFrank", "PapaCambridge"]
_DEFAULT_SOURCE: Final[DownloadSource] = "CIEFrank"


def _build_url(source: DownloadSource, filename: str) -> str:
    """Construct the full PDF URL for a given source and filename stem."""
    if source == "CIEFrank":
        return f"{_URL_CIEFRANK}/{filename}.pdf"
    return f"{_URL_PAPACAMBRIDGE}/{filename}.pdf"


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class DownloadRequest(BaseModel):
    """Validated input for a single download job."""

    model_config = {"strict": True}

    paper_id: str
    source: DownloadSource = _DEFAULT_SOURCE

    @field_validator("paper_id")
    @classmethod
    def paper_id_format(cls, v: str) -> str:
        v = v.strip()
        # Standard: <subject>_<session>_<component>_<variant>, e.g. 9231_s25_qp_11
        standard = re.fullmatch(r"[a-zA-Z0-9]+_[a-zA-Z0-9]+_[a-zA-Z]+_[a-zA-Z0-9]+", v)
        # GT format: <subject>_<session>_gt  e.g. 9231_s25_gt
        gt_format = re.fullmatch(r"[a-zA-Z0-9]+_[a-zA-Z0-9]+_gt", v)
        if not standard and not gt_format:
            raise ValueError(
                f"paper_id must match '<subject>_<session>_<component>_<variant>' "
                f"or '<subject>_<session>_gt', got: {v!r}"
            )
        return v

    @model_validator(mode="after")
    def derive_ms_id(self) -> DownloadRequest:
        if "_qp_" in self.paper_id:
            self._ms_id: str = self.paper_id.replace("_qp_", "_ms_")
            self._insert_id: str = self.paper_id.replace("_qp_", "_in_")
        else:
            self._ms_id = ""
            self._insert_id = ""
        return self

    @property
    def ms_id(self) -> str:
        return self._ms_id

    @property
    def insert_id(self) -> str:
        """``9701_s25_qp_31`` → ``9701_s25_in_31``; empty for non-QP ids.

        Only ``download_with_insert`` looks at this — plain ``download()``
        never asks for an insert.
        """
        return self._insert_id

    @property
    def is_gt(self) -> bool:
        return self.paper_id.endswith("_gt")

    @property
    def qp_url(self) -> str:
        return _build_url(self.source, self.paper_id)

    @property
    def ms_url(self) -> str:
        return _build_url(self.source, self.ms_id)

    @property
    def insert_url(self) -> str:
        return _build_url(self.source, self.insert_id)


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------


class DownloadResult(BaseModel):
    """Outcome of a download attempt."""

    model_config = {"strict": False}

    success: bool
    paper_id: str
    qp_path: str | None = None
    ms_path: str | None = None
    error: str | None = None
    #: Only ``download_with_insert`` ever fills these two in; ``download()``
    #: leaves them None, so its callers can keep ignoring them.
    #: ``insert_path=None`` + ``insert_error=None`` means "this paper has no
    #: insert", which is the normal case — most papers don't.
    insert_path: str | None = None
    #: Set when the insert *should* have been fetchable but the fetch broke
    #: (network, HTTP 500, …). ``success`` stays True: QP+MS are on disk and
    #: registered, so this is a warning to surface, not a failed download.
    insert_error: str | None = None


# ---------------------------------------------------------------------------
# Downloader class
# ---------------------------------------------------------------------------


class PaperDownloader:
    """Downloads QP and MS PDFs and registers them in the CSV store."""

    def __init__(self, store: CSVStore | None = None) -> None:
        self._store = store or CSVStore()
        self._pdfs_dir: Path = app_settings.pdfs_dir

    def download(self, request: DownloadRequest) -> DownloadResult:
        """
        Main entry point. Downloads QP (and MS if applicable), saves to disk,
        and appends a new PaperRecord to the store.
        GT files skip the MS download and store registration.

        Returns a DownloadResult — never raises on network errors,
        validation errors from the request model will propagate normally.
        """
        try:
            qp_path = self._fetch_pdf(request.qp_url, request.paper_id)
        except _DownloadError as exc:
            return DownloadResult(
                success=False,
                paper_id=request.paper_id,
                error=str(exc),
            )

        # GT files: just download, don't fetch MS or register in store
        if request.is_gt:
            return DownloadResult(
                success=True,
                paper_id=request.paper_id,
                qp_path=str(qp_path),
                ms_path=None,
            )

        try:
            ms_path = self._fetch_pdf(request.ms_url, request.ms_id)
        except _DownloadError as exc:
            return DownloadResult(
                success=False,
                paper_id=request.paper_id,
                error=str(exc),
            )

        record = PaperRecord(
            paper_id=request.paper_id,
            status="Pending",
            qp_path=str(qp_path),
            ms_path=str(ms_path),
        )

        try:
            self._store.append(record)
        except ValueError as exc:
            # paper_id already exists in store
            return DownloadResult(
                success=False,
                paper_id=request.paper_id,
                error=str(exc),
            )

        return DownloadResult(
            success=True,
            paper_id=request.paper_id,
            qp_path=str(qp_path),
            ms_path=str(ms_path),
        )

    def download_with_insert(self, request: DownloadRequest) -> DownloadResult:
        """
        QP + MS + the paper's insert (``_in_``) when it has one.

        Deliberately a separate entry point rather than a flag on
        ``download()``: the plain-download callers have no way to reach the
        insert fetch, so "which screens pull inserts" is settled by which
        method they call, not by a convention about a parameter.

        QP-only ids: GT files and anything else without a ``_qp_`` component
        are rejected outright — pairing is the whole premise here.

        The insert is optional, and that shapes the failure handling: a 404
        means "this paper has no insert" (true for most papers), so the result
        still comes back ``success=True`` with ``insert_path=None``. Any other
        insert failure also keeps ``success=True`` — QP+MS are already on disk
        and registered — but reports itself in ``insert_error`` for the UI to
        show as a warning. A QP or MS failure still fails the whole call.

        The insert path is returned, not persisted: PaperRecord has no column
        for it, and adding one would migrate every existing data.csv.
        """
        if not request.ms_id:
            return DownloadResult(
                success=False,
                paper_id=request.paper_id,
                error=(
                    f"{request.paper_id} 不是 QP 试卷，无法配对下载 MS/insert"
                ),
            )

        try:
            qp_path = self._fetch_pdf(request.qp_url, request.paper_id)
            ms_path = self._fetch_pdf(request.ms_url, request.ms_id)
        except _DownloadError as exc:
            return DownloadResult(
                success=False,
                paper_id=request.paper_id,
                error=str(exc),
            )

        insert_path: Path | None = None
        insert_error: str | None = None
        try:
            insert_path = self._fetch_pdf(request.insert_url, request.insert_id)
        except _DownloadError as exc:
            # 404 == 这份卷子没有 insert，是常态，不算错。
            if not exc.missing:
                insert_error = str(exc)

        record = PaperRecord(
            paper_id=request.paper_id,
            status="Pending",
            qp_path=str(qp_path),
            ms_path=str(ms_path),
        )

        try:
            self._store.append(record)
        except ValueError as exc:
            # paper_id already exists in store
            return DownloadResult(
                success=False,
                paper_id=request.paper_id,
                error=str(exc),
            )

        return DownloadResult(
            success=True,
            paper_id=request.paper_id,
            qp_path=str(qp_path),
            ms_path=str(ms_path),
            insert_path=str(insert_path) if insert_path else None,
            insert_error=insert_error,
        )

    def record_only(self, paper_id: str) -> DownloadResult:
        """
        Register a paper in the store without downloading its QP, but download its MS.
        Useful for papers completed on physical copies.
        Reuses DownloadRequest's paper_id format validation.
        """
        try:
            request = DownloadRequest(paper_id=paper_id)
        except Exception as exc:  # noqa: BLE001
            return DownloadResult(success=False, paper_id=paper_id, error=str(exc))

        try:
            ms_path = self._fetch_pdf(request.ms_url, request.ms_id)
        except _DownloadError as exc:
            return DownloadResult(
                success=False, paper_id=request.paper_id, error=str(exc)
            )

        record = PaperRecord(
            paper_id=request.paper_id, status="Pending", ms_path=str(ms_path)
        )
        try:
            self._store.append(record)
        except ValueError as exc:
            return DownloadResult(
                success=False, paper_id=request.paper_id, error=str(exc)
            )

        return DownloadResult(
            success=True, paper_id=request.paper_id, ms_path=str(ms_path)
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_pdf(self, url: str, filename_stem: str) -> Path:
        """
        Stream-download a single PDF to disk.
        Raises _DownloadError on HTTP errors or non-PDF content.
        """
        try:
            response = requests.get(url, stream=True, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise _DownloadError(f"Network error fetching {url!r}: {exc}") from exc

        if response.status_code == 404:
            raise _DownloadError(
                f"404 Not Found — check the paper ID and base URL are correct: {url!r}",
                missing=True,
            )

        if not response.ok:
            raise _DownloadError(
                f"HTTP {response.status_code} when fetching {url!r}"
            )

        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not url.endswith(".pdf"):
            raise _DownloadError(
                f"Unexpected content type {content_type!r} for {url!r}. "
                "Expected a PDF file."
            )

        dest: Path = self._pdfs_dir / f"{filename_stem}.pdf"
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                if chunk:
                    fh.write(chunk)

        return dest


# ---------------------------------------------------------------------------
# Internal exception
# ---------------------------------------------------------------------------


class _DownloadError(Exception):
    """Raised internally when a PDF fetch fails. Never leaks outside this module."""

    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(message)
        #: True only for a 404 — "the server has no such file", as opposed to
        #: "the fetch broke". ``download_with_insert`` needs the distinction
        #: because a missing insert is normal; every other caller just reads
        #: the message.
        self.missing = missing


# ---------------------------------------------------------------------------
# Session query — list everything CIEFrank has for one subject/year/season
# ---------------------------------------------------------------------------

_URL_RENUM: Final[str] = "https://cie.fraft.cn/obj/Common/Fetch/renum"

QuerySeason = Literal["m", "s", "w"]
QueryKind = Literal["qp", "gt", "other"]

# The endpoint speaks English month abbreviations, not the m/s/w codes used in
# every filename. Getting this mapping wrong is silent — the response is still
# valid JSON, just for the wrong session — hence the dedicated tests.
_RENUM_SEASONS: Final[dict[str, str]] = {"m": "Mar", "s": "Jun", "w": "Nov"}


def classify_paper_id(paper_id: str) -> QueryKind:
    """
    Bucket a paper_id stem (no .pdf) into what the downloader can handle.

    ``9701_w25_qp_11`` → "qp", ``9701_w25_gt`` → "gt", everything else
    (ms, ci, in, er, qr, …) → "other".
    """
    parts = paper_id.split("_")
    if len(parts) == 3 and parts[2] == "gt":
        return "gt"
    if len(parts) == 4 and parts[2] == "qp":
        return "qp"
    return "other"


class QueryEntry(BaseModel):
    """One paper the session query turned up."""

    model_config = {"strict": False}

    paper_id: str
    kind: QueryKind
    already_downloaded: bool = False
    #: This session also lists the paper's insert (``_in_``). Only ever True on
    #: a ``qp`` entry — it's what tells the UI to hang the insert under the QP
    #: and to download it via ``download_with_insert``.
    has_insert: bool = False


class QueryResult(BaseModel):
    """Outcome of a session query — never raises, mirrors DownloadResult."""

    model_config = {"strict": False}

    success: bool
    entries: list[QueryEntry] = []
    error: str | None = None


def query_available(
    subject: str,
    year: str,
    season: QuerySeason,
    store: CSVStore | None = None,
) -> QueryResult:
    """
    List every paper CIEFrank holds for one subject/year/season.

    ``store`` is only there so tests (and callers holding a store already) can
    avoid re-reading the CSV; it defaults to the app's own store.

    Returns a QueryResult — network, HTTP, malformed-JSON and "路径非法" style
    errors all come back as ``success=False`` with a message, never as an
    exception. An empty ``entries`` list with ``success=True`` means the
    session genuinely has nothing (e.g. a future exam session).
    """
    renum_season = _RENUM_SEASONS.get(season)
    if renum_season is None:
        return QueryResult(success=False, error=f"未知考季代码: {season!r}")

    try:
        rows = _fetch_renum(subject.strip(), str(year).strip(), renum_season)
    except _DownloadError as exc:
        return QueryResult(success=False, error=str(exc))

    downloaded = _downloaded_paper_ids(store)
    entries: list[QueryEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        filename = row.get("file")
        if not isinstance(filename, str) or not filename.strip():
            continue
        paper_id = re.sub(r"\.pdf$", "", filename.strip(), flags=re.IGNORECASE)
        entries.append(
            QueryEntry(
                paper_id=paper_id,
                kind=classify_paper_id(paper_id),
                already_downloaded=paper_id in downloaded,
            )
        )

    # Which QPs come with an insert can only be answered once the whole listing
    # is in hand, so it's a second pass. Deciding it here rather than in the UI
    # keeps "does this paper have an insert" a fact about the session listing.
    listed = {entry.paper_id for entry in entries}
    for entry in entries:
        if entry.kind == "qp":
            entry.has_insert = entry.paper_id.replace("_qp_", "_in_") in listed

    return QueryResult(success=True, entries=entries)


def _fetch_renum(subject: str, year: str, season: str) -> list[object]:
    """
    POST the renum query and hand back its ``rows`` list.

    Raises _DownloadError for anything that isn't a well-formed row list —
    including the ``{"status":101,"message":"路径非法。"}`` shape the endpoint
    returns for an unknown subject, which carries no ``rows`` key at all and
    must NOT be mistaken for "this session has no papers".
    """
    try:
        response = requests.post(
            _URL_RENUM,
            data={"subject": subject, "year": year, "season": season},
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise _DownloadError(f"网络错误: {exc}") from exc

    if not response.ok:
        raise _DownloadError(f"HTTP {response.status_code} — 查询接口无响应")

    try:
        payload = response.json()
    except ValueError as exc:
        raise _DownloadError(f"查询接口返回的不是合法 JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise _DownloadError("查询接口返回了意料之外的结构")

    if "rows" not in payload:
        message = payload.get("message") or "查询接口拒绝了这次请求"
        raise _DownloadError(f"查询失败: {message}")

    rows = payload["rows"]
    if not isinstance(rows, list):
        raise _DownloadError("查询接口返回的 rows 不是列表")

    return rows


def _downloaded_paper_ids(store: CSVStore | None) -> set[str]:
    """paper_ids already in the store; an unreadable store just means 'none'."""
    try:
        records = (store or CSVStore()).load_all()
    except Exception:  # noqa: BLE001
        return set()
    return {record.paper_id for record in records}