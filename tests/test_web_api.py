"""Tests for the js_api surface exposed to the webview.

The layer is deliberately thin, so what is worth testing is only what the
adapter itself owns:

* ``open_external`` — the one method that takes a string from the page and
  hands it to the OS.
* the shape every method returns — JS reads ``success`` and nothing else, so a
  validation failure has to arrive looking like an operation failure rather
  than as a rejected promise.
* JSON-serializability — a Pydantic model that reaches pywebview un-dumped
  fails at the bridge, far from the method that produced it.
"""
from __future__ import annotations

import datetime
import json

import pytest
from pydantic import ValidationError

from app_web.api import Api, _invalid
from core.models import MistakeRecord
from core.storage import AttemptStore, MistakeStore
from modules.marking.grader import QuestionResult


@pytest.fixture
def api(tmp_path) -> Api:
    """Stores under tmp_path and no note rewrite: a test that confirms a run
    must not append to the real ~/.cie_helper files, nor — on a machine whose
    .env holds grader credentials — call the model from a background thread."""
    a = Api()
    a._mistakes = MistakeStore(tmp_path / "mistakes.csv")
    a._attempts = AttemptStore(tmp_path / "attempts.csv")
    a._refresh_notes_later = lambda *_: None  # type: ignore[method-assign]
    return a


def test_grading_type_reads_the_mark_scheme_file_name(api: Api) -> None:
    assert api.grading_type("/papers/9702_s25_ms_21.pdf") == "physics"
    assert api.grading_type("/papers/9702_s25_ms_11.pdf") == "mcq"
    assert api.grading_type("/uploads/scan.pdf") is None


def test_ping_round_trips(api: Api) -> None:
    assert api.ping() == "pong"


# -- open_external -----------------------------------------------------------


@pytest.mark.parametrize("url", ["http://x.test/a", "https://x.test/a"])
def test_open_external_accepts_web_urls(api: Api, url: str, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("app_web.api.webbrowser.open", opened.append)
    assert api.open_external(url) is True
    assert opened == [url]


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox",
        "",
        "not a url",
    ],
)
def test_open_external_refuses_everything_else(
    api: Api, url: str, monkeypatch,
) -> None:
    """A refused scheme must not reach the OS at all — returning False is not
    enough if webbrowser.open already ran."""
    monkeypatch.setattr(
        "app_web.api.webbrowser.open",
        lambda _: pytest.fail(f"handed {url!r} to the OS"),
    )
    assert api.open_external(url) is False


# -- the error channel -------------------------------------------------------


def test_a_bad_paper_id_comes_back_as_a_result_not_an_exception(api: Api) -> None:
    """JS reads `success`; it must not also have to catch a rejected promise."""
    out = api.download_paper("nonsense")
    assert out["success"] is False
    assert "paper_id" in out["error"]


def test_a_bad_source_comes_back_the_same_way(api: Api) -> None:
    out = api.download_paper("9231_s22_qp_41", source="nowhere")
    assert out["success"] is False
    assert out["error"]


def test_the_default_source_is_a_source_the_backend_accepts(
    api: Api, monkeypatch,
) -> None:
    """The default has to survive DownloadRequest's strict Literal.

    `DownloadSource` is spelled "CIEFrank"/"PapaCambridge"; a lower-cased
    default validates fine in isolation and then rejects every real call.
    Nothing else here would notice — the other failure tests pass a bad
    paper_id, which fails first.
    """
    seen: list[str] = []
    monkeypatch.setattr(
        api._downloader, "download",
        lambda request, **_: seen.append(request.source) or _ok(request.paper_id),
    )
    out = api.download_paper("9231_s22_qp_41")
    assert out["success"] is True, out.get("error")
    assert seen == ["CIEFrank"]


def _ok(paper_id: str):
    from modules.downloader import DownloadResult

    return DownloadResult(success=True, paper_id=paper_id)


