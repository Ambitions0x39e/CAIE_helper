"""Long-running work on a worker thread, pushing progress to the page.

The Mark tab's two slow operations — parsing a mark scheme and grading a
paper — take tens of seconds and report as they go. Neither fits the js_api
request/response shape: a method that blocks that long would hang the bridge
and produce a single answer at the end, which is exactly what F3.4 forbids.

So they run on a thread and push events instead. `window.evaluate_js` is safe
to call from a worker thread on this stack — measured on pywebview 6.2.1 /
WebView2: five pushes from a worker all arrived, in order, ~1.2ms each. The
alternative (the frontend polling a status method) stays the fallback if some
backend ever proves unreliable; nothing here depends on which is used beyond
this file.

**One job at a time.** Both operations mutate the same analysis state, and the
A single in-progress flag is what guards them. The
guard lives here so every caller inherits it rather than remembering it.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import webview

_log = logging.getLogger("cie_helper.jobs")

#: The page-side receiver. Defined by the frontend before it starts a job.
_SINK = "window.__cieJobEvent"

_lock = threading.Lock()
_running: str | None = None


def push(event: dict[str, Any]) -> None:
    """Send one event to the page. Never raises into the worker.

    A push that fails must not kill the job — the work is still worth
    finishing, and the page will see the terminal event or the job's absence.
    """
    window = webview.active_window()
    if window is None:
        return
    try:
        payload = json.dumps(event, ensure_ascii=False)
        window.evaluate_js(f"{_SINK} && {_SINK}({payload})")
    except Exception:  # noqa: BLE001 — a dead page is not the job's problem
        _log.debug("push failed for %s", event.get("type"), exc_info=True)


def current() -> str | None:
    """The running job's name, or None."""
    with _lock:
        return _running


def start(name: str, work: Callable[[], None]) -> dict[str, Any]:
    """Run *work* on a worker thread, or report that one is already running.

    *work* is responsible for its own progress events; this only brackets it
    with the terminal `done`/`error` push so no caller can forget one and
    leave the page waiting forever.
    """
    global _running
    with _lock:
        if _running is not None:
            return {"success": False, "error": f"{_running} 还在进行中，请稍候"}
        _running = name

    def _run() -> None:
        global _running
        try:
            work()
        except Exception as exc:  # noqa: BLE001 — reported to the page
            _log.exception("%s failed", name)
            push({"type": "error", "job": name, "message": str(exc)})
        finally:
            with _lock:
                _running = None
            push({"type": "finished", "job": name})

    threading.Thread(target=_run, name=f"cie-{name}", daemon=True).start()
    return {"success": True}
