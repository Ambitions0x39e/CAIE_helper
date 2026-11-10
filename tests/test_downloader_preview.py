"""``PaperDownloader.preview``: PDFs land in the folder given, nothing is recorded."""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.downloader import DownloadRequest
from tests.test_downloader_insert import (
    _MS,
    _QP,
    _FakeResponse,
    _GetRecorder,
    _make_downloader,
    _ok_pair,
)


def test_preview_writes_to_its_folder_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    library, folder = tmp_path / "pdfs", tmp_path / "preview"
    library.mkdir()
    folder.mkdir()
    downloader, store = _make_downloader(monkeypatch, library, _GetRecorder(_ok_pair()))

    result = downloader.preview(DownloadRequest(paper_id=_QP), folder)

    assert result.success
    assert result.qp_path == str(folder / f"{_QP}.pdf")
    assert result.ms_path == str(folder / f"{_MS}.pdf")
    assert store.appended == []
    assert list(library.iterdir()) == []


def test_preview_without_ms_still_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloader, _ = _make_downloader(
        monkeypatch, tmp_path, _GetRecorder({_QP: _FakeResponse()}),
    )

    result = downloader.preview(DownloadRequest(paper_id=_QP), tmp_path)

    assert result.success
    assert result.ms_path is None


def test_preview_refuses_a_non_qp_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloader, _ = _make_downloader(monkeypatch, tmp_path, _GetRecorder())

    result = downloader.preview(DownloadRequest(paper_id="9701_s25_gt"), tmp_path)

    assert not result.success