def test_invalid_unwraps_the_validators_own_message() -> None:
    """Pydantic prefixes a custom validator's message with "Value error, ";
    the user should see the sentence the validator actually wrote."""
    from modules.downloader import DownloadRequest

    with pytest.raises(ValidationError) as caught:
        DownloadRequest(paper_id="nonsense")
    assert _invalid(caught.value)["error"].startswith("paper_id must match")


# -- serializability ---------------------------------------------------------


def test_syllabuses_are_plain_json(api: Api) -> None:
    """Anything crossing the bridge must survive json.dumps — a Pydantic model
    returned un-dumped only fails once pywebview tries to serialize it."""
    out = api.syllabuses()
    assert isinstance(out, list)
    json.dumps(out)
    assert all(isinstance(entry["syllabus_id"], str) for entry in out)


def test_query_session_reports_a_bad_season_as_a_result(api: Api) -> None:
    out = api.query_session("9231", "2022", "z")
    assert out["success"] is False
    assert "考季" in out["error"]
    json.dumps(out)


# -- settings never hand secrets back ----------------------------------------


def test_mail_settings_omits_the_password(api: Api) -> None:
    """The form field is write-only. Sending the stored password back would put
    a live app password into the page's DOM for no functional gain — the user
    re-types it to change it, and leaves it alone otherwise."""
    out = api.mail_settings()
    assert not any("password" in k.lower() for k in out)
    assert "app_password" not in json.dumps(out).lower()


def test_grader_settings_omits_the_api_key(api: Api) -> None:
    out = api.grader_settings()
    assert "api_key" not in out
    assert "key" not in json.dumps(out).lower()


# -- mistake exports pick rows by position -----------------------------------


def _stub_mistakes(api: Api, count: int) -> list[MistakeRecord]:
    """Give the adapter a known store to select out of."""
    records = [
        MistakeRecord(
            paper_id="9702_s23_qp_11",
            question_id=str(i),
            score=0.0,
            max_score=2.0,
            comment="",
            timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )
        for i in range(count)
    ]
    api._mistakes.load_all = lambda: list(records)  # type: ignore[method-assign]
    return records


def test_export_selection_is_by_position_and_stays_in_store_order(api: Api) -> None:
    """Positions, not paper+question: a re-grade repeats the same pair, so a
    key made of the two would pull both rows when the user ticked one."""
    records = _stub_mistakes(api, 4)
    assert api._chosen_mistakes([2, 0]) == [records[0], records[2]]


def test_export_selection_ignores_positions_the_store_does_not_have(api: Api) -> None:
    """The page holds its own copy of the list; a stale index must not raise
    across the bridge."""
    records = _stub_mistakes(api, 2)
    assert api._chosen_mistakes([-1, 1, 99]) == [records[1]]


def test_exporting_nothing_is_a_result_not_a_save_dialog(api: Api) -> None:
    _stub_mistakes(api, 2)
    for out in (
        api.export_mistakes_csv([]),
        api.export_mistakes_pdf([]),
        api.export_mistakes_answers([]),
    ):
        assert out["success"] is False
        assert "勾选" in out["error"]
        json.dumps(out)


# -- confirming a graded run -------------------------------------------------


def _graded_run(api: Api) -> None:
    """Three questions, all tagged 7 by the model: two lost marks, one full."""
    api._results = [
        QuestionResult(question="1", marks=[], total=0, max=2, topic="7",
                       error_type="slip"),
        QuestionResult(question="2", marks=[], total=1, max=2, topic="7",
                       error_type="concept"),
        QuestionResult(question="3", marks=[], total=2, max=2, topic="7"),
    ]
    api.submit_score = lambda *_: {"success": True}  # type: ignore[method-assign]
    api.topics_for = lambda _: {"7": "Equilibria", "8": "Kinetics"}  # type: ignore[method-assign]


