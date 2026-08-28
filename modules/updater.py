"""In-app updater — check GitHub Releases, download the installer, run it.

"设置 → 关于 → 更新" does the whole round trip: ask the API what the latest
release is, compare it against our own version, and (once the user confirms)
fetch the installer for *this* platform and hand it to the OS.

Same shape as ``modules.downloader``: every public method returns a Pydantic
result object with ``success`` / ``error``, and the internal ``_UpdateError``
never escapes this module. A failed check is a *result*, not an exception —
the caller shows a message and carries on.

Deliberately conservative on two fronts, because getting either wrong breaks
a working install rather than merely failing to update it:

* **Never install a package built for another platform.** ``check()`` only ever
  returns an asset whose suffix matches ``sys.platform``, and ``install()``
  re-validates the suffix before spawning anything.
* **Strictly-greater-than only.** Equal or older upstream versions (and any
  version string we cannot parse) are "no update available", never a
  downgrade attempt.
"""
from __future__ import annotations

import contextlib
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import requests
from pydantic import BaseModel

from core.settings import app_settings

_REPO: Final[str] = "Ambitions0x39e/CAIE_helper"
_LATEST_RELEASE_API: Final[str] = (
    f"https://api.github.com/repos/{_REPO}/releases/latest"
)
#: Public — the UI opens this in a browser on platforms we cannot install for.
RELEASES_PAGE_URL: Final[str] = (
    f"https://github.com/{_REPO}/releases/latest"
)

_API_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/vnd.github+json",
}

# Same value as downloader._REQUEST_TIMEOUT: 10s to connect, 30s between
# chunks. The connect budget is what the brief asks for; the read budget has
# to be generous because these installers are 50–100 MB.
_REQUEST_TIMEOUT: Final[tuple[int, int]] = (10, 30)
_CHUNK_SIZE: Final[int] = 8192

# Progress callbacks are throttled to this interval. At 8 KB a chunk a 56 MB
# installer is ~7000 chunks; reporting every chunk would mean thousands of
# page.update() calls and make the UI, not the network, the bottleneck.
_PROGRESS_MIN_INTERVAL_S: Final[float] = 0.3

# GitHub's release page labels sizes in MB but computes them in MiB (it shows
# our 56,356,909-byte installer as "53.7 MB"). Match that so the number the
# user watched on the release page is the number the app counts up to.
_MIB: Final[float] = 1024.0 * 1024.0

_INNO_SILENT_ARGS: Final[tuple[str, ...]] = (
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
)

#: Which release asset belongs to which platform. A platform absent from this
#: map has no installer we know how to run — the UI sends those users to the
#: releases page instead.
_ASSET_SUFFIX: Final[dict[str, str]] = {
    "win32": ".exe",
    "darwin": ".pkg",
}

_UNSUPPORTED_PLATFORM: Final[str] = "platform not supported"


def platform_asset_suffix() -> str | None:
    """The installer extension for the running platform, or None if we can't."""
    return _ASSET_SUFFIX.get(sys.platform)


def current_app_version() -> str:
    """Our own version, read from pyproject.toml (same source as the About page).

    ``flet build`` copies the whole working directory into the bundle, so
    pyproject.toml sits next to the package in a packaged app too. Returns ""
    when it cannot be read — ``check()`` turns that into a plain error.
    """
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return ""


def _parse_version(raw: str) -> tuple[int, int, int] | None:
    """``"v1.2.3"`` → ``(1, 2, 3)``. None for anything not exactly 3 numbers.

    Returning None rather than raising is the point: a release tagged
    ``"nightly"`` must degrade to "no update", never to a traceback.
    """
    text = raw.strip().removeprefix("v").removeprefix("V")
    parts = text.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    major, minor, patch = (int(p) for p in parts)
    return (major, minor, patch)


# ---------------------------------------------------------------------------
# Result schemas
# ---------------------------------------------------------------------------


