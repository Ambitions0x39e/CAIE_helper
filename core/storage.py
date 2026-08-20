from __future__ import annotations

import datetime
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from core.models import MistakeRecord, PaperRecord
from core.settings import app_settings

# Canonical column order that matches PaperRecord fields + computed percentage
_COLUMNS: list[str] = [
    "paper_id",
    "status",
    "qp_path",
    "ms_path",
    "score_raw",
    "score_total",
    "percentage",
    "sent_to_gn",
    "timestamp",
]


class CSVStore:
    """Handles all persistence for PaperRecord objects via a flat CSV file."""

    def __init__(self, csv_path: Path = app_settings.data_csv) -> None:
        self._path = csv_path
        self._ensure_file()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> list[PaperRecord]:
        """Read CSV → validate every row → return list of PaperRecords."""
        df = pd.read_csv(self._path, dtype=str)
        records: list[PaperRecord] = []
        errors: list[str] = []

        for idx, row in df.iterrows():
            try:
                record = PaperRecord.model_validate(
                    self._row_to_dict(row), strict=False
                )
                records.append(record)
            except ValidationError as exc:
                errors.append(f"Row {idx}: {exc.error_count()} error(s) — {exc}")

        if errors:
            # Surface all validation errors at once rather than silently dropping rows
            raise ValueError(
                f"data.csv contains {len(errors)} invalid row(s):\n"
                + "\n".join(errors)
            )

        return records

    def save_all(self, records: Sequence[PaperRecord]) -> None:
        """Validate and overwrite the entire CSV with the given records."""
        rows = [self._record_to_row(r) for r in records]
        df = pd.DataFrame(rows, columns=_COLUMNS)
        df.to_csv(self._path, index=False)

    def append(self, record: PaperRecord) -> None:
        """Append a single validated record to the CSV."""
        existing = self.load_all()
        if any(r.paper_id == record.paper_id for r in existing):
            raise ValueError(
                f"paper_id '{record.paper_id}' already exists in the store"
            )
        existing.append(record)
        self.save_all(existing)

    def update(self, updated: PaperRecord) -> None:
        """Replace the row matching updated.paper_id."""
        records = self.load_all()
        for i, r in enumerate(records):
            if r.paper_id == updated.paper_id:
                records[i] = updated
                self.save_all(records)
                return
        raise KeyError(f"paper_id '{updated.paper_id}' not found in store")

    def delete(self, paper_id: str) -> None:
        """Remove the row with the given paper_id."""
        records = self.load_all()
        filtered = [r for r in records if r.paper_id != paper_id]
        if len(filtered) == len(records):
            raise KeyError(f"paper_id '{paper_id}' not found in store")
        self.save_all(filtered)

    def to_dataframe(
        self, records: Sequence[PaperRecord] | None = None
    ) -> pd.DataFrame:
        """Return a DataFrame of all records (useful for Streamlit display)."""
        if records is None:
            records = self.load_all()
        return pd.DataFrame(
            [self._record_to_row(r) for r in records], columns=_COLUMNS
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_file(self) -> None:
        """Create an empty CSV with headers if it doesn't exist yet."""
        if not self._path.exists():
            pd.DataFrame(columns=_COLUMNS).to_csv(self._path, index=False)

    @staticmethod
    def _row_to_dict(row: pd.Series[object]) -> dict[str, object]:
        """Convert a raw CSV row (all strings) into types Pydantic can coerce."""

        def _nullable_float(val: str) -> float | None:
            return None if pd.isna(val) or str(val).strip() == "" else float(val)

        def _nullable_dt(val: str) -> datetime.datetime | None:
            if pd.isna(val) or str(val).strip() == "":
                return None
            return datetime.datetime.fromisoformat(str(val))

        def _bool(val: str) -> bool:
            return str(val).strip().lower() in {"true", "1", "yes"}

        return {
            "paper_id": str(row["paper_id"]).strip(),
            "status": str(row["status"]).strip(),
            "qp_path": str(row["qp_path"]).strip(),
            "ms_path": str(row["ms_path"]).strip(),
            "score_raw": _nullable_float(row["score_raw"]),
            "score_total": _nullable_float(row["score_total"]),
            "sent_to_gn": _bool(row["sent_to_gn"]),
            "timestamp": _nullable_dt(row["timestamp"]),
        }

    @staticmethod
    def _record_to_row(record: PaperRecord) -> dict[str, object]:
        """Serialize a PaperRecord to a flat dict for DataFrame construction."""
        return {
            "paper_id": record.paper_id,
            "status": record.status,
            "qp_path": record.qp_path,
            "ms_path": record.ms_path,
            "score_raw": record.score_raw,
            "score_total": record.score_total,
            "percentage": record.percentage,
            "sent_to_gn": record.sent_to_gn,
            "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        }


# Canonical column order that matches MistakeRecord's fields
_MISTAKE_COLUMNS: list[str] = [
    "paper_id",
    "question_id",
    "topic_id",
    "topic_name",
    "score",
    "max_score",
    "comment",
    "timestamp",
]


class MistakeStore:
    """Persistence for MistakeRecord objects — the mistake notebook's store.

    A separate class rather than a generic rewrite of ``CSVStore``, whose
    methods are typed to ``PaperRecord``. Append-only by design: there is no
    ``update``, and re-grading a paper adds a second set of rows.
    """

    def __init__(self, csv_path: Path = app_settings.mistakes_csv) -> None:
        self._path = csv_path
        self._ensure_file()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> list[MistakeRecord]:
        """Read CSV → validate every row → return list of MistakeRecords."""
        df = pd.read_csv(self._path, dtype=str)
        records: list[MistakeRecord] = []
        errors: list[str] = []

        for idx, row in df.iterrows():
            try:
                records.append(
                    MistakeRecord.model_validate(
                        self._row_to_dict(row), strict=False
                    )
                )
            except ValidationError as exc:
                errors.append(f"Row {idx}: {exc.error_count()} error(s) — {exc}")

        if errors:
            # Surface all validation errors at once rather than silently
            # dropping rows — same contract as CSVStore.load_all.
            raise ValueError(
                f"mistakes.csv contains {len(errors)} invalid row(s):\n"
                + "\n".join(errors)
            )

        return records

    def save_all(self, records: Sequence[MistakeRecord]) -> None:
        """Validate and overwrite the entire CSV with the given records."""
        rows = [self._record_to_row(r) for r in records]
        df = pd.DataFrame(rows, columns=_MISTAKE_COLUMNS)
        df.to_csv(self._path, index=False)

    def append(self, record: MistakeRecord) -> None:
        """Append a single record. Duplicates are allowed — see class docs."""
        self.append_many([record])

    def append_many(self, records: Sequence[MistakeRecord]) -> None:
        """Append a whole grading run's mistakes in one rewrite.

        One paper yields a dozen or so rows at once; appending them one at a
        time would reload and rewrite the file once per row.
        """
        if not records:
            return
        self.save_all([*self.load_all(), *records])

    def delete(self, paper_id: str, question_id: str | None = None) -> None:
        """Remove one paper's rows, or just one question's within it.

        Re-grades mean a (paper_id, question_id) pair can match several rows;
        every match goes.
        """
        records = self.load_all()
        kept = [
            r
            for r in records
            if not (
                r.paper_id == paper_id
                and (question_id is None or r.question_id == question_id)
            )
        ]
        if len(kept) == len(records):
            target = (
                paper_id if question_id is None else f"{paper_id}/{question_id}"
            )
            raise KeyError(f"no mistake rows for '{target}'")
        self.save_all(kept)

    def to_dataframe(
        self, records: Sequence[MistakeRecord] | None = None
    ) -> pd.DataFrame:
        """Return a DataFrame of the given records (all of them by default)."""
        if records is None:
            records = self.load_all()
        return pd.DataFrame(
            [self._record_to_row(r) for r in records], columns=_MISTAKE_COLUMNS
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_file(self) -> None:
        """Create an empty CSV with headers if it doesn't exist yet."""
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(columns=_MISTAKE_COLUMNS).to_csv(
                self._path, index=False
            )

    @staticmethod
    def _row_to_dict(row: pd.Series[object]) -> dict[str, object]:
        """Convert a raw CSV row (all strings) into types Pydantic can coerce."""

        def _nullable_str(val: object) -> str | None:
            if pd.isna(val) or str(val).strip() == "":
                return None
            return str(val).strip()

        return {
            "paper_id": str(row["paper_id"]).strip(),
            "question_id": str(row["question_id"]).strip(),
            "topic_id": _nullable_str(row["topic_id"]),
            "topic_name": _nullable_str(row["topic_name"]),
            "score": float(str(row["score"])),
            "max_score": float(str(row["max_score"])),
            "comment": _nullable_str(row["comment"]) or "",
            "timestamp": datetime.datetime.fromisoformat(
                str(row["timestamp"]).strip()
            ),
        }

    @staticmethod
    def _record_to_row(record: MistakeRecord) -> dict[str, object]:
        """Serialize a MistakeRecord to a flat dict for DataFrame construction."""
        return {
            "paper_id": record.paper_id,
            "question_id": record.question_id,
            "topic_id": record.topic_id,
            "topic_name": record.topic_name,
            "score": record.score,
            "max_score": record.max_score,
            "comment": record.comment,
            "timestamp": record.timestamp.isoformat(),
        }
