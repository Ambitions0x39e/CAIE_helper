"""Tests for the js_api surface exposed to the webview.

Only ``open_external`` has anything to get wrong: it is the one method that
takes a string from the page and hands it to the OS.
"""
from __future__ import annotations

import pytest

from app_web.main import Api


def test_ping_round_trips():
    assert Api().ping() == "pong"


@pytest.mark.parametrize("url", ["http://x.test/a", "https://x.test/a"])
def test_open_external_accepts_web_urls(url, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("app_web.main.webbrowser.open", opened.append)
    assert Api().open_external(url) is True
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
def test_open_external_refuses_everything_else(url, monkeypatch):
    """A refused scheme must not reach the OS at all — returning False is not
    enough if webbrowser.open already ran."""
    monkeypatch.setattr(
        "app_web.main.webbrowser.open",
        lambda _: pytest.fail(f"handed {url!r} to the OS"),
    )
    assert Api().open_external(url) is False
