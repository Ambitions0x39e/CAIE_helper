from __future__ import annotations

import datetime
import platform
import subprocess
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from core.models import PaperRecord
from core.storage import CSVStore

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class ScoreUpdate(BaseModel):
    """Validated input when a user submits scores for a paper."""

    model_config = {"strict": True}

    paper_id: str
    score_raw: float
    score_total: float

    @field_validator("paper_id")
    @classmethod
    def paper_id_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("paper_id cannot be empty")
        return v

    @field_validator("score_raw", "score_total", mode="before")
    @classmethod
    def must_be_non_negative(cls, v: object) -> float:
        if not isinstance(v, (int, float)):
            raise TypeError(f"Expected a number, got {type(v).__name__}")
        if v < 0:
            raise ValueError("Score values cannot be negative")
        return float(v)

    @model_validator(mode="after")
    def raw_must_not_exceed_total(self) -> ScoreUpdate:
        if self.score_raw > self.score_total:
            raise ValueError(
                f"score_raw ({self.score_raw}) cannot exceed "
                f"score_total ({self.score_total})"
            )
        return self

    @model_validator(mode="after")
    def total_must_be_positive(self) -> ScoreUpdate:
        if self.score_total <= 0:
            raise ValueError("score_total must be greater than zero")
        return self


class DeleteRequest(BaseModel):
    """Validated input for a deletion operation."""

    model_config = {"strict": True}

    paper_id: str
    delete_local_files: bool = False

    @field_validator("paper_id")
    @classmethod
    def paper_id_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("paper_id cannot be empty")
        return v


# ---------------------------------------------------------------------------
# Result schemas
# ---------------------------------------------------------------------------


class UpdateResult(BaseModel):
    model_config = {"strict": False}

    success: bool
    paper_id: str
    error: str | None = None


class DeleteResult(BaseModel):
    model_config = {"strict": False}

    success: bool
    paper_id: str
    files_deleted: list[str] = []
    error: str | None = None


class OpenResult(BaseModel):
    model_config = {"strict": False}

    success: bool
    path: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Manager class
# ---------------------------------------------------------------------------


class PaperManager:
    """
    Handles all CRUD operations on PaperRecords:
    - Submitting scores (marks a paper Completed)
    - Deleting records (optionally removes local PDFs)
    - Opening PDFs in the system default viewer
    """

    def __init__(self, store: CSVStore | None = None) -> None:
        self._store = store or CSVStore()

    # ------------------------------------------------------------------
    # Score submission
    # ------------------------------------------------------------------

    def submit_score(self, update: ScoreUpdate) -> UpdateResult:
        """
        Apply score_raw / score_total to the matching record,
        flip status → 'Completed', and record a timestamp.
        """
        try:
            records = self._store.load_all()
        except ValueError as exc:
            return UpdateResult(success=False, paper_id=update.paper_id, error=str(exc))

        target: PaperRecord | None = next(
            (r for r in records if r.paper_id == update.paper_id), None
        )
        if target is None:
            return UpdateResult(
                success=False,
                paper_id=update.paper_id,
                error=f"paper_id '{update.paper_id}' not found in store.",
            )

        try:
            updated = target.model_copy(
                update={
                    "score_raw": update.score_raw,
                    "score_total": update.score_total,
                    "status": "Completed",
                    "timestamp": datetime.datetime.now(tz=datetime.UTC),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return UpdateResult(
                success=False,
                paper_id=update.paper_id,
                error=f"Failed to build updated record: {exc}",
            )

        try:
            self._store.update(updated)
        except (KeyError, ValueError) as exc:
            return UpdateResult(
                success=False, paper_id=update.paper_id, error=str(exc)
            )

        return UpdateResult(success=True, paper_id=update.paper_id)

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete(self, request: DeleteRequest) -> DeleteResult:
        """
        Remove a record from the store.
        If delete_local_files=True, also removes the QP and MS PDFs from disk.
        """
        try:
            records = self._store.load_all()
        except ValueError as exc:
            return DeleteResult(
                success=False, paper_id=request.paper_id, error=str(exc)
            )

        target: PaperRecord | None = next(
            (r for r in records if r.paper_id == request.paper_id), None
        )
        if target is None:
            return DeleteResult(
                success=False,
                paper_id=request.paper_id,
                error=f"paper_id '{request.paper_id}' not found in store.",
            )

        files_deleted: list[str] = []

        if request.delete_local_files:
            for attr in ("qp_path", "ms_path"):
                raw_path: str = getattr(target, attr)
                path = Path(raw_path)
                if raw_path and path.exists():
                    try:
                        path.unlink()
                        files_deleted.append(str(path))
                    except OSError as exc:
                        return DeleteResult(
                            success=False,
                            paper_id=request.paper_id,
                            error=f"Could not delete file {path}: {exc}",
                        )

        try:
            self._store.delete(request.paper_id)
        except (KeyError, ValueError) as exc:
            return DeleteResult(
                success=False, paper_id=request.paper_id, error=str(exc)
            )

        return DeleteResult(
            success=True,
            paper_id=request.paper_id,
            files_deleted=files_deleted,
        )

    # ------------------------------------------------------------------
    # Open PDF locally
    # ------------------------------------------------------------------

    def open_pdf(self, path: str) -> OpenResult:
        """
        Open a PDF in the system's default viewer.
        Cross-platform: Windows / macOS / Linux.
        """
        pdf_path = Path(path.strip())

        if not pdf_path.exists():
            return OpenResult(
                success=False,
                path=str(pdf_path),
                error=f"File not found: {pdf_path}",
            )
        if pdf_path.suffix.lower() != ".pdf":
            return OpenResult(
                success=False,
                path=str(pdf_path),
                error=f"Expected a .pdf file, got: {pdf_path.suffix!r}",
            )

        system = platform.system()
        try:
            if system == "Windows":
                import os
                os.startfile(str(pdf_path))  # noqa: S606  # type: ignore[attr-defined,unused-ignore]
            elif system == "Darwin":
                subprocess.run(["open", str(pdf_path)], check=True)
            else:
                # Linux and other POSIX
                subprocess.run(["xdg-open", str(pdf_path)], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            return OpenResult(
                success=False,
                path=str(pdf_path),
                error=f"Failed to open file: {exc}",
            )

        return OpenResult(success=True, path=str(pdf_path))
