"""In-app updater — check GitHub Releases, download the installer, run it.

Before this existed, shipping a new version meant telling users to go to the
GitHub releases page and install the package by hand. Now "设置 → 关于 → 更新"
does the whole round trip: ask the API what the latest release is, compare it
against our own version, and (once the user confirms) fetch the installer for
*this* platform and hand it to the OS.

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

import subprocess
import sys
import tomllib
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

    def download(self, url: str) -> UpdateDownloadResult:
        """Stream the installer into ``updates_dir``. Never raises."""
        try:
            path = self._fetch_installer(url)
        except _UpdateError as exc:
            return UpdateDownloadResult(success=False, error=str(exc))
        return UpdateDownloadResult(success=True, local_path=str(path))

    # -- install -------------------------------------------------------------

    def install(self, installer_path: Path) -> UpdateInstallResult:
        """Hand the installer to the OS, detached from this process.

        The caller MUST exit the app right after a successful return on
        Windows: Inno Setup cannot overwrite the .exe while it is running.

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

        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    [
                        str(installer_path),
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                    ],
                    creationflags=(
                        subprocess.DETACHED_PROCESS
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                    ),
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

    def _fetch_installer(self, url: str) -> Path:
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

        dest: Path = self._updates_dir / filename
        try:
            with dest.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    if chunk:
                        fh.write(chunk)
        except OSError as exc:
            raise _UpdateError(f"Cannot write {dest}: {exc}") from exc

        return dest


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
