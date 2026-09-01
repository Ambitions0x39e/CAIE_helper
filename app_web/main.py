"""pywebview host: opens the window and exposes the Python side to JS.

The frontend is a built Vite bundle loaded off disk, so ``frontend/dist`` must
exist (``npm run build``) before this runs.

Set ``CIE_DEBUG=1`` to get devtools and the right-click menu back. Shipping
builds run with it unset — that is what keeps the window from feeling like a
browser tab.
"""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import webview

#: Painted before the webview has anything to show. Without it the window comes
#: up white and flashes on every launch.
_BACKGROUND = "#F9F9F8"

_INDEX = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"


class Api:
    """Everything JS may call, as ``window.pywebview.api.*``."""

    def ping(self) -> str:
        return "pong"

    def open_external(self, url: str) -> bool:
        """Open *url* in the user's browser. Never navigates this window.

        Only http(s) gets through: ``file:`` would hand the page a way to launch
        local content, and ``javascript:`` a way to run in whatever the browser
        opens it with.
        """
        if urlparse(url).scheme not in ("http", "https"):
            return False
        webbrowser.open(url)
        return True


#: Where `npm run dev` serves from. Pointed at with CIE_DEV=1 so edits reload
#: in the real window instead of needing a rebuild between every change.
_DEV_URL = "http://localhost:5173"


def _entry() -> str:
    if os.environ.get("CIE_DEV") == "1":
        return _DEV_URL
    if not _INDEX.is_file():
        raise SystemExit(f"前端产物不存在：{_INDEX}\n先在 frontend/ 里跑 npm run build")
    return str(_INDEX)


def main() -> None:
    debug = os.environ.get("CIE_DEBUG") == "1"
    webview.create_window(
        "CIE Helper",
        _entry(),
        js_api=Api(),
        width=1100,
        height=760,
        background_color=_BACKGROUND,
        text_select=False,  # chrome is not selectable and shows no I-beam
        zoomable=False,  # no pinch / ctrl+wheel zoom
        draggable=False,  # images and links cannot be dragged out
    )
    webview.start(debug=debug)


if __name__ == "__main__":
    main()
