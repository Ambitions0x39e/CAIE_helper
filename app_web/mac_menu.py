"""The macOS menu bar.

Built here rather than through pywebview's `Menu`: its items take no key
equivalent, and ⌘, / ⌘1–4 are most of what a menu bar is for. pywebview only
rebuilds the bar when a window carries a `menu` of its own, so the one set here
stays.

Page destinations are command ids from `frontend/src/lib/commands.ts`, the
registry the command palette reads, handed to `window.__cieMenu`.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import AppKit  # type: ignore[import-untyped]
import webview
from PyObjCTools import AppHelper  # type: ignore[import-untyped]

from core.settings import app_settings
from modules.updater import REPO_URL

_CMD = AppKit.NSEventModifierFlagCommand
_OPT = AppKit.NSEventModifierFlagOption
_SHIFT = AppKit.NSEventModifierFlagShift
_CTRL = AppKit.NSEventModifierFlagControl

#: (title, action, key, modifiers). An action ending in `:` is a selector, sent
#: to `_Target` when it has one by that name and down the responder chain
#: otherwise; anything else is called. None is a separator.
_Item = tuple[str, "str | Callable[[], None]", str, int] | None


_actions: list[Callable[[], None]] = []


class _Target(AppKit.NSObject):  # type: ignore[misc]
    def run_(self, sender: Any) -> None:
        # Off the main thread: `evaluate_js` waits on the main thread to run
        # the script, so calling it from a menu action would deadlock.
        threading.Thread(target=_actions[sender.tag()], daemon=True).start()

    # Not `toggleFullScreen:` itself: macOS hides an item carrying that action
    # and puts its own 🌐F one in its place, so ⌃⌘F would never show.
    def fullScreen_(self, sender: Any) -> None:
        window = AppKit.NSApp.mainWindow()
        if window is not None:
            window.toggleFullScreen_(sender)

    def validateMenuItem_(self, item: Any) -> bool:
        if item.action() != "fullScreen:":
            return True
        window = AppKit.NSApp.mainWindow()
        if window is None:
            return False
        full = window.styleMask() & AppKit.NSWindowStyleMaskFullScreen
        item.setTitle_("退出全屏幕" if full else "进入全屏幕")
        return True


_target = _Target.alloc().init()


def _page(window: webview.Window, command: str) -> Callable[[], None]:
    arg = json.dumps(command)
    return lambda: window.evaluate_js(f"window.__cieMenu && window.__cieMenu({arg})")


def _open(url: Any) -> None:
    AppKit.NSWorkspace.sharedWorkspace().openURL_(url)


def _reveal(folder: Path) -> Callable[[], None]:
    def reveal() -> None:
        folder.mkdir(parents=True, exist_ok=True)
        _open(AppKit.NSURL.fileURLWithPath_(str(folder)))

    return reveal


def _browse(url: str) -> Callable[[], None]:
    return lambda: _open(AppKit.NSURL.URLWithString_(url))


def _attach(parent: Any, menu: Any, at: int | None = None) -> None:
    item = AppKit.NSMenuItem.alloc().init()
    item.setTitle_(menu.title())
    item.setSubmenu_(menu)
    parent.insertItem_atIndex_(item, parent.numberOfItems() if at is None else at)


def _menu(title: str, items: list[_Item]) -> Any:
    menu = AppKit.NSMenu.alloc().initWithTitle_(title)
    for item in items:
        if item is None:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        name, action, key, mods = item
        if isinstance(action, str):
            entry = menu.addItemWithTitle_action_keyEquivalent_(name, action, key)
            if _target.respondsToSelector_(action):
                entry.setTarget_(_target)
        else:
            entry = menu.addItemWithTitle_action_keyEquivalent_(name, "run:", key)
            entry.setTarget_(_target)
            entry.setTag_(len(_actions))
            _actions.append(action)
        entry.setKeyEquivalentModifierMask_(mods)
    return menu


def _app_menu(window: webview.Window) -> Any:
    page = partial(_page, window)
    menu = _menu("CIE Helper", [
        ("关于 CIE Helper", page("st.about"), "", 0),
        ("检查更新…", page("st.update"), "", 0),
        None,
        ("设置…", page("tab.settings"), ",", _CMD),
        None,
        None,
        ("隐藏 CIE Helper", "hide:", "h", _CMD),
        ("隐藏其他", "hideOtherApplications:", "h", _CMD | _OPT),
        ("全部显示", "unhideAllApplications:", "", 0),
        None,
        ("退出 CIE Helper", "terminate:", "q", _CMD),
    ])
    services = AppKit.NSMenu.alloc().initWithTitle_("服务")
    _attach(menu, services, at=5)
    AppKit.NSApp.setServicesMenu_(services)
    return menu


def install(window: webview.Window) -> None:
    """Replace pywebview's menu bar. Called once the page has loaded."""
    page = partial(_page, window)
    window_menu = _menu("窗口", [
        ("最小化", "performMiniaturize:", "m", _CMD),
        ("缩放", "performZoom:", "", 0),
        None,
        ("前置全部窗口", "arrangeInFront:", "", 0),
    ])
    help_menu = _menu("帮助", [
        ("CIE Helper 主页", _browse(REPO_URL), "", 0),
        ("版本说明", _browse(f"{REPO_URL}/releases"), "", 0),
        ("报告问题", _browse(f"{REPO_URL}/issues"), "", 0),
    ])

    def build() -> None:
        bar = AppKit.NSMenu.alloc().init()
        for menu in (
            _app_menu(window),
            _menu("文件", [
                ("打开 PDF 文件夹", _reveal(app_settings.pdfs_dir), "", 0),
                ("打开导出文件夹", _reveal(app_settings.exports_dir), "", 0),
            ]),
            _menu("编辑", [
                ("撤销", "undo:", "z", _CMD),
                ("重做", "redo:", "z", _CMD | _SHIFT),
                None,
                ("剪切", "cut:", "x", _CMD),
                ("拷贝", "copy:", "c", _CMD),
                ("粘贴", "paste:", "v", _CMD),
                ("全选", "selectAll:", "a", _CMD),
            ]),
            _menu("显示", [
                ("命令面板", page("palette"), "k", _CMD),
                None,
                ("进入全屏幕", "fullScreen:", "f", _CMD | _CTRL),
            ]),
            _menu("前往", [
                ("下载", page("tab.download"), "1", _CMD),
                ("管理", page("tab.manage"), "2", _CMD),
                ("练习", page("tab.practice"), "3", _CMD),
                ("批改", page("tab.mark"), "4", _CMD),
            ]),
            window_menu,
            help_menu,
        ):
            _attach(bar, menu)
        AppKit.NSApp.setMainMenu_(bar)
        AppKit.NSApp.setWindowsMenu_(window_menu)
        AppKit.NSApp.setHelpMenu_(help_menu)

    AppHelper.callAfter(build)
