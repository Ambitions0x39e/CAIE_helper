"""pywebview host: opens the window and exposes the Python side to JS.

The frontend is a built Vite bundle loaded off disk, so ``frontend/dist`` must
exist (``npm run build``) before this runs.

Set ``CIE_DEBUG=1`` to get devtools and the right-click menu back. Shipping
builds run with it unset — that is what keeps the window from feeling like a
browser tab.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import webview

from app_web.api import Api
from core.settings import app_settings
from modules.updater import prune_legacy_macos_app

#: Painted before the webview has anything to show. Without it the window comes
#: up white and flashes on every launch.
_BACKGROUND = "#F9F9F8"

#: Opening size, in logical pixels — the unit keeps the window the same
#: apparent size on every display instead of shrinking as density rises.
_WIDTH_DP = 1280
_HEIGHT_DP = 720

_INDEX = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"


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
    prune_legacy_macos_app()
    debug = os.environ.get("CIE_DEBUG") == "1"
    # Root stays at WARNING: pdfminer logs a line per glyph at DEBUG and would
    # bury everything the app says.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("cie_helper").setLevel(logging.DEBUG if debug else logging.INFO)
    webview.create_window(
        "CIE Helper",
        _entry(),
        js_api=Api(),
        # Logical pixels, not device ones, and they size the outer frame:
        # measured at 144 dpi, width=1100 came out 1650 px wide. So this is
        # 16:9, and on a 150% display it opens at exactly 1920x1080.
        width=_WIDTH_DP,
        height=_HEIGHT_DP,
        background_color=_BACKGROUND,
        text_select=False,  # chrome is not selectable and shows no I-beam
        zoomable=False,  # no pinch / ctrl+wheel zoom
        draggable=False,  # images and links cannot be dragged out
    )
    # `private_mode` defaults to True, which throws the webview's storage away
    # on exit — localStorage included, so anything the UI remembers between
    # launches (the command palette's usage counts, its empty-state setting)
    # would come back blank every time. The profile lives beside the rest of
    # the app's data so uninstalling clears it with everything else.
    webview.start(
        debug=debug,
        private_mode=False,
        storage_path=str(app_settings.base_dir / "webview"),
    )


if __name__ == "__main__":
    main()
