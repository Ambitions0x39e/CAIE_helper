"""Tests for modules.updater — the in-app update check / download / install.

Every test fakes the network with monkeypatch: nothing here may touch
api.github.com, and nothing here may actually spawn an installer.

The version comparison is the dangerous part of this module. Getting it
backwards raises nothing and logs nothing — it just silently offers
downgrades, or silently never offers anything. Hence the deliberately
symmetrical newer / equal / older trio below.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import requests

from modules import updater as updater_mod
from modules.updater import (
    RELEASES_PAGE_URL,
    AppUpdater,
    UpdateCheckResult,
    UpdateDownloadResult,
    UpdateInstallResult,
    _parse_version,
    current_app_version,
    platform_asset_suffix,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stands in for requests.Response for both the API and the download."""

    def __init__(
        self,
        *,
        payload: object = None,
        ok: bool = True,
        status_code: int = 200,
        chunks: list[bytes] | None = None,
        raise_on_json: bool = False,
    ) -> None:
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self._chunks = chunks if chunks is not None else [b"installer-bytes"]
        self._raise_on_json = raise_on_json

    def json(self) -> object:
        if self._raise_on_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload

    def iter_content(self, chunk_size: int = 1) -> list[bytes]:
        return self._chunks


def _release(
    tag: str = "v9.9.9",
    *,
    body: str = "Bug fixes.",
    assets: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """A minimal copy of the real GitHub latest-release payload shape.

    Field names and the asset naming convention were verified against the
    live API on 2026-07-28 (which then served v1.0.0 with
    cie-helper-1.0.0-setup.exe / .pkg).
    """
    if assets is None:
        assets = [
            {
                "name": "cie-helper-9.9.9-setup.exe",
                "browser_download_url": (
                    "https://github.com/Ambitions0x39e/CAIE_helper/releases"
                    "/download/v9.9.9/cie-helper-9.9.9-setup.exe"
                ),
            },
            {
                "name": "cie-helper-9.9.9-setup.pkg",
                "browser_download_url": (
                    "https://github.com/Ambitions0x39e/CAIE_helper/releases"
                    "/download/v9.9.9/cie-helper-9.9.9-setup.pkg"
                ),
            },
        ]
    return {"tag_name": tag, "body": body, "assets": assets}


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test reaches the network instead of a fake."""
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("test made a real network call")

    monkeypatch.setattr(requests, "get", _boom)


def _patch_get(
    monkeypatch: pytest.MonkeyPatch, response: _FakeResponse,
) -> list[dict[str, Any]]:
    """Replace requests.get with a fake; return a log of the calls made."""
    calls: list[dict[str, Any]] = []

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        return response

    monkeypatch.setattr(requests, "get", _fake_get)
    return calls


# ---------------------------------------------------------------------------
# _parse_version
# ---------------------------------------------------------------------------


def test_parse_version_strips_leading_v() -> None:
    assert _parse_version("v1.2.3") == (1, 2, 3)
    assert _parse_version("1.2.3") == (1, 2, 3)
    assert _parse_version("  V10.0.11  ") == (10, 0, 11)


@pytest.mark.parametrize(
    "raw",
    ["", "v", "latest", "1.2", "1.2.3.4", "v1.2.x", "v1.-2.3", "nightly"],
)
def test_parse_version_rejects_non_three_part_numbers(raw: str) -> None:
    assert _parse_version(raw) is None


def test_parse_version_compares_numerically_not_lexically() -> None:
    """"1.10.0" > "1.9.0" — string comparison would get this wrong."""
    lower = _parse_version("v1.9.0")
    higher = _parse_version("v1.10.0")
    assert lower is not None and higher is not None
    assert higher > lower


def test_current_app_version_is_readable_and_parseable() -> None:
    version = current_app_version()
    assert version, "pyproject.toml version should be readable"
    assert _parse_version(version) is not None


# ---------------------------------------------------------------------------
# check() — version comparison
# ---------------------------------------------------------------------------


def test_check_reports_update_when_remote_version_is_newer(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v9.9.9")))

    result = AppUpdater(current_version="1.1.2").check()

    assert isinstance(result, UpdateCheckResult)
    assert result.success is True
    assert result.update_available is True
    assert result.latest_version == "9.9.9"
    assert result.release_notes == "Bug fixes."
    assert result.download_url is not None
    assert result.download_url.endswith("cie-helper-9.9.9-setup.exe")
    assert result.error is None


def test_check_reports_no_update_when_versions_are_equal(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v1.1.2")))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is True
    assert result.update_available is False
    assert result.latest_version == "1.1.2"
    assert result.download_url is None
    assert result.error is None


def test_check_reports_no_update_when_remote_version_is_older(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    """Never offer a downgrade — this is the live situation today (v1.0.0)."""
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v1.0.0")))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is True
    assert result.update_available is False
    assert result.latest_version == "1.0.0"
    assert result.download_url is None
    assert result.error is None


def test_check_treats_patch_bump_as_newer(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v1.1.3")))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.update_available is True


def test_check_treats_minor_bump_below_current_minor_as_older(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    """1.1.2 local vs 1.0.9 upstream — patch number must not win alone."""
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v1.0.9")))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.update_available is False


@pytest.mark.parametrize("tag", ["", "latest", "v1.1", "release-2026", "v1.x.2"])
def test_check_fails_on_unparseable_remote_version_tag(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, tag: str,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=_release(tag)))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.update_available is False
    assert result.error is not None
    assert "tag" in result.error.lower()


def test_check_fails_when_tag_name_is_missing_entirely(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload={"body": "x", "assets": []}))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.update_available is False


def test_check_fails_on_unparseable_local_version(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, no_network: None,
) -> None:
    """A broken local version must not be reported as "everything is newer"."""
    result = AppUpdater(current_version="dev").check()

    assert result.success is False
    assert result.update_available is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# check() — platform / asset selection
# ---------------------------------------------------------------------------


def test_check_picks_the_exe_asset_on_windows(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v9.9.9")))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.download_url is not None
    assert result.download_url.endswith(".exe")


def test_check_picks_the_pkg_asset_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v9.9.9")))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.update_available is True
    assert result.download_url is not None
    assert result.download_url.endswith(".pkg")


@pytest.mark.parametrize("platform", ["linux", "ios", "android", "freebsd"])
def test_check_reports_platform_not_supported_without_touching_network(
    monkeypatch: pytest.MonkeyPatch, no_network: None, platform: str,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.update_available is False
    assert result.error == "platform not supported"


def test_check_reports_platform_not_supported_when_no_asset_matches(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    """A release that only shipped a .pkg must not hand Windows the .pkg."""
    _patch_get(
        monkeypatch,
        _FakeResponse(
            payload=_release(
                "v9.9.9",
                assets=[
                    {
                        "name": "cie-helper-9.9.9-setup.pkg",
                        "browser_download_url": "https://example.test/a.pkg",
                    },
                ],
            ),
        ),
    )

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.update_available is False
    assert result.error == "platform not supported"
    assert result.download_url is None


def test_check_reports_platform_not_supported_when_assets_list_is_empty(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(
        monkeypatch, _FakeResponse(payload=_release("v9.9.9", assets=[])),
    )

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.error == "platform not supported"


def test_platform_asset_suffix_maps_only_win32_and_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert platform_asset_suffix() == ".exe"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert platform_asset_suffix() == ".pkg"
    monkeypatch.setattr(sys, "platform", "linux")
    assert platform_asset_suffix() is None


def test_releases_page_url_points_at_the_public_latest_release() -> None:
    """The UI opens this on platforms we cannot install for."""
    assert RELEASES_PAGE_URL == (
        "https://github.com/Ambitions0x39e/CAIE_helper/releases/latest"
    )


# ---------------------------------------------------------------------------
# check() — network failures
# ---------------------------------------------------------------------------


def test_check_returns_failure_on_request_timeout(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    def _timeout(*args: object, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(requests, "get", _timeout)

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.update_available is False
    assert result.error is not None
    assert "timed out" in result.error


def test_check_returns_failure_on_connection_error(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise requests.exceptions.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", _boom)

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.error is not None


def test_check_returns_failure_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(
        monkeypatch, _FakeResponse(payload=None, ok=False, status_code=403),
    )

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.error is not None
    assert "403" in result.error


def test_check_returns_failure_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(raise_on_json=True))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False
    assert result.error is not None


def test_check_returns_failure_when_payload_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=["not", "a", "dict"]))

    result = AppUpdater(current_version="1.1.2").check()

    assert result.success is False


def test_check_uses_a_ten_second_connect_timeout(
    monkeypatch: pytest.MonkeyPatch, on_windows: None,
) -> None:
    calls = _patch_get(monkeypatch, _FakeResponse(payload=_release("v9.9.9")))

    AppUpdater(current_version="1.1.2").check()

    assert len(calls) == 1
    timeout = calls[0]["timeout"]
    connect = timeout[0] if isinstance(timeout, tuple) else timeout
    assert connect == 10


# ---------------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------------


@pytest.fixture
def updates_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Path:
    """Point app_settings at a temp dir so downloads never touch ~/.cie_helper."""
    monkeypatch.setattr(updater_mod.app_settings, "base_dir", tmp_path)
    return tmp_path / "updates"


def test_download_streams_the_installer_into_updates_dir(
    monkeypatch: pytest.MonkeyPatch, updates_dir: Path,
) -> None:
    calls = _patch_get(
        monkeypatch, _FakeResponse(chunks=[b"abc", b"", b"def"]),
    )
    url = "https://example.test/download/v9.9.9/cie-helper-9.9.9-setup.exe"

    result = AppUpdater(current_version="1.1.2").download(url)

    assert isinstance(result, UpdateDownloadResult)
    assert result.success is True
    assert result.error is None
    assert result.local_path is not None
    written = Path(result.local_path)
    assert written.parent == updates_dir
    assert written.name == "cie-helper-9.9.9-setup.exe"
    assert written.read_bytes() == b"abcdef"
    assert calls[0]["stream"] is True
    timeout = calls[0]["timeout"]
    connect = timeout[0] if isinstance(timeout, tuple) else timeout
    assert connect == 10


def test_download_creates_updates_dir_when_absent(
    monkeypatch: pytest.MonkeyPatch, updates_dir: Path,
) -> None:
    assert not updates_dir.exists()
    _patch_get(monkeypatch, _FakeResponse())

    result = AppUpdater(current_version="1.1.2").download(
        "https://example.test/cie-helper-setup.exe"
    )

    assert result.success is True
    assert updates_dir.is_dir()


def test_download_ignores_query_strings_when_naming_the_file(
    monkeypatch: pytest.MonkeyPatch, updates_dir: Path,
) -> None:
    _patch_get(monkeypatch, _FakeResponse())

    result = AppUpdater(current_version="1.1.2").download(
        "https://example.test/cie-helper-setup.exe?token=abc123"
    )

    assert result.success is True
    assert result.local_path is not None
    assert Path(result.local_path).name == "cie-helper-setup.exe"


def test_download_returns_failure_on_network_error(
    monkeypatch: pytest.MonkeyPatch, updates_dir: Path,
) -> None:
    def _timeout(*args: object, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr(requests, "get", _timeout)

    result = AppUpdater(current_version="1.1.2").download(
        "https://example.test/x.exe"
    )

    assert result.success is False
    assert result.local_path is None
    assert result.error is not None
    assert "read timed out" in result.error


def test_download_returns_failure_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, updates_dir: Path,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(ok=False, status_code=404))

    result = AppUpdater(current_version="1.1.2").download(
        "https://example.test/x.exe"
    )

    assert result.success is False
    assert result.local_path is None
    assert result.error is not None
    assert "404" in result.error


# ---------------------------------------------------------------------------
# install()
# ---------------------------------------------------------------------------


def _spy_popen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace subprocess.Popen with a spy — nothing is ever really spawned."""
    calls: list[dict[str, Any]] = []

    def _fake_popen(argv: list[str], **kwargs: Any) -> object:
        calls.append({"argv": argv, **kwargs})
        return object()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    return calls


def _installer(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"MZ-not-really-an-installer")
    return path


def test_install_runs_inno_setup_silently_on_windows(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, tmp_path: Path,
) -> None:
    calls = _spy_popen(monkeypatch)
    exe = _installer(tmp_path, "cie-helper-9.9.9-setup.exe")

    result = AppUpdater(current_version="1.1.2").install(exe)

    assert isinstance(result, UpdateInstallResult)
    assert result.success is True
    assert result.error is None
    assert len(calls) == 1
    assert calls[0]["argv"] == [
        str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
    ]


def test_install_detaches_the_windows_installer_from_this_process(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, tmp_path: Path,
) -> None:
    """Without DETACHED_PROCESS the installer dies with the app we're closing."""
    calls = _spy_popen(monkeypatch)
    exe = _installer(tmp_path, "setup.exe")

    AppUpdater(current_version="1.1.2").install(exe)

    assert calls[0]["creationflags"] == (
        subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    )


def test_install_opens_the_pkg_with_open_on_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`open` shows Installer.app; the `installer` CLI would need sudo."""
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = _spy_popen(monkeypatch)
    pkg = _installer(tmp_path, "cie-helper-9.9.9-setup.pkg")

    result = AppUpdater(current_version="1.1.2").install(pkg)

    assert result.success is True
    assert len(calls) == 1
    assert calls[0]["argv"] == ["open", str(pkg)]
    assert "creationflags" not in calls[0]


def test_install_refuses_a_pkg_on_windows(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, tmp_path: Path,
) -> None:
    """Installing the wrong platform's package is worse than not updating."""
    calls = _spy_popen(monkeypatch)
    pkg = _installer(tmp_path, "cie-helper-9.9.9-setup.pkg")

    result = AppUpdater(current_version="1.1.2").install(pkg)

    assert result.success is False
    assert result.error is not None
    assert calls == []


def test_install_refuses_an_exe_on_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = _spy_popen(monkeypatch)
    exe = _installer(tmp_path, "cie-helper-9.9.9-setup.exe")

    result = AppUpdater(current_version="1.1.2").install(exe)

    assert result.success is False
    assert calls == []


def test_install_refuses_on_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    calls = _spy_popen(monkeypatch)
    deb = _installer(tmp_path, "cie-helper.deb")

    result = AppUpdater(current_version="1.1.2").install(deb)

    assert result.success is False
    assert result.error == "platform not supported"
    assert calls == []


def test_install_reports_a_missing_installer_file(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, tmp_path: Path,
) -> None:
    calls = _spy_popen(monkeypatch)

    result = AppUpdater(current_version="1.1.2").install(
        tmp_path / "never-downloaded.exe"
    )

    assert result.success is False
    assert result.error is not None
    assert calls == []


def test_install_reports_os_error_from_spawn(
    monkeypatch: pytest.MonkeyPatch, on_windows: None, tmp_path: Path,
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise OSError("[WinError 740] elevation required")

    monkeypatch.setattr(subprocess, "Popen", _fail)
    exe = _installer(tmp_path, "setup.exe")

    result = AppUpdater(current_version="1.1.2").install(exe)

    assert result.success is False
    assert result.error is not None
    assert "740" in result.error


# ---------------------------------------------------------------------------
# End-to-end (still fully faked): check → download → install
# ---------------------------------------------------------------------------


def test_check_download_install_round_trip_never_raises(
    monkeypatch: pytest.MonkeyPatch,
    on_windows: None,
    updates_dir: Path,
) -> None:
    _patch_get(monkeypatch, _FakeResponse(payload=_release("v9.9.9")))
    popen_calls = _spy_popen(monkeypatch)
    up = AppUpdater(current_version="1.1.2")

    check = up.check()
    assert check.update_available is True
    assert check.download_url is not None

    # Second leg reuses the same fake requests.get, now returning bytes.
    _patch_get(monkeypatch, _FakeResponse(chunks=[b"payload"]))
    download = up.download(check.download_url)
    assert download.success is True
    assert download.local_path is not None

    install = up.install(Path(download.local_path))
    assert install.success is True
    assert popen_calls[0]["argv"][1:] == [
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
    ]