class UpdateCheckResult(BaseModel):
    """Outcome of asking GitHub what the latest release is."""

    model_config = {"strict": False}

    success: bool
    error: str | None = None
    update_available: bool = False
    latest_version: str | None = None
    release_notes: str | None = None
    download_url: str | None = None


class UpdateDownloadResult(BaseModel):
    """Outcome of fetching the installer to disk."""

    model_config = {"strict": False}

    success: bool
    error: str | None = None
    local_path: str | None = None


class DownloadProgress(BaseModel):
    """How far the installer download has got, and how fast it is going.

    ``total`` is None when the server sends no usable Content-Length — the
    download still works, there is just nothing to count towards.
    """

    model_config = {"strict": False}

    downloaded: int
    total: int | None = None
    speed_bps: float = 0.0


#: What a caller passes to ``download`` to watch progress. It must not raise;
#: ``download`` ignores exceptions from it rather than abandoning the download.
ProgressCallback = Callable[[DownloadProgress], None]


def format_progress(progress: DownloadProgress) -> str:
    """``'12.3 / 53.7 MB (23%) · 2.4 MB/s'`` — for display next to a label."""
    done = progress.downloaded / _MIB
    if progress.total:
        percent = round(progress.downloaded / progress.total * 100)
        head = f"{done:.1f} / {progress.total / _MIB:.1f} MB ({percent}%)"
    else:
        head = f"{done:.1f} MB"
    if progress.speed_bps <= 0:
        return head
    return f"{head} · {progress.speed_bps / _MIB:.1f} MB/s"


class UpdateInstallResult(BaseModel):
    """Outcome of handing the installer to the OS.

    ``success`` means the installer process was *spawned*, not that the
    install finished — by design, since the app has to exit for the installer
    to overwrite it.
    """

    model_config = {"strict": False}

    success: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Updater
# ---------------------------------------------------------------------------


