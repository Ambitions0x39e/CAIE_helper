from __future__ import annotations

import csv
import datetime
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

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


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
#
# ``newline=""`` on both sides is load-bearing on Windows, not decoration: the
# csv module writes its own ``\r\n``, so letting text mode translate as well
# produces ``\r\r\n`` and a blank line between every row.


@contextmanager
def _reading(path: Path) -> Iterator[IO[str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        yield fh


@contextmanager
def _writing(path: Path) -> Iterator[IO[str]]:
    with path.open("w", encoding="utf-8", newline="") as fh:
        yield fh


def _write_rows(
    path: Path, columns: list[str], rows: Sequence[Mapping[str, object]]
) -> None:
    with _writing(path) as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _cell(row: Mapping[str, str | None], key: str) -> str:
    """One cell as a stripped string — blank for a missing or empty column."""
    return (row.get(key) or "").strip()


def _nullable_float(value: str) -> float | None:
    """``""`` → None, leaving the field's own validator to judge the blank.

    Never NaN: a blank cell parsed as NaN passes both the non-negative and the
    ``score <= max_score`` checks, since ``nan < 0`` and ``nan > max`` are both
    False — a mark that is silently neither too low nor too high. None cannot
    pass any of them.
    """
    return float(value) if value else None


def _nullable_dt(value: str) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(value) if value else None


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
        records: list[PaperRecord] = []
        errors: list[str] = []

        with _reading(self._path) as fh:
            for idx, row in enumerate(csv.DictReader(fh)):
                try:
                    records.append(
                        PaperRecord.model_validate(
                            self._row_to_dict(row), strict=False
                        )
                    )
                except ValidationError as exc:
                    errors.append(
                        f"Row {idx}: {exc.error_count()} error(s) — {exc}"
                    )

        if errors:
            # Surface all validation errors at once rather than silently dropping rows
            raise ValueError(
                f"data.csv contains {len(errors)} invalid row(s):\n"
                + "\n".join(errors)
            )

        return records

    def save_all(self, records: Sequence[PaperRecord]) -> None:
        """Validate and overwrite the entire CSV with the given records."""
        _write_rows(self._path, _COLUMNS, [self._record_to_row(r) for r in records])

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_file(self) -> None:
        """Create an empty CSV with headers if it doesn't exist yet."""
        if not self._path.exists():
            _write_rows(self._path, _COLUMNS, [])

    @staticmethod
    def _row_to_dict(row: Mapping[str, str | None]) -> dict[str, object]:
        """Convert a raw CSV row (all strings) into types Pydantic can coerce."""
        return {
            "paper_id": _cell(row, "paper_id"),
            "status": _cell(row, "status"),
            "qp_path": _cell(row, "qp_path"),
            "ms_path": _cell(row, "ms_path"),
            "score_raw": _nullable_float(_cell(row, "score_raw")),
            "score_total": _nullable_float(_cell(row, "score_total")),
            "sent_to_gn": _cell(row, "sent_to_gn").lower() in {"true", "1", "yes"},
            "timestamp": _nullable_dt(_cell(row, "timestamp")),
        }

    @staticmethod
    def _record_to_row(record: PaperRecord) -> dict[str, Any]:
        """Serialize a PaperRecord to a flat dict of CSV cells."""
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
        records: list[MistakeRecord] = []
        errors: list[str] = []

        with _reading(self._path) as fh:
            for idx, row in enumerate(csv.DictReader(fh)):
                try:
                    records.append(
                        MistakeRecord.model_validate(
                            self._row_to_dict(row), strict=False
                        )
                    )
                except ValidationError as exc:
                    errors.append(
                        f"Row {idx}: {exc.error_count()} error(s) — {exc}"
                    )

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
        _write_rows(
            self._path, _MISTAKE_COLUMNS, [self._record_to_row(r) for r in records]
        )

    def append_many(self, records: Sequence[MistakeRecord]) -> None:
        """Append a whole grading run's mistakes in one rewrite.

        Duplicates are allowed — see the class docs. One paper yields a dozen
        or so rows at once; appending them one at a time would reload and
        rewrite the file once per row.
        """
        if not records:
            return
        self.save_all([*self.load_all(), *records])

    def update_at(self, index: int, record: MistakeRecord) -> None:
        """Replace the row at *index* (its position in ``load_all``).

        By position rather than by key: append-only means a re-grade repeats
        the same (paper_id, question_id) pair, so nothing else identifies one
        row. The caller reads with ``load_all`` and writes back the index it
        got — which is exactly how the 错题本 tab already tracks its rows.
        """
        records = self.load_all()
        if not 0 <= index < len(records):
            raise IndexError(
                f"no mistake row at index {index} (store holds {len(records)})"
            )
        records[index] = record
        self.save_all(records)

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_file(self) -> None:
        """Create an empty CSV with headers if it doesn't exist yet."""
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _write_rows(self._path, _MISTAKE_COLUMNS, [])

    @staticmethod
    def _row_to_dict(row: Mapping[str, str | None]) -> dict[str, object]:
        """Convert a raw CSV row (all strings) into types Pydantic can coerce."""
        return {
            "paper_id": _cell(row, "paper_id"),
            "question_id": _cell(row, "question_id"),
            "topic_id": _cell(row, "topic_id") or None,
            "topic_name": _cell(row, "topic_name") or None,
            "score": _nullable_float(_cell(row, "score")),
            "max_score": _nullable_float(_cell(row, "max_score")),
            "comment": _cell(row, "comment"),
            "timestamp": datetime.datetime.fromisoformat(_cell(row, "timestamp")),
        }

    @staticmethod
    def _record_to_row(record: MistakeRecord) -> dict[str, Any]:
        """Serialize a MistakeRecord to a flat dict of CSV cells."""
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
