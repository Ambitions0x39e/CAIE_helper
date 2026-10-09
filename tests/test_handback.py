"""Handing an export back: pages matched to questions by their markers, a
sheet built from the export's snapshot, and the run confirmed against it."""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import pytest
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
)

from core.models import (
    ExportedMark,
    ExportedPaper,
    ExportedQuestion,
    ExportManifest,
    PaperType,
)
from modules.marking.sheet import ForeignPaper, pages_by_question, sheet_from_export
from modules.question_pdf import Band, QuestionCrop, compose_pdf

_ID = "20261009-220129-practice"
_P1 = "9231_s25_qp_31"
_P2 = "9231_s25_qp_32"


def _source(path: Path) -> Path:
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Helvetica", size=10)
    pdf.add_page()
    pdf.text(72, 60, "6  Two uniform smooth spheres A and B.")
    pdf.output(str(path))
    return path


def _blank(tmp_path: Path) -> bytes:
    """P1 Q6 over two pages, then P2 Q6 on one."""
    source = str(_source(tmp_path / "qp.pdf"))
    data, pages = compose_pdf([
        QuestionCrop(_P1, "Q6", source, [
            Band(0, 50.0, 400.0), Band(0, 50.0, 760.0),
        ]),
        QuestionCrop(_P2, "Q6", source, [Band(0, 50.0, 400.0)]),
    ], _ID)
    assert pages == {(_P1, "Q6"): [1, 2], (_P2, "Q6"): [3]}
    return data


def _write(tmp_path: Path, data: bytes, name: str = "back.pdf") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _rebuild(data: bytes, order: list[int | None]) -> bytes:
    """The pages of *data* in *order*; None is a page added in GoodNotes."""
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for index in order:
        if index is None:
            writer.add_blank_page(width=612, height=792)
        else:
            writer.add_page(reader.pages[index])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _wrapped(data: bytes) -> bytes:
    """Every page drawn through a form XObject, as a layered export may."""
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        form = DecodedStreamObject()
        form.set_data(page.get_contents().get_data())
        form[NameObject("/Type")] = NameObject("/XObject")
        form[NameObject("/Subtype")] = NameObject("/Form")
        form[NameObject("/BBox")] = ArrayObject(
            [FloatObject(v) for v in (0, 0, 612, 792)]
        )
        form[NameObject("/Resources")] = page["/Resources"].clone(writer)
        out_page = writer.add_blank_page(width=612, height=792)
        out_page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({
                NameObject("/X0"): writer._add_object(form),
            }),
        })
        content = DecodedStreamObject()
        content.set_data(b"q /X0 Do Q")
        out_page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class TestPagesByQuestion:
    def test_each_page_goes_to_its_marker(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _blank(tmp_path))

        assert pages_by_question(path, _ID) == {
            (_P1, "Q6"): [1, 2], (_P2, "Q6"): [3],
        }

    def test_an_added_page_belongs_to_the_question_before_it(
        self, tmp_path: Path,
    ) -> None:
        path = _write(tmp_path, _rebuild(_blank(tmp_path), [0, None, 1, 2]))

        assert pages_by_question(path, _ID) == {
            (_P1, "Q6"): [1, 2, 3], (_P2, "Q6"): [4],
        }

    def test_pages_before_the_first_marker_are_dropped(
        self, tmp_path: Path,
    ) -> None:
        path = _write(tmp_path, _rebuild(_blank(tmp_path), [None, 0, 1, 2]))

        assert pages_by_question(path, _ID) == {
            (_P1, "Q6"): [2, 3], (_P2, "Q6"): [4],
        }

    def test_another_exports_paper_is_refused(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _blank(tmp_path))

        with pytest.raises(ForeignPaper):
            pages_by_question(path, "20261010-090000-practice")

    def test_a_marker_inside_a_form_xobject_is_read(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _wrapped(_blank(tmp_path)))

        assert pages_by_question(path, _ID) == {
            (_P1, "Q6"): [1, 2], (_P2, "Q6"): [3],
        }


def _manifest(**over: object) -> ExportManifest:
    ms = {
        "Q6a": ExportedMark(max_marks=3, mark_scheme="M1 A1 A1"),
        "Q6b": ExportedMark(max_marks=6, mark_scheme="B1 M1 A1 M1 A1 A1"),
    }
    return ExportManifest(**{
        "export_id": _ID, "kind": "practice", "title": "9231 P3 · 3.6",
        "created_at": datetime.datetime(2026, 10, 9, 22, 1, 29),
        "questions": [
            ExportedQuestion(paper_id=_P1, question_id="Q6", pages=[1, 2]),
            ExportedQuestion(paper_id=_P2, question_id="Q6", pages=[3]),
        ],
        "papers": {
            pid: ExportedPaper(
                paper_type=PaperType.MATH, topics={"3.6": "Momentum"}, ms=ms,
            )
            for pid in (_P1, _P2)
        },
        **over,
    })


