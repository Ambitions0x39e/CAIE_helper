"""pywebview host: opens the window and exposes the Python side to JS.

The frontend is a built Vite bundle loaded off disk, so ``frontend/dist`` must
exist (``pnpm build``) before this runs.

Set ``CIE_DEBUG=1`` to get devtools and the right-click menu back. Shipping
builds run with it unset — that is what keeps the window from feeling like a
browser tab.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

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


#: Where `pnpm dev` serves from. Pointed at with CIE_DEV=1 so edits reload
#: in the real window instead of needing a rebuild between every change.
_DEV_URL = "http://localhost:5173"


def _entry() -> str:
    if os.environ.get("CIE_DEV") == "1":
        return _DEV_URL
    if not _INDEX.is_file():
        raise SystemExit(f"前端产物不存在：{_INDEX}\n先在 frontend/ 里跑 pnpm build")
    return str(_INDEX)


if sys.platform == "darwin":
    import AppKit  # type: ignore[import-untyped]
    import WebKit  # type: ignore[import-untyped]
    from PyObjCTools import AppHelper  # type: ignore[import-untyped]
    from webview.platforms.cocoa import BrowserView

    class _TitlebarGrip(AppKit.NSView):  # type: ignore[misc]
        def mouseDown_(self, event: AppKit.NSEvent) -> None:
            window = self.window()
            if event.clickCount() != 2:
                window.performWindowDragWithEvent_(event)
                return
            # Double-click does what System Settings › Desktop & Dock says.
            action = AppKit.NSUserDefaults.standardUserDefaults().stringForKey_(
                "AppleActionOnDoubleClick"
            )
            if action == "Minimize":
                window.performMiniaturize_(None)
            elif action != "None":
                window.performZoom_(None)


def _titlebar(ns: Any) -> tuple[Any, float]:
    """The title bar container and the height AppKit reserves for it."""
    close = ns.standardWindowButton_(AppKit.NSWindowCloseButton)
    container = close.superview().superview()
    return container, ns.frame().size.height - ns.contentLayoutRect().size.height


def _inset_titlebar(window: webview.Window) -> None:
    """A full-height sidebar under a compact unified toolbar: title hidden,
    traffic lights inset in the toolbar row, the page running beneath. The page
    learns the toolbar height as `--titlebar`, taken from `contentLayoutRect`
    the way the HIG asks full-size content to be laid out, and injected before
    the first paint."""
    ns: Any = window.native
    ns.setStyleMask_(ns.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
    ns.setTitlebarAppearsTransparent_(True)
    ns.setTitleVisibility_(AppKit.NSWindowTitleHidden)
    toolbar = AppKit.NSToolbar.alloc().initWithIdentifier_("main")
    toolbar.setShowsBaselineSeparator_(False)
    ns.setToolbar_(toolbar)
    # The plain unified style reserves 66 pt above the page, compact 40.
    ns.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnifiedCompact)
    container, height = _titlebar(ns)
    # pywebview paints the container opaque; the page shows through only once
    # that is cleared.
    container.setBackgroundColor_(AppKit.NSColor.clearColor())
    script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        f"document.documentElement.style.setProperty('--titlebar', '{height}px')",
        WebKit.WKUserScriptInjectionTimeAtDocumentStart,
        True,
    )
    webkit = BrowserView.instances[window.uid].webview
    webkit.configuration().userContentController().addUserScript_(script)


def _add_titlebar_grip(window: webview.Window) -> None:
    """A transparent title bar passes clicks through to the webview, so nothing
    would move the window. This view sits between the page and the traffic
    lights and hands the strip back to AppKit. It goes in once the webview has
    become the content view — pywebview swaps it in when the first load
    finishes, above anything added earlier. pywebview's JS drag region was
    tried instead and overshoots: a 100 px drag moved the window 1050 px."""

    def add() -> None:
        ns: Any = window.native
        container, height = _titlebar(ns)
        frame = container.superview()
        width, full = frame.bounds().size
        rect = ((0, full - height), (width, height))
        grip = _TitlebarGrip.alloc().initWithFrame_(rect)
        grip.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        frame.addSubview_positioned_relativeTo_(grip, AppKit.NSWindowBelow, container)

    AppHelper.callAfter(add)


def _center_traffic_lights(window: webview.Window) -> None:
    """Centre the three window buttons over the nav column. AppKit lays the
    title bar out again whenever the window resizes, which puts them back at
    the left edge, so the shift is re-applied after every resize."""
    nav = window.evaluate_js("document.querySelector('nav').clientWidth")
    ns: Any = window.native
    kinds = (AppKit.NSWindowCloseButton, AppKit.NSWindowMiniaturizeButton,
             AppKit.NSWindowZoomButton)

    def place(_note: Any = None) -> None:
        buttons = [ns.standardWindowButton_(k) for k in kinds]
        left = buttons[0].frame().origin.x
        span = AppKit.NSMaxX(buttons[-1].frame()) - left
        shift = (nav - span) / 2 - left
        for b in buttons:
            x, y = b.frame().origin
            b.setFrameOrigin_((x + shift, y))

    def install() -> None:
        place()
        AppKit.NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            AppKit.NSWindowDidResizeNotification, ns, None, place
        )

    AppHelper.callAfter(install)


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
    window = webview.create_window(
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
    if sys.platform == "darwin" and window is not None:
        # before_show fires on the main thread, before the page starts loading.
        window.events.before_show += _inset_titlebar
        window.events.loaded += _add_titlebar_grip
        window.events.loaded += _center_traffic_lights
    # `private_mode` defaults to True, which throws the webview's storage away
    # on exit — localStorage included, so anything the UI remembers between
    # launches (the command palette's usage counts, its empty-state setting)
    # would come back blank every time. The profile lives beside the rest of
    # the app's data so uninstalling clears it with everything else.
    storage = app_settings.base_dir / "webview"
    # The HTTP cache inside it has to go, though. pywebview's asset route sets
    # no-cache, but `bottle.static_file` returns a response of its own and those
    # headers never reach the wire — the bundle is served with Last-Modified
    # alone, and WebView2 answers index.html from disk. Every build shares this
    # profile and the same 127.0.0.1 origin, so a fresh build (run from source,
    # or installed by an update) came up showing the previous build's UI.
    # Nothing in that cache is worth keeping for files read off local disk.
    shutil.rmtree(storage / "EBWebView" / "Default" / "Cache", ignore_errors=True)
    webview.start(
        debug=debug,
        private_mode=False,
        storage_path=str(storage),
    )


if __name__ == "__main__":
    main()
