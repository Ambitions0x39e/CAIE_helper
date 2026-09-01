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

import json

import pytest
from pydantic import ValidationError

from app_web.api import Api, _invalid


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