class TestSheetFromExport:
    def test_a_main_question_becomes_its_parts_on_its_pages(
        self, tmp_path: Path,
    ) -> None:
        path = _write(tmp_path, _blank(tmp_path))

        back = sheet_from_export(_manifest(), path)

        assert (back.sheet.kind, back.sheet.export_id) == ("practice", _ID)
        assert [(i.paper_id, i.question_id, i.pages) for i in back.sheet.items] == [
            (_P1, "Q6a", [1, 2]), (_P1, "Q6b", [1, 2]),
            (_P2, "Q6a", [3]), (_P2, "Q6b", [3]),
        ]
        config, paper_type = back.paper_configs[_P1]
        assert paper_type is PaperType.MATH
        assert config.questions["Q6b"].max_marks == 6
        assert back.skipped == []

    def test_what_cannot_be_graded_is_skipped_with_its_reason(
        self, tmp_path: Path,
    ) -> None:
        """P2's page was deleted; P1 went out with no mark scheme."""
        path = _write(tmp_path, _rebuild(_blank(tmp_path), [0, 1]))
        manifest = _manifest()
        manifest.papers[_P1] = ExportedPaper(paper_type=PaperType.MATH)

        back = sheet_from_export(manifest, path)

        assert back.sheet.items == []
        assert back.skipped == [
            (_P1, "Q6", "no_mark_scheme"), (_P2, "Q6", "no_pages"),
        ]


def test_a_handed_back_practice_set_is_graded_and_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graded against the snapshot, filed under each question's own paper,
    no paper's score row touched, and the record marked graded — after which
    its answers are on offer."""
    from app_web.api import Api
    from core.settings import GraderConfig
    from core.storage import AttemptStore, ExportStore, MistakeStore
    from modules.marking import sheet

    api = Api()
    api._mistakes = MistakeStore(tmp_path / "mistakes.csv")
    api._attempts = AttemptStore(tmp_path / "attempts.csv")
    api._exports = ExportStore(tmp_path / "exports")
    api._exports.write(_manifest(), _blank(tmp_path))
    api._refresh_notes_later = lambda *_: None  # type: ignore[method-assign]
    submitted: list[object] = []
    api.submit_score = lambda *a: submitted.append(a) or {"success": True}  # type: ignore[method-assign]
    events: list[dict[str, object]] = []
    saved: list[str] = []
    asked: list[tuple[str, str]] = []

    def fake_grade(**kw: object) -> str:
        asked.append((str(kw["question_id"]), str(kw["mark_scheme"])))
        m = int(kw["max_marks"])  # type: ignore[call-overload]
        marks = ",".join(
            f'{{"code": "B1", "awarded": {"true" if i else "false"}, "reason": ""}}'
            for i in range(m)
        )
        return f'{{"question": "?", "max": {m}, "marks": [{marks}], "topic": "3.6"}}'

    monkeypatch.setattr(sheet, "grade_question", fake_grade)
    monkeypatch.setattr(GraderConfig, "try_load", lambda: GraderConfig(api_key="k"))
    monkeypatch.setattr(
        "app_web.api.start", lambda _n, work: work() or {"success": True},
    )
    monkeypatch.setattr("app_web.api.push", events.append)
    monkeypatch.setattr("app_web.api.LocalRenderer", lambda: _Renderer())
    monkeypatch.setattr(
        "app_web.api._save_to_chosen_file",
        lambda _d, name, _t: saved.append(name) or {"success": True, "path": name},
    )

    blank = _write(tmp_path, api._exports.blank_pdf(_ID), "handed.pdf")
    assert api.export_answers(_ID)["success"] is False      # not graded yet
    assert api.start_handback(_ID, blank) == {"success": True}

    announced = next(e for e in events if e["type"] == "sheet")
    assert announced["queue"] == [
        f"{_P1}:Q6a", f"{_P1}:Q6b", f"{_P2}:Q6a", f"{_P2}:Q6b",
    ]
    assert announced["max"] == {
        f"{_P1}:Q6a": 3, f"{_P1}:Q6b": 6, f"{_P2}:Q6a": 3, f"{_P2}:Q6b": 6,
    }
    assert ("Q6b", "B1 M1 A1 M1 A1 A1") in asked

    out = api.confirm_results("", overrides={f"{_P2}:Q6a": 3})

    assert out["success"] is True
    assert (out["score"], out["max_score"]) == (2 + 5 + 3 + 5, 18)
    assert submitted == []
    rows = api._attempts.load_all()
    assert {(r.paper_id, r.question_id) for r in rows} == {
        (_P1, "Q6a"), (_P1, "Q6b"), (_P2, "Q6a"), (_P2, "Q6b"),
    }
    assert {r.topic_name for r in rows} == {"Momentum"}
    assert api._exports.read(_ID).graded_at is not None
    assert api.export_answers(_ID)["success"] is True
    assert saved == [f"{_ID}-answers.pdf"]


def test_a_foreign_paper_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app_web.api import Api
    from core.settings import GraderConfig
    from core.storage import ExportStore

    api = Api()
    api._exports = ExportStore(tmp_path / "exports")
    api._exports.write(
        _manifest(export_id="20261010-090000-practice"), _blank(tmp_path),
    )
    monkeypatch.setattr(GraderConfig, "try_load", lambda: GraderConfig(api_key="k"))

    def run(_name: str, work: object) -> dict[str, object]:
        with pytest.raises(ValueError, match="不是这次导出的"):
            work()  # type: ignore[operator]
        return {"success": True}

    monkeypatch.setattr("app_web.api.start", run)
    api.start_handback(
        "20261010-090000-practice", _write(tmp_path, _blank(tmp_path)),
    )


class _Renderer:
    def render_regions(self, *_a: object, **_k: object) -> list[bytes]:
        return [b"png"]

    def render_pages(self, *_a: object, **_k: object) -> list[bytes]:
        return [b"png"]
