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


@pytest.fixture
def api() -> Api:
    return Api()


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
