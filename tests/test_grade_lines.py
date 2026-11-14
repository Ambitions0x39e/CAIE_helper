"""The trend chart's grade lines: percentages per paper, read once per session."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from core.gt_parser import ComponentThreshold, GTDocument, GTParser
from core.models import PaperRecord
from modules.downloader import DownloadRequest, DownloadResult
from modules.grade_lines import GradeLines, lines_for, position


def _component(component: str, max_raw: int, **thresholds: int) -> ComponentThreshold:
    return ComponentThreshold(
        component=component, max_raw=max_raw, thresholds=thresholds
    )


def test_a_star_is_halfway_between_a_and_full_marks() -> None:
    lines = lines_for(_component("42", 50, A=38, B=32, C=25, D=19, E=12))
    assert lines == {"A*": 88.0, "A": 76.0, "B": 64.0, "C": 50.0}


def test_a_paper_without_an_a_boundary_gets_no_a_star() -> None:
    # IGCSE Core components print "-" for A*–B.
    assert lines_for(_component("11", 40, C=26, D=23)) == {"C": 65.0}


_LINES = {"A*": 88.0, "A": 76.0, "B": 64.0, "C": 50.0}


@pytest.mark.parametrize(
    ("percentage", "expected"),
    [
        (0.0, 0.0),
        (25.0, 0.5),  # halfway to C
        (50.0, 1.0),  # on C
        (82.0, 3.5),  # halfway from A to A*
        (94.0, 4.5),  # halfway from A* to full marks
        (100.0, 5.0),
    ],
)
def test_position_interpolates_inside_the_band(
    percentage: float, expected: float
) -> None:
    assert position(percentage, _LINES) == pytest.approx(expected)


def test_a_score_on_tied_boundaries_takes_the_higher_grade() -> None:
    assert position(60.0, {**_LINES, "B": 60.0, "C": 60.0}) == 2.0


def test_position_needs_all_four_boundaries() -> None:
    assert position(70.0, {"C": 65.0}) is None


@pytest.fixture
def parsed(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    seen: list[Path] = []

    def parse(_self: GTParser, pdf: Path, session: str) -> GTDocument:
        seen.append(pdf)
        return GTDocument.model_construct(
            syllabus_id="9709",
            session=session,
            options=[],
            components=[_component("42", 50, A=38, B=32, C=25)],
        )

    monkeypatch.setattr(GTParser, "parse", parse)
    return seen


def test_lines_are_keyed_by_paper_and_the_session_is_read_once(
    tmp_path: Path,
    parsed: list[Path],
) -> None:
    (tmp_path / "9709_s25_gt.pdf").write_bytes(b"%PDF")
    lines = GradeLines(_no_fetch, tmp_path, tmp_path / "cache")

    first = lines.for_papers(["9709_s25_qp_42", "9709_s25_qp_43", "bogus"])
    again = lines.for_papers(["9709_s25_qp_42"])

    assert first == {"9709_s25_qp_42": {"A*": 88.0, "A": 76.0, "B": 64.0, "C": 50.0}}
    assert again == {"9709_s25_qp_42": first["9709_s25_qp_42"]}
    assert len(parsed) == 1  # the second call came from the cache


def test_a_missing_file_is_fetched_from_ciefrank(
    tmp_path: Path, parsed: list[Path]
) -> None:
    asked: list[DownloadRequest] = []

    def fetch(request: DownloadRequest) -> DownloadResult:
        asked.append(request)
        path = tmp_path / f"{request.paper_id}.pdf"
        path.write_bytes(b"%PDF")
        return DownloadResult(
            success=True, paper_id=request.paper_id, qp_path=str(path)
        )

    GradeLines(fetch, tmp_path, tmp_path / "cache").for_papers(["9709_w25_qp_42"])
    assert [(r.paper_id, r.source) for r in asked] == [("9709_w25_gt", "CIEFrank")]


def test_a_failed_fetch_is_not_cached(tmp_path: Path, parsed: list[Path]) -> None:
    lines = GradeLines(_no_fetch, tmp_path, tmp_path / "cache")
    assert lines.for_papers(["9709_w25_qp_42"]) == {}
    assert not (tmp_path / "cache").exists()


def _no_fetch(request: DownloadRequest) -> DownloadResult:
    return DownloadResult(success=False, paper_id=request.paper_id, error="404")


def _record(paper_id: str, raw: float, day: int) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        status="Completed",
        score_raw=raw,
        score_total=50.0,
        timestamp=datetime.datetime(2026, 4, day, tzinfo=datetime.UTC),
    )


def test_one_components_trend_is_tested_in_the_order_it_was_scored(
    tmp_path: Path, parsed: list[Path]
) -> None:
    sessions = [f"s{y}" for y in range(18, 26)]
    for s in sessions:
        (tmp_path / f"9709_{s}_gt.pdf").write_bytes(b"%PDF")
    # Listed newest first; the test must still see a climb.
    records = [
        _record(f"9709_{s}_qp_42", 49.0 - i, day=10 - i) for i, s in enumerate(sessions)
    ]
    trend = GradeLines(_no_fetch, tmp_path, tmp_path / "cache").trend(records)
    assert len(trend.points) == 8
    assert trend.progress is not None
    assert trend.progress.improved


def test_two_components_are_not_tested_as_one_series(
    tmp_path: Path, parsed: list[Path]
) -> None:
    (tmp_path / "9709_s25_gt.pdf").write_bytes(b"%PDF")
    records = [_record("9709_s25_qp_42", 40.0, day=i + 1) for i in range(6)]
    records.append(_record("9709_s25_qp_32", 40.0, day=20))
    trend = GradeLines(_no_fetch, tmp_path, tmp_path / "cache").trend(records)
    assert trend.progress is None
