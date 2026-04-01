from __future__ import annotations

import datetime
from pathlib import Path
from typing import Sequence

import pandas as pd
from pydantic import ValidationError

from core.models import PaperRecord
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

    def to_dataframe(self) -> pd.DataFrame:
        """Return a DataFrame of all records (useful for Streamlit display)."""
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
    def _row_to_dict(row: pd.Series) -> dict[str, object]:  # type: ignore[type-arg]
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
