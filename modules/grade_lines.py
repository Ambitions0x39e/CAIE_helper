"""Each paper's score against its own A* / A / B / C — the 管理 trend chart.

A paper's lines come from its session's grade-threshold PDF: the table of
single-component boundaries printed above the options. The PDF is fetched from
CIEFrank the first time a session is asked for, and its component table is
cached in ``~/.cie_helper/.cache/gt/``. A session with no threshold file, or a
component missing from it, leaves that paper without lines.

The chart plots :func:`position`, not the raw percentage: the boundaries move
from paper to paper with its difficulty, and on the grade scale they hold
still, so a point rising across papers is a score rising against them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError

from core.gt_parser import ComponentThreshold, GTParser
from core.models import PaperRecord
from modules.downloader import DownloadRequest, DownloadResult
from modules.progress import Progress, progress

GRADES = ("A*", "A", "B", "C")

#: Each boundary's height on the grade scale: one unit per band, 0% at the
#: bottom and full marks at :data:`TOP`.
LEVELS = {"C": 1.0, "B": 2.0, "A": 3.0, "A*": 4.0}
TOP = 5.0

_COMPONENTS = TypeAdapter(list[ComponentThreshold])

Fetch = Callable[[DownloadRequest], DownloadResult]


class PaperLines(BaseModel):
    lines: dict[str, float]
    #: The score on the grade scale; None without a percentage or a boundary.
    position: float | None


class Trend(BaseModel):
    points: dict[str, PaperLines]
    #: Only for papers of one component — Paper 4 of one syllabus, say. Two
    #: components' scores are not one series to test.
    progress: Progress | None


def position(percentage: float, lines: dict[str, float]) -> float | None:
    """*percentage* on the grade scale, interpolated linearly inside the band
    it falls in: 3.5 is halfway from this paper's A to its A*.

    A score exactly on a boundary sits on it, tied boundaries included —
    reaching the mark earns the higher grade.
    """
    if any(g not in lines for g in GRADES):
        return None
    knots = [
        (0.0, 0.0),
        *sorted((lines[g], LEVELS[g]) for g in GRADES),
        (100.0, TOP),
    ]
    for (p0, y0), (p1, y1) in zip(knots, knots[1:], strict=False):
        if percentage < p1:
            return y0 + (percentage - p0) / (p1 - p0) * (y1 - y0)
    return TOP


def lines_for(threshold: ComponentThreshold) -> dict[str, float]:
    """Each grade's boundary as a percentage of the paper's maximum.

    CIE publishes no A* for a single component, so it is taken as halfway
    between A and full marks.
    """
    marks = {g: float(v) for g, v in threshold.thresholds.items()}
    if "A" in marks:
        marks["A*"] = (marks["A"] + threshold.max_raw) / 2
    return {
        g: round(marks[g] / threshold.max_raw * 100, 1) for g in GRADES if g in marks
    }


def _component(paper_id: str) -> str:
    """``9709_s25_qp_42`` → ``9709_4``: the syllabus and paper number."""
    parts = paper_id.split("_")
    return f"{parts[0]}_{parts[-1][:1]}"


class GradeLines:
    def __init__(self, fetch: Fetch, pdfs_dir: Path, cache_dir: Path) -> None:
        self._fetch = fetch
        self._pdfs_dir = pdfs_dir
        self._cache_dir = cache_dir

    def for_papers(self, paper_ids: Iterable[str]) -> dict[str, dict[str, float]]:
        """``{"9709_s25_qp_42": {"A*": 88.0, "A": 76.0, ...}}`` for every paper
        whose lines are known; the rest are left out."""
        sessions: dict[str, dict[str, ComponentThreshold]] = {}
        out: dict[str, dict[str, float]] = {}
        for paper_id in paper_ids:
            parts = paper_id.split("_")
            if len(parts) != 4 or parts[2] != "qp":
                continue
            syllabus, session, _, component = parts
            gt_id = f"{syllabus}_{session}_gt"
            if gt_id not in sessions:
                sessions[gt_id] = self._components(gt_id, session)
            if component in sessions[gt_id]:
                out[paper_id] = lines_for(sessions[gt_id][component])
        return out

    def for_records(self, records: Iterable[PaperRecord]) -> dict[str, PaperLines]:
        """The chart's points: every paper whose lines are known, with its
        score placed among them."""
        records = list(records)
        known = self.for_papers(r.paper_id for r in records)
        return {
            r.paper_id: PaperLines(
                lines=known[r.paper_id],
                position=None
                if r.percentage is None
                else position(r.percentage, known[r.paper_id]),
            )
            for r in records
            if r.paper_id in known
        }

    def trend(self, records: Iterable[PaperRecord]) -> Trend:
        """The chart's points, and whether the later papers sit higher than
        the earlier ones, in the order they were scored."""
        records = list(records)
        points = self.for_records(records)
        components = {_component(r.paper_id) for r in records}
        # An undated row has no place in the order, so it is left out of the
        # test; it is still a point on the chart.
        dated = sorted(
            ((r.timestamp, r.paper_id) for r in records if r.timestamp is not None),
        )
        positions = [
            p.position
            for _, paper_id in dated
            if (p := points.get(paper_id)) and p.position is not None
        ]
        return Trend(
            points=points,
            progress=progress(positions) if len(components) == 1 else None,
        )

    def _components(self, gt_id: str, session: str) -> dict[str, ComponentThreshold]:
        cached = self._cache_dir / f"{gt_id}.json"
        try:
            rows = _COMPONENTS.validate_json(cached.read_bytes())
        except (OSError, ValidationError):
            rows = self._parse(gt_id, session)
            if rows:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(_COMPONENTS.dump_json(rows))
        return {r.component: r for r in rows}

    def _parse(self, gt_id: str, session: str) -> list[ComponentThreshold]:
        """Nothing is cached when this comes back empty, so a session that
        failed to download is tried again next time.

        ponytail: a session CIEFrank has no file for is re-requested on
        every call; remember the 404s if that ever shows up as lag.
        """
        pdf = self._pdfs_dir / f"{gt_id}.pdf"
        if not pdf.exists():
            result = self._fetch(DownloadRequest(paper_id=gt_id, source="CIEFrank"))
            if not result.success or not result.qp_path:
                return []
            pdf = Path(result.qp_path)
        try:
            return GTParser().parse(pdf, session).components
        except Exception:  # noqa: BLE001 — a third-party PDF; no lines, not a crash
            return []
