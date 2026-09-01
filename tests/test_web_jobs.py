"""Tests for the worker-thread job runner behind the Mark tab.

The push transport itself needs a real window, so it is verified at runtime.
What is testable here is the part that goes wrong quietly: the single-job
guard, whether the lock is released on every exit path, and whether a caller
that forgets to report completion still produces a terminal event — a page
waiting forever on a job that already died looks identical to a slow one.
"""
from __future__ import annotations

import threading

import pytest

from app_web import jobs


@pytest.fixture(autouse=True)
def captured(monkeypatch) -> list[dict]:
    """Collect pushes instead of sending them, and start from no job."""
    sent: list[dict] = []
    monkeypatch.setattr(jobs, "push", sent.append)
    monkeypatch.setattr(jobs, "_running", None)
    return sent


def _run_to_completion(name: str, work) -> None:
    done = threading.Event()

    def wrapped() -> None:
        try:
            work()
        finally:
            done.set()

    assert jobs.start(name, wrapped)["success"] is True
    assert done.wait(timeout=5), "job never ran"
    # The runner releases the lock after `work` returns, so wait for that too.
    for _ in range(500):
        if jobs.current() is None:
            return
        threading.Event().wait(0.01)
    raise AssertionError("job never released the lock")


def test_a_job_runs_and_releases(captured: list[dict]) -> None:
    _run_to_completion("批改", lambda: captured.append({"type": "work"}))
    assert jobs.current() is None
    assert captured[-1] == {"type": "finished", "job": "批改"}


def test_a_second_job_is_refused_while_one_runs() -> None:
    gate = threading.Event()
    started = threading.Event()

    def slow() -> None:
        started.set()
        gate.wait(timeout=5)

    assert jobs.start("批改", slow)["success"] is True
    assert started.wait(timeout=5)

    refused = jobs.start("解析", lambda: pytest.fail("should not have run"))
    assert refused["success"] is False
    assert "批改" in refused["error"]

    gate.set()


def test_a_failing_job_reports_and_still_releases(captured: list[dict]) -> None:
    """A crash must not leave the lock held — that would wedge the tab until
    restart, with no way for the user to tell why."""

    def boom() -> None:
        raise RuntimeError("渲染炸了")

    _run_to_completion("批改", boom)

    assert jobs.current() is None
    kinds = [e["type"] for e in captured]
    assert kinds[-2:] == ["error", "finished"]
    assert captured[-2]["message"] == "渲染炸了"


def test_every_job_ends_with_a_terminal_event(captured: list[dict]) -> None:
    """The page keys its spinner off `finished`; a path that skips it hangs."""
    _run_to_completion("解析", lambda: None)
    assert captured[-1]["type"] == "finished"
