"""Parse CIE grade-threshold PDFs into per-option grade boundaries.

Backed by **pdfminer.six**, not pdfplumber. pdfplumber's only irreplaceable
feature here was ``extract_tables()``; everything else it does is pdfminer
underneath (including the ``(cid:N)`` rendering the CID map below relies on).
Dropping it makes this module iOS-safe — pdfplumber pulls in pypdfium2, which
has no iOS wheel and would break ``flet build ipa`` — so grade thresholds can
ship in the packaged app instead of hiding behind the ``gt`` extra.

Table reconstruction (:func:`_extract_tables`) works off the ruling lines the
PDFs actually draw, the same signal pdfplumber's default strategy uses: CIE
renders every table border as a thin ``LTRect``, so the vertical rules give
the column boundaries and the horizontal rules the row boundaries.
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Final

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTContainer, LTRect
from pydantic import BaseModel, field_validator, model_validator

_GRADE_COLS: Final[list[str]] = ["A*", "A", "B", "C", "D", "E"]

# A border is a rect thinner than this; anything fatter is a filled block.
_RULE_MAX_THICKNESS: Final[float] = 3.0
# Rules closer together than this are the same boundary drawn twice
# (CIE double-strokes most borders — hence ~200 rects for ~10 columns).
_RULE_MERGE_TOL: Final[float] = 3.0
# Ignore stub marks; a real rule spans at least this many points.
_RULE_MIN_LENGTH: Final[float] = 4.0
# A separator must reach this fraction of the page's longest rule. Tuned on
# 9231_s23/s25 and 9701_w25: header-only verticals sit near 0.1, the real
# column separators at 1.0, so anything in the middle works.
_RULE_SPAN_RATIO: Final[float] = 0.5

# CIE GT PDFs embed Arial as an Identity-H CIDFontType2 subset with **no**
# ToUnicode CMap, and the subsetter strips the font's own `cmap` table too —
# so pdfminer has nothing to decode with and emits "(cid:N)", where N is the
# raw glyph id.
#
# Those glyph ids turn out to be the standard Macintosh TrueType glyph order,
# whose entries 3..97 run straight through printable ASCII: 3 is space, 19 is
# "0", 36 is "A", and so on. That single rule reproduced 17 of the 19 entries
# in the hand-built table this replaced.
#
# The table it replaced was transcribed by eye from ONE document
# (9231_s25_gt.pdf) and silently mistranslated every other syllabus, because
# a missing id was dropped rather than flagged: 9701_w25 rendered its D
# threshold as "10" instead of 103. Deriving the mapping instead of listing
# it fixes every font subset at once.
_GLYPH_ID_SPACE: Final[int] = 3
_GLYPH_ID_TILDE: Final[int] = 97

# Beyond the ASCII run the order is MacRoman-ish; only the codepoints these
# documents actually use are worth naming.
_CID_EXTRAS: Final[dict[int, str]] = {
    177: "-",  # en dash, as in "Grade thresholds - November 2025"
}

_CID_RE = re.compile(r"\(cid:(\d+)\)")


def _cid_to_char(gid: int) -> str:
    """Map a raw glyph id to its character, or "" if it is not known."""
    if _GLYPH_ID_SPACE <= gid <= _GLYPH_ID_TILDE:
        return chr(0x20 + gid - _GLYPH_ID_SPACE)
    return _CID_EXTRAS.get(gid, "")


def _decode(text: str | None) -> str:
    """Resolve every (cid:N) escape pdfminer left in the extracted text."""
    if not text:
        return ""
    return _CID_RE.sub(lambda m: _cid_to_char(int(m.group(1))), text)


# ---------------------------------------------------------------------------
# Table reconstruction (pdfminer)
# ---------------------------------------------------------------------------


def _walk(element: object, chars: list[LTChar], rects: list[LTRect]) -> None:
    """Flatten a pdfminer layout tree into its chars and rects."""
    if not isinstance(element, LTContainer):
        return
    for item in element:
        if isinstance(item, LTChar):
            chars.append(item)
        elif isinstance(item, LTRect):
            rects.append(item)
        if isinstance(item, LTContainer):
            _walk(item, chars, rects)


def _merge_positions(values: list[float]) -> list[float]:
    """Collapse near-duplicate rule positions into one boundary each."""
    boundaries: list[float] = []
    for v in sorted(values):
        if not boundaries or v - boundaries[-1] > _RULE_MERGE_TOL:
            boundaries.append(v)
        else:
            boundaries[-1] = (boundaries[-1] + v) / 2
    return boundaries


def _cell_index(boundaries: list[float], pos: float) -> int | None:
    """Which slot between *boundaries* does *pos* fall in? None if outside."""
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= pos <= boundaries[i + 1]:
            return i
    return None


def _spanning(rules: list[LTRect], *, vertical: bool) -> list[LTRect]:
    """Keep only the rules long enough to separate a whole table.

    A column separator runs its table's full height; a rule covering one
    header row is decoration and must not be projected onto the data rows
    (that is what split "250" into "25" + "0").

    Each rule is judged against the rules it *overlaps*, not against the
    longest on the page: a page can hold two tables of different heights, and
    measuring the short table's separators against the tall one's deletes
    them all — which collapsed a whole grid into a single column.
    """
    if not rules:
        return []

    def extent(r: LTRect) -> tuple[float, float, float]:
        # (start, end, length) along the rule's long axis.
        return (r.y0, r.y1, r.height) if vertical else (r.x0, r.x1, r.width)

    spans = [extent(r) for r in rules]
    kept: list[LTRect] = []
    for rule, (lo, hi, length) in zip(rules, spans, strict=True):
        peers = [
            plen for plo, phi, plen in spans if plo < hi and phi > lo
        ]
        if length >= max(peers) * _RULE_SPAN_RATIO:
            kept.append(rule)
    return kept


def _cell_text(chars: list[LTChar]) -> str:
    """Read a cell's glyphs back in visual order.

    A header cell like "Combination of / components" is two printed lines. A
    plain left-to-right sort interleaves them into "Ccoommbpinoanteionnt so f",
    which then fails every substring check downstream — so group into lines by
    baseline first, top-down, and only sort by x inside a line.
    """
    lines: list[list[LTChar]] = []
    for ch in sorted(chars, key=lambda c: -c.y1):
        placed = False
        for line in lines:
            # Same printed line if the baselines overlap vertically at all.
            if abs(line[0].y1 - ch.y1) <= max(ch.height, line[0].height) / 2:
                line.append(ch)
                placed = True
                break
        if not placed:
            lines.append([ch])

    return "\n".join(
        "".join(c.get_text() for c in sorted(line, key=lambda c: c.x0)).strip()
        for line in lines
    ).strip()


def _cluster_by_extent(rules: list[LTRect]) -> list[list[LTRect]]:
    """Group vertical rules into one cluster per table, by y overlap.

    A page can carry several tables with different column positions (the CIE
    GT front page has one at y≈158-196 and another at y≈543-598). Pooling
    their verticals into a single boundary list projects each table's columns
    onto the other and slices the cells apart — that is what turned "250"
    into "25" + "0". Rules that share vertical extent belong to one table.
    """
    clusters: list[list[LTRect]] = []
    for rule in sorted(rules, key=lambda r: r.y0):
        for cluster in clusters:
            top = max(r.y1 for r in cluster)
            bottom = min(r.y0 for r in cluster)
            if rule.y0 <= top + _RULE_MERGE_TOL and rule.y1 >= bottom:
                cluster.append(rule)
                break
        else:
            clusters.append([rule])
    return clusters


def _extract_tables(pdf_path: Path) -> list[list[list[str | None]]]:
    """Rebuild every ruled table in the PDF as a grid of cell strings."""
    tables: list[list[list[str | None]]] = []

    for layout in extract_pages(str(pdf_path), laparams=LAParams()):
        chars: list[LTChar] = []
        rects: list[LTRect] = []
        _walk(layout, chars, rects)
        if not chars or not rects:
            continue

        v_rules = [
            r for r in rects
            if r.width <= _RULE_MAX_THICKNESS and r.height >= _RULE_MIN_LENGTH
        ]
        h_rules = [
            r for r in rects
            if r.height <= _RULE_MAX_THICKNESS and r.width >= _RULE_MIN_LENGTH
        ]

        for cluster in _cluster_by_extent(v_rules):
            top = max(r.y1 for r in cluster)
            bottom = min(r.y0 for r in cluster)
            # Only full-height rules separate columns; a rule covering one
            # header row is decoration and must not reach the data rows.
            col_bounds = _merge_positions(
                [(r.x0 + r.x1) / 2 for r in _spanning(cluster, vertical=True)]
            )
            row_bounds = _merge_positions([
                (r.y0 + r.y1) / 2 for r in h_rules
                if bottom - _RULE_MERGE_TOL
                <= (r.y0 + r.y1) / 2
                <= top + _RULE_MERGE_TOL
            ])
            if len(col_bounds) < 2 or len(row_bounds) < 2:
                continue

            # (row, col) -> chars, keyed off each glyph's centre.
            cells: dict[tuple[int, int], list[LTChar]] = {}
            for ch in chars:
                col = _cell_index(col_bounds, (ch.x0 + ch.x1) / 2)
                row = _cell_index(row_bounds, (ch.y0 + ch.y1) / 2)
                if col is None or row is None:
                    continue  # outside this table — other table, or page furniture
                cells.setdefault((row, col), []).append(ch)
            if not cells:
                continue

            grid: list[list[str | None]] = []
            # row_bounds run bottom-up (PDF origin); emit top-down like the page.
            for row in reversed(range(len(row_bounds) - 1)):
                line: list[str | None] = []
                for col in range(len(col_bounds) - 1):
                    got = cells.get((row, col))
                    line.append(_cell_text(got) or None if got else None)
                grid.append(line)
            tables.append(grid)

    return tables


def _page_text(pdf_path: Path) -> str:
    """First page's text, for the syllabus-id fallback."""
    for layout in extract_pages(str(pdf_path), laparams=LAParams()):
        chars: list[LTChar] = []
        _walk(layout, chars, [])
        return "".join(c.get_text() for c in chars)
    return ""


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

    @model_validator(mode="after")
    def thresholds_must_not_invert(self) -> GradeThreshold:
        """A higher grade can never need fewer marks than a lower one.

        This is the net under the CID decoding. These PDFs ship no usable
        character map, so a glyph id we cannot resolve is dropped — and a
        dropped digit turns 103 into 10, which reads as a perfectly plausible
        grade boundary. An inversion (D=10 below E=80) is the fingerprint of
        exactly that, and _try_parse_options_table skips rows that fail to
        construct. Better to lose a row than to tell someone they got a D.

        Ties are allowed: only a genuine inversion is rejected.
        """
        ranked = [
            (g, self.thresholds[g]) for g in _GRADE_COLS if g in self.thresholds
        ]
        for (high, hv), (low, lv) in zip(ranked, ranked[1:], strict=False):
            if hv < lv:
                raise ValueError(
                    f"threshold for {high} ({hv}) is below {low} ({lv}) — "
                    "the source text was probably mis-decoded"
                )
        if self.max_weighted > 0:
            over = [f"{g}={v}" for g, v in ranked if v > self.max_weighted]
            if over:
                raise ValueError(
                    f"threshold(s) above the paper maximum "
                    f"{self.max_weighted}: {', '.join(over)}"
                )
        return self

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
        match = re.search(r"\b(\d{4})\b", _decode(_page_text(pdf_path)))
        if match:
            return match.group(1)
        raise ValueError("Could not determine syllabus ID from PDF")

    def _extract_options(self, pdf_path: Path) -> list[GradeThreshold]:
        results: list[GradeThreshold] = []
        for table in _extract_tables(pdf_path):
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

        # Start straight after the header row and let the option-code regex
        # below reject anything that is still header. The old "+3" assumed
        # pdfplumber's three physical header rows; the line-based grid folds
        # that stack into one, so +3 swallowed the first two options.
        results: list[GradeThreshold] = []

        for row in table[header_row_idx + 1:]:
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