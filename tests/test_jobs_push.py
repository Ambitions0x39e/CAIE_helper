"""`push` must reach the page whether or not the window is in the foreground."""
from __future__ import annotations

import webview

from app_web import jobs


class _Window:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def evaluate_js(self, script: str) -> None:
        self.scripts.append(script)


def test_push_reaches_a_window_that_is_not_in_the_foreground(monkeypatch) -> None:
    window = _Window()
    monkeypatch.setattr(webview, "windows", [window])
    # WinForms answers None here while another application has the focus.
    monkeypatch.setattr(webview, "active_window", lambda: None)

    jobs.push({"type": "finished", "job": "练习"})

    assert len(window.scripts) == 1
    assert '"finished"' in window.scripts[0]
