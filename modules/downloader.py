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
        else:
            self._ms_id = ""
        return self

    @property
    def ms_id(self) -> str:
        return self._ms_id

    @property
    def is_gt(self) -> bool:
        return self.paper_id.endswith("_gt")

    @property
    def qp_url(self) -> str:
        return _build_url(self.source, self.paper_id)

    @property
    def ms_url(self) -> str:
        return _build_url(self.source, self.ms_id)


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
                f"404 Not Found — check the paper ID and base URL are correct: {url!r}"
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