class AppUpdater:
    """Checks for, downloads and launches app updates."""

    def __init__(self, current_version: str | None = None) -> None:
        self._current_version = (
            current_version if current_version is not None
            else current_app_version()
        )
        self._updates_dir: Path = app_settings.updates_dir

    # -- check ---------------------------------------------------------------

    def check(self) -> UpdateCheckResult:
        """Ask GitHub for the latest release and compare it with ours.

        Never raises. ``update_available`` is True only when the upstream
        version parses cleanly, is strictly greater than ours, *and* ships an
        asset for this platform.
        """
        suffix = platform_asset_suffix()
        if suffix is None:
            return UpdateCheckResult(
                success=False, error=_UNSUPPORTED_PLATFORM,
            )

        current = _parse_version(self._current_version)
        if current is None:
            return UpdateCheckResult(
                success=False,
                error=f"Cannot read local version: {self._current_version!r}",
            )

        try:
            payload = self._fetch_latest_release()
        except _UpdateError as exc:
            return UpdateCheckResult(success=False, error=str(exc))

        raw_tag = payload.get("tag_name")
        tag = raw_tag if isinstance(raw_tag, str) else ""
        latest = _parse_version(tag)
        if latest is None:
            return UpdateCheckResult(
                success=False,
                error=f"Unrecognised release tag: {tag!r}",
            )

        raw_notes = payload.get("body")
        notes = raw_notes.strip() if isinstance(raw_notes, str) else ""
        latest_version = ".".join(str(n) for n in latest)

        # Strictly greater, or there is nothing to do. Equal is "up to date";
        # older upstream (a yanked release, a hand-edited tag) must never
        # trigger a downgrade.
        is_newer = latest > current
        if not is_newer:
            return UpdateCheckResult(
                success=True,
                update_available=False,
                latest_version=latest_version,
                release_notes=notes,
            )

        url = _pick_asset_url(payload.get("assets"), suffix)
        if url is None:
            return UpdateCheckResult(
                success=False,
                error=_UNSUPPORTED_PLATFORM,
                latest_version=latest_version,
                release_notes=notes,
            )

        return UpdateCheckResult(
            success=True,
            update_available=True,
            latest_version=latest_version,
            release_notes=notes,
            download_url=url,
        )

    # -- download ------------------------------------------------------------

    def download(
        self, url: str, on_progress: ProgressCallback | None = None,
    ) -> UpdateDownloadResult:
        """Stream the installer into ``updates_dir``. Never raises.

        ``on_progress`` is called at most every 0.3 s with bytes-so-far, the
        total when known, and the speed over that window, plus once more when
        the download finishes. Exceptions from it are swallowed: a broken
        progress readout must not abandon a download that is working.
        """
        try:
            path = self._fetch_installer(url, on_progress)
        except _UpdateError as exc:
            return UpdateDownloadResult(success=False, error=str(exc))
        return UpdateDownloadResult(success=True, local_path=str(path))

    # -- install -------------------------------------------------------------

    def install(
        self, installer_path: Path, relaunch_exe: Path | None = None,
    ) -> UpdateInstallResult:
        """Hand the installer to the OS, detached from this process.

        The caller MUST exit the app right after a successful return on
        Windows: Inno Setup cannot overwrite the .exe while it is running.

        Which is also why reopening it afterwards cannot be done here — by then
        this process is gone. On Windows we instead spawn a detached ``cmd``
        running a generated .cmd that waits for the installer to finish and
        *then* starts the app, so the new instance begins life after Setup has
        exited. ``relaunch_exe`` defaults to this process's own .exe; pass it
        explicitly to test, or pass nothing when running from source (there is
        no app to reopen, and the install still happens).

        macOS gets ``open`` rather than the ``installer`` CLI on purpose —
        installing into /Applications needs an admin password, and
        ``installer`` would either hang or fail outright without a terminal to
        prompt in. A visible Installer.app window is the honest behaviour.
        """
        suffix = platform_asset_suffix()
        if suffix is None:
            return UpdateInstallResult(
                success=False, error=_UNSUPPORTED_PLATFORM,
            )

        # Last line of defence against running a package built for another
        # platform — a .pkg passed to Windows would at best do nothing.
        if installer_path.suffix.lower() != suffix:
            return UpdateInstallResult(
                success=False,
                error=(
                    f"Installer {installer_path.name!r} does not match "
                    f"platform {sys.platform!r} (expected {suffix})"
                ),
            )

        if not installer_path.exists():
            return UpdateInstallResult(
                success=False,
                error=f"Installer not found: {installer_path}",
            )

        app_exe = relaunch_exe if relaunch_exe is not None else (
            current_executable()
        )

        try:
            if sys.platform == "win32":
                # CREATE_NO_WINDOW, not DETACHED_PROCESS. Both survive this
                # process exiting, but DETACHED_PROCESS leaves the child with no
                # console at all, and every attempt to start the app from a
                # console-less parent produced a process that died immediately
                # (or never appeared); every attempt from a parent with a
                # console worked. CREATE_NO_WINDOW gives cmd its own console and
                # simply never shows it, so nothing flashes on screen.
                detached = (
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                )
                script = (
                    None if app_exe is None
                    else self._write_relaunch_script(installer_path, app_exe)
                )
                if script is None:
                    # Nothing to reopen, or the script could not be written:
                    # install anyway. Losing the reopen is a much smaller
                    # failure than refusing to update.
                    subprocess.Popen(
                        [str(installer_path), *_INNO_SILENT_ARGS],
                        creationflags=detached,
                    )
                else:
                    subprocess.Popen(
                        ["cmd", "/c", str(script)],
                        creationflags=detached,
                    )
            else:
                subprocess.Popen(["open", str(installer_path)])
        except OSError as exc:
            return UpdateInstallResult(
                success=False, error=f"Could not start installer: {exc}",
            )

        return UpdateInstallResult(success=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_relaunch_script(
        self, installer_path: Path, app_exe: Path,
    ) -> Path | None:
        """Write the installer-then-relaunch .cmd. None if it cannot be written.

        Encoded in the system codepage, not ASCII or UTF-8: cmd.exe reads batch
        files in the local codepage, and these paths run through the user's
        profile name, which is not necessarily ASCII on a Chinese Windows.
        """
        script = self._updates_dir / "relaunch.cmd"
        try:
            # install() can be called without download() having run in this
            # process (a resumed session, a hand-placed installer), so the
            # directory is not guaranteed to exist yet.
            self._updates_dir.mkdir(parents=True, exist_ok=True)
            script.write_text(
                _windows_relaunch_script(
                    installer_path, app_exe, self._updates_dir / "relaunch.log",
                ),
                encoding="mbcs",
                # newline="" or text mode translates our explicit \r\n again and
                # every line ends \r\r\n. cmd tolerates that on some lines but a
                # quoted path followed by a stray CR is not the path we meant.
                newline="",
            )
        except (OSError, UnicodeError):
            return None
        return script

    def _fetch_latest_release(self) -> dict[str, Any]:
        """GET the latest-release JSON. Raises _UpdateError on any failure."""
        try:
            response = requests.get(
                _LATEST_RELEASE_API,
                timeout=_REQUEST_TIMEOUT,
                headers=_API_HEADERS,
            )
        except requests.RequestException as exc:
            raise _UpdateError(f"Network error contacting GitHub: {exc}") from exc

        if not response.ok:
            raise _UpdateError(
                f"HTTP {response.status_code} from the GitHub releases API"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise _UpdateError(f"Malformed JSON from GitHub: {exc}") from exc

        if not isinstance(payload, dict):
            raise _UpdateError("Unexpected release payload from GitHub")
        return payload

    def _fetch_installer(
        self, url: str, on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Stream-download the installer. Raises _UpdateError on failure."""
        # Take only the basename, and only from the URL we chose ourselves —
        # never let a remote string decide where on disk we write.
        filename = Path(url.split("?")[0].rsplit("/", 1)[-1]).name
        if not filename:
            filename = f"cie-helper-setup{platform_asset_suffix() or ''}"

        try:
            self._updates_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _UpdateError(
                f"Cannot create {self._updates_dir}: {exc}"
            ) from exc

        try:
            response = requests.get(url, stream=True, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise _UpdateError(f"Network error downloading {url!r}: {exc}") from exc

        if not response.ok:
            raise _UpdateError(
                f"HTTP {response.status_code} when downloading {url!r}"
            )

        total = _content_length(response)
        report = _guard_callback(on_progress)

        dest: Path = self._updates_dir / filename
        downloaded = 0
        started_at = time.monotonic()
        window_at = started_at
        window_bytes = 0
        try:
            with dest.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    window = now - window_at
                    if window < _PROGRESS_MIN_INTERVAL_S:
                        continue
                    # Speed over this window, not since the start — the user
                    # asked what it is doing now, not what it averaged.
                    report(DownloadProgress(
                        downloaded=downloaded,
                        total=total,
                        speed_bps=(downloaded - window_bytes) / window,
                    ))
                    window_at, window_bytes = now, downloaded
        except OSError as exc:
            raise _UpdateError(f"Cannot write {dest}: {exc}") from exc

        # However the throttle happened to fall, always land on a final report
        # so the readout cannot freeze at something like 98% for a fast tail.
        # Average speed for this one; and total stays None if we never knew it
        # rather than being back-filled from downloaded, which would show a
        # confident "100%" we were never in a position to claim.
        elapsed = time.monotonic() - started_at
        report(DownloadProgress(
            downloaded=downloaded,
            total=total,
            speed_bps=downloaded / elapsed if elapsed > 0 else 0.0,
        ))

        return dest


def current_executable() -> Path | None:
    """The running process's own .exe, or None if that isn't a packaged app.

    In the packaged Windows app this is ``<install dir>\\cie-helper.exe`` — both
    the file the installer replaces and the thing to reopen afterwards. Asking
    Windows for the module filename beats ``sys.executable``, which an embedded
    interpreter is free to leave empty or point elsewhere.

    Returns None when running from source, where the answer would be python.exe
    and relaunching it would be nonsense.
    """
    exe: Path | None = None
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetModuleFileNameW(
            None, buffer, len(buffer),
        ):
            exe = Path(buffer.value)
    if exe is None and sys.executable:
        exe = Path(sys.executable)
    if exe is None or exe.stem.lower() in {"python", "pythonw"}:
        return None
    return exe


def _windows_relaunch_script(installer: Path, app_exe: Path, log: Path) -> str:
    """A .cmd that runs the installer to completion, then reopens the app.

    Written to a file rather than passed as a cmd command line on purpose: the
    paths contain spaces ("CIE Helper", "Your Company") and chaining with && on
    a generated command line is where the quoting bugs live. A file we author
    ourselves has exactly the quoting we put in it, and a test can read it back.

    The sequencing is the whole point. Launching the app from the installer's
    own [Run] section starts it *inside* Setup's lifetime, and it did not
    survive Setup tearing down. Here cmd waits for the installer to exit first.

    The app is invoked directly rather than via ``start``, which launched
    nothing at all here and left no trace.

    Redirections are written *before* the echo, not after it. ``echo x=%VAR%>f``
    is a trap: once %VAR% expands to a number, cmd reads the digit immediately
    left of ``>`` as a file handle and treats it as a stdin redirect, so the
    text never reaches the file. That silently produced a 0-byte log.

    The log is the only evidence a user could ever give us about a silent update
    that went wrong, so it is worth the one file.
    """
    return (
        "@echo off\r\n"
        f'>"{log}" echo starting installer\r\n'
        f'"{installer}" {" ".join(_INNO_SILENT_ARGS)}\r\n'
        f'>>"{log}" echo installer exit=%ERRORLEVEL%\r\n'
        # Let the install settle before starting the app. Launched immediately
        # after Setup finished replacing ~225 MB of files, the app started and
        # exited 0 straight away; launched by hand a minute later, or via cmd,
        # or with a freshly deleted extraction dir, it ran fine every time — so
        # the difference was how soon after the install it began.
        #
        # Not `timeout`: it aborts with "input redirection is not supported"
        # whenever stdin is not a real console, which is exactly the situation
        # this script runs in. Not `ping` either (the first fix tried here):
        # some locked-down Windows images block ICMP outright, including to
        # 127.0.0.1, and a blocked ping fails immediately instead of waiting —
        # silently turning the delay into zero seconds. `Start-Sleep` depends
        # on neither a console nor the network stack.
        'powershell -NoProfile -NonInteractive'
        ' -Command "Start-Sleep -Seconds 5"\r\n'
        # Launch regardless of the installer's exit code: if the update failed
        # the previous version is still installed, and leaving the user with no
        # app at all is the worst outcome available.
        f'>>"{log}" echo launching app\r\n'
        f'"{app_exe}"\r\n'
        f'>>"{log}" echo app exit=%ERRORLEVEL%\r\n'
    )


def _content_length(response: Any) -> int | None:
    """Content-Length as a positive int, or None if absent/unusable."""
    raw = response.headers.get("Content-Length")
    try:
        total = int(raw)
    except (TypeError, ValueError):
        return None
    return total if total > 0 else None


def _guard_callback(
    on_progress: ProgressCallback | None,
) -> ProgressCallback:
    """Wrap a progress callback so it can never break the download.

    Returns a no-op when there is no callback, so the download loop has no
    None-check in it.
    """
    if on_progress is None:
        return lambda _progress: None

    def report(progress: DownloadProgress) -> None:
        # Deliberately broad: this is a UI notification, and a display bug is
        # not a reason to throw away a 56 MB download that is going fine.
        with contextlib.suppress(Exception):
            on_progress(progress)

    return report


def _pick_asset_url(assets: object, suffix: str) -> str | None:
    """First ``browser_download_url`` whose filename ends with ``suffix``."""
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str):
            continue
        name = asset.get("name")
        candidate = name if isinstance(name, str) else url
        if candidate.lower().endswith(suffix):
            return url
    return None


# ---------------------------------------------------------------------------
# Internal exception
# ---------------------------------------------------------------------------


class _UpdateError(Exception):
    """Raised internally when a check or download fails. Never leaks out."""