def test_a_topic_picked_on_the_results_page_is_what_both_rows_are_filed_under(
    api: Api,
) -> None:
    """The student's pick wins over the model's; None means 未分类; a question
    they left alone keeps the model's tag."""
    _graded_run(api)

    out = api.confirm_results("9701_s25_qp_22", topic_overrides={"1": "8", "2": None})

    assert out["success"] is True
    assert [(r.question_id, r.topic_name) for r in api._mistakes.load_all()] == [
        ("1", "Kinetics"),
        ("2", None),
    ]
    assert [(r.question_id, r.topic_name) for r in api._attempts.load_all()] == [
        ("1", "Kinetics"),
        ("2", None),
        ("3", "Equilibria"),
    ]


def test_every_question_becomes_an_attempt_with_the_picked_error_type(
    api: Api,
) -> None:
    """Full marks included; a picked error type wins; one the page made up is
    ignored rather than failing the confirm after the score was written."""
    _graded_run(api)

    out = api.confirm_results(
        "9701_s25_qp_22", error_overrides={"1": "misread", "2": "nonsense"},
    )

    assert out["success"] is True
    assert [
        (a.question_id, a.error_type, a.model_error_type)
        for a in api._attempts.load_all()
    ] == [
        ("1", "misread", "slip"),
        ("2", "concept", "concept"),
        ("3", None, None),
    ]


def test_retagging_a_mistake_retags_its_attempts(api: Api) -> None:
    _graded_run(api)
    api.confirm_results("9701_s25_qp_22")

    api.retag_mistake("9701_s25_qp_22", "2", "8")

    assert [(a.question_id, a.topic_name) for a in api._attempts.load_all()] == [
        ("1", "Equilibria"),
        ("2", "Kinetics"),
        ("3", "Equilibria"),
    ]


def test_a_confirmed_run_rewrites_its_components_note(
    tmp_path, monkeypatch,
) -> None:
    """Off the calling thread, with the run's lost marks and their comments."""
    import threading

    from core.settings import GraderConfig

    a = Api()
    a._mistakes = MistakeStore(tmp_path / "mistakes.csv")
    a._attempts = AttemptStore(tmp_path / "attempts.csv")
    _graded_run(a)
    monkeypatch.setattr(
        "app_web.api.GraderConfig.try_load", lambda: GraderConfig(api_key="k"),
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app_web.api.refresh_notes",
        lambda config, run, comments, **kw: calls.append(
            {"run": [r.question_id for r in run], "comments": comments, **kw}
        ),
    )

    a.confirm_results("9701_s25_qp_22")
    for t in threading.enumerate():
        if t.name == "tutor-notes":
            t.join(timeout=5)

    assert len(calls) == 1
    assert calls[0]["run"] == ["1", "2", "3"]
    assert set(calls[0]["comments"]) == {"1", "2"}  # type: ignore[arg-type]
    assert calls[0]["paper_id"] == "9701_s25_qp_22"
    profile = calls[0]["profile"]
    assert (profile.subject_id, profile.component) == ("9701", "2")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "cover_id,expected",
    [
        ("9231/43/M/J/23", "9231_s23_qp_43"),
        ("9702/21/O/N/24", "9702_w24_qp_21"),
        ("9709/12/F/M/25", "9709_m25_qp_12"),
        ("9231/43", "9231/43"),
        ("", ""),
    ],
)
def test_the_analysis_is_keyed_by_the_downloaded_id(
    api: Api, monkeypatch, cover_id: str, expected: str,
) -> None:
    """The store, the syllabus topics and the tutor notes all key on
    ``9231_s23_qp_43``; a run under the cover's "9231/43/M/J/23" got no
    topics and could not be confirmed. An id that doesn't convert passes
    through as it is."""
    from modules.marking.ms_parser import PaperConfig

    monkeypatch.setattr("app_web.api.push", lambda _: None)
    monkeypatch.setattr("app_web.api.start", lambda _, work: work())
    monkeypatch.setattr(
        api, "_parse_ms",
        lambda *_: PaperConfig(paper_id=cover_id, total_marks=50, questions={}),
    )
    api.start_analysis("/uploads/scan.pdf", "math")
    assert api.analysis()["paper_id"] == expected
