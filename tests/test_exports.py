"""Export records: the ``.cpd`` store and the snapshot written into it."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from core.models import ExportedQuestion, ExportManifest, PaperType
from core.storage import ExportStore
from modules import exports

_NOW = datetime.datetime(2026, 10, 9, 15, 30, 12)


def _manifest(export_id: str = "20261009-153012-practice") -> ExportManifest:
    return ExportManifest(
        export_id=export_id, kind="practice", title="9709 P4", created_at=_NOW,
        questions=[
            ExportedQuestion(paper_id="9709_s24_qp_41", question_id="Q3", pages=[1, 2]),
        ],
        papers={},
    )


def test_a_record_reads_back_as_written(tmp_path: Path) -> None:
    store = ExportStore(tmp_path)
    path = store.write(_manifest(), b"%PDF-blank")

    assert path.name == "20261009-153012-practice.cpd"
    assert store.read("20261009-153012-practice") == _manifest()
    assert store.blank_pdf("20261009-153012-practice") == b"%PDF-blank"


def test_marking_graded_keeps_the_blank_paper(tmp_path: Path) -> None:
    store = ExportStore(tmp_path)
    store.write(_manifest(), b"%PDF-blank")

    store.mark_graded("20261009-153012-practice", _NOW)

    assert store.read("20261009-153012-practice").graded_at == _NOW
    assert store.blank_pdf("20261009-153012-practice") == b"%PDF-blank"
    assert [p.name for p in tmp_path.iterdir()] == ["20261009-153012-practice.cpd"]


def test_the_list_is_cpd_files_newest_first(tmp_path: Path) -> None:
    store = ExportStore(tmp_path)
    store.write(_manifest("20261008-090000-mistakes").model_copy(update={
        "kind": "mistakes", "created_at": _NOW - datetime.timedelta(days=1),
    }), b"%PDF")
    store.write(_manifest(), b"%PDF")
    (tmp_path / "manifest.json").write_text("{}", "utf-8")
    (tmp_path / "20261007-000000-practice.cpd").write_bytes(b"not a zip")

    assert [m.export_id for m in store.load_all()] == [
        "20261009-153012-practice", "20261008-090000-mistakes",
    ]


@pytest.mark.parametrize("bad", ["../data", "20261009-153012-practice/../x", ""])
def test_an_id_that_is_not_one_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        ExportStore(tmp_path).read(bad)


def test_the_snapshot_holds_what_grading_the_export_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each paper's mark scheme parts for the exported questions only, the
    type the mark scheme was parsed for, and the paper's topics."""
    from core.settings import app_settings

    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    app_settings.ms_cache_dir.mkdir(parents=True)
    (app_settings.ms_cache_dir / "9709_s24_ms_41.sp4.json").write_text(json.dumps({
        "paper_id": "9709/41/M/J/24", "total_marks": 50, "paper_type": "physics",
        "questions": {
            "Q2a": {"max_marks": 2, "mark_scheme": "B1: x = 3"},
            "Q2b": {"max_marks": 3, "mark_scheme": "M1: v = u + at"},
            "Q3": {"max_marks": 4, "mark_scheme": "M1"},
        },
    }), "utf-8")
    monkeypatch.setattr(
        exports, "build_export",
        lambda _r, _qp, export_id: (
            b"%PDF",
            {("9709_s24_qp_41", "Q2"): [1, 2], ("9709_w24_qp_42", "Q1"): [3]},
            [],
        ),
    )
    monkeypatch.setattr(
        "modules.marking.syllabus_parser.resolve_grading_type", lambda _pid: None,
    )

    manifest, data, warnings = exports.build_record(
        "practice", "9709 P4", [], {},
        {"9709_s24_qp_41": "/gone/9709_s24_ms_41.pdf"}, now=_NOW,
    )

    assert manifest.export_id == "20261009-153012-practice"
    assert [(q.paper_id, q.question_id, q.pages) for q in manifest.questions] == [
        ("9709_s24_qp_41", "Q2", [1, 2]), ("9709_w24_qp_42", "Q1", [3]),
    ]
    parsed = manifest.papers["9709_s24_qp_41"]
    assert parsed.paper_type is PaperType.PHYSICS
    assert parsed.ms is not None and sorted(parsed.ms) == ["Q2a", "Q2b"]
    unparsed = manifest.papers["9709_w24_qp_42"]
    assert (unparsed.paper_type, unparsed.ms) == (None, None)
    assert warnings == ["9709_w24_qp_42: 不知道批改类型，这几题交回时不能批改"]
    assert data == b"%PDF"
