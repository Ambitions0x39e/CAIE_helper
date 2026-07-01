from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Final

import pdfplumber
from pydantic import BaseModel, field_validator, model_validator

_GRADE_COLS: Final[list[str]] = ["A*", "A", "B", "C", "D", "E"]

# CIE GT PDFs use a non-standard font encoding that maps many characters
# to Private Use Area codepoints rendered as (cid:N) by pdfplumber.
# This table was derived empirically from 9231_s25_gt.pdf.
_CID_MAP: Final[dict[int, str]] = {
    13:  "*",
    15:  ",",
    23:  "4",
    25:  "6",
    26:  "7",
    27:  "8",
    29:  ":",
    37:  "B",
    39:  "D",
    40:  "E",
    49:  "1",
    50:  "O",
    55:  "T",
    59:  "X",
    60:  "Y",
    61:  "Z",
    84:  "q",
    90:  "w",
    177: "-",
}

_CID_RE = re.compile(r"\(cid:(\d+)\)")


def _decode(text: str | None) -> str:
    """Replace all (cid:N) sequences using the known CIE font mapping."""
    if not text:
        return ""
    return _CID_RE.sub(lambda m: _CID_MAP.get(int(m.group(1)), ""), text)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class GradeThreshold(BaseModel):
    model_config = {"strict": False}

    option: str
    max_weighted: int
    components: list[str]
    thresholds: dict[str, int]

    @field_validator("components")
    @classmethod
    def components_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("components list cannot be empty")
        return v

    @field_validator("thresholds")
    @classmethod
    def thresholds_valid(cls, v: dict[str, int]) -> dict[str, int]:
        for grade, mark in v.items():
            if mark < 0:
                raise ValueError(f"Threshold for grade {grade!r} cannot be negative")
        return v

    def grade_for_score(self, total_raw: int | float) -> str:
        """Check grades from highest downward; return 'U' if below all thresholds."""
        for grade in _GRADE_COLS:
            threshold = self.thresholds.get(grade)
            if threshold is not None and total_raw >= threshold:
                return grade
        return "U"

    @property
    def component_paper_types(self) -> list[str]:
        return [c[0] for c in self.components if c]


class GTDocument(BaseModel):
    model_config = {"strict": False}

    syllabus_id: str
    session: str
    options: list[GradeThreshold]

    @model_validator(mode="after")
    def must_have_options(self) -> GTDocument:
        if not self.options:
            raise ValueError(
                "No option rows found — PDF may not be a grade threshold document"
            )
        return self

    def get_option(self, option_code: str) -> GradeThreshold | None:
        return next((o for o in self.options if o.option == option_code), None)

    @property
    def option_codes(self) -> list[str]:
        return [o.option for o in self.options]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class GTParser:
    """
    Parses a CIE grade threshold PDF and extracts the Options table.
    Handles the non-standard CID font encoding used by Cambridge PDFs.
    """

    def parse(self, pdf_path: Path, session: str) -> GTDocument:
        if not pdf_path.exists():
            raise FileNotFoundError(f"GT PDF not found: {pdf_path}")

        syllabus_id = self._extract_syllabus_id(pdf_path)
        options = self._extract_options(pdf_path)

        return GTDocument(
            syllabus_id=syllabus_id,
            session=session,
            options=options,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_syllabus_id(pdf_path: Path) -> str:
        stem = pdf_path.stem  # e.g. '9231_s25_gt'
        match = re.match(r"(\d{4})", stem)
        if match:
            return match.group(1)
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = _decode(pdf.pages[0].extract_text() or "")
        match = re.search(r"\b(\d{4})\b", text)
        if match:
            return match.group(1)
        raise ValueError("Could not determine syllabus ID from PDF")

    def _extract_options(self, pdf_path: Path) -> list[GradeThreshold]:
        results: list[GradeThreshold] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    decoded = [
                        [_decode(cell) if cell is not None else None for cell in row]
                        for row in table
                    ]
                    results.extend(self._try_parse_options_table(decoded))
        return results

    @staticmethod
    def _merge_header_rows(
        table: list[list[str | None]], header_row_idx: int
    ) -> list[str]:
        """
        The options table has a multi-row header spanning 3 rows, e.g.:
          Row 0: ['Option', 'Maximum', 'Combination of components', '', '', 'B', ...]
          Row 1: [None, 'mark after', None, 'A*', 'A', None, 'C', 'D', 'E']
          Row 2: [None, 'weighting', None, '', '', None, '', '', '']

        Strategy: for each column index, take the first non-empty cell
        scanning downward across the header rows (rows 0..header_row_idx+2).
        This assembles ['Option', 'Maximum', ..., 'A*', 'A', 'B', 'C', 'D', 'E'].
        """
        # Scan at most 3 rows from the header row upward/downward
        scan_rows = table[max(0, header_row_idx - 1): header_row_idx + 3]
        n_cols = max((len(r) for r in scan_rows), default=0)
        flat: list[str] = [""] * n_cols

        for row in scan_rows:
            for i, cell in enumerate(row):
                if i < n_cols and cell and str(cell).strip() and not flat[i]:
                    flat[i] = str(cell).strip()

        return flat

    def _try_parse_options_table(
        self, table: list[list[str | None]]
    ) -> list[GradeThreshold]:
        if not table or len(table) < 2:
            return []

        # Find the row that contains 'Option'
        header_row_idx: int | None = None
        for idx, row in enumerate(table):
            normalised = [str(c or "").strip().lower() for c in row]
            if "option" in normalised:
                header_row_idx = idx
                break

        if header_row_idx is None:
            return []

        flat_header = self._merge_header_rows(table, header_row_idx)
        flat_lower = [h.lower().replace("\n", " ") for h in flat_header]

        # Locate column indices
        try:
            opt_idx = flat_lower.index("option")
        except ValueError:
            return []

        grade_indices: dict[str, int] = {}
        for i, cell in enumerate(flat_header):
            clean = cell.strip().upper()
            if clean in {"A*", "A", "B", "C", "D", "E"} and clean not in grade_indices:
                grade_indices[clean] = i

        comp_idx: int | None = next(
            (
                i
                for i, c in enumerate(flat_lower)
                if "component" in c or "combination" in c
            ),
            None,
        )
        max_idx: int | None = next(
            (i for i, c in enumerate(flat_lower) if "max" in c or "mark" in c),
            None,
        )

        # Data rows start after the last header row we merged
        data_start = min(header_row_idx + 3, len(table))
        results: list[GradeThreshold] = []

        for row in table[data_start:]:
            if not row or not row[opt_idx]:
                continue

            option_code = str(row[opt_idx]).strip().upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9]{1,2}", option_code):
                continue

            components: list[str] = []
            if comp_idx is not None and comp_idx < len(row) and row[comp_idx]:
                components = re.findall(r"\d+", str(row[comp_idx]))

            max_weighted = 0
            if max_idx is not None and max_idx < len(row) and row[max_idx]:
                with contextlib.suppress(ValueError):
                    max_weighted = int(str(row[max_idx]).strip())

            thresholds: dict[str, int] = {}
            for grade, idx in grade_indices.items():
                if idx < len(row) and row[idx] and row[idx] not in {"-", ""}:
                    with contextlib.suppress(ValueError):
                        thresholds[grade] = int(str(row[idx]).strip())

            if not thresholds or not components:
                continue

            try:
                results.append(
                    GradeThreshold(
                        option=option_code,
                        max_weighted=max_weighted,
                        components=components,
                        thresholds=thresholds,
                    )
                )
            except Exception:  # noqa: BLE001
                continue

        return results