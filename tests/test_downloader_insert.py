"""Tests for ``PaperDownloader.download_with_insert``.

The network is faked with monkeypatch — nothing here may touch cie.fraft.cn.
Only ``requests.get`` is replaced; ``download_with_insert`` itself always runs
for real.

Two things these tests exist to pin down:

* **A missing insert is not a failure.** Most papers have no ``_in_`` file at
  all, so a 404 on the insert must still leave QP+MS downloaded, the record
  appended, and ``success=True``. Any other insert failure (network, HTTP 500)
  also keeps ``success=True`` but must not be swallowed — it surfaces in
  ``insert_error``.
* **``download()`` stays insert-free.** The whole point of a separate method is
  that the plain-download screens can't accidentally pull an insert; a test
  guards that rather than a comment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from core.models import PaperRecord
from modules.downloader import DownloadRequest, PaperDownloader

_QP = "9701_s25_qp_31"
_MS = "9701_s25_ms_31"
_IN = "9701_s25_in_31"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stands in for requests.Response as ``_fetch_pdf`` uses it."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content_type: str = "application/pdf",
        body: bytes = b"%PDF-1.7\nfake\n",
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.headers = {"Content-Type": content_type}
        self._body = body

    def iter_content(self, chunk_size: int = 1) -> Any:
        yield self._body


class _GetRecorder:
    """Serves canned responses keyed by filename stem; 404s anything else.

    Defaulting to 404 is deliberate: that is exactly what the real endpoint
    does for a paper with no insert, which is the common case.
    """

    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.urls: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.urls.append(url)
        for stem, response in self.responses.items():
            if url.endswith(f"/{stem}.pdf"):
                if isinstance(response, Exception):
                    raise response
                return response
        return _FakeResponse(status_code=404)

    def fetched_stems(self) -> list[str]:
        return [url.rsplit("/", 1)[-1].removesuffix(".pdf") for url in self.urls]


class _RecordingStore:
    """Minimal CSVStore stand-in — only append() is ever called."""

    def __init__(self, existing: tuple[str, ...] = ()) -> None:
        self.appended: list[PaperRecord] = []
        self._ids = set(existing)

    def append(self, record: PaperRecord) -> None:
        if record.paper_id in self._ids:
            raise ValueError(
                f"paper_id '{record.paper_id}' already exists in the store"
            )
        self._ids.add(record.paper_id)
        self.appended.append(record)


def _make_downloader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    recorder: _GetRecorder,
    store: _RecordingStore | None = None,
) -> tuple[PaperDownloader, _RecordingStore]:
    # Same module object ``modules.downloader`` calls ``requests.get`` on;
    # monkeypatch puts it back after each test.
    monkeypatch.setattr(requests, "get", recorder)
    store = store or _RecordingStore()
    downloader = PaperDownloader(store=store)  # type: ignore[arg-type]
    downloader._pdfs_dir = tmp_path
    return downloader, store


def _ok_pair() -> dict[str, object]:
    return {_QP: _FakeResponse(), _MS: _FakeResponse()}


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_downloads_qp_ms_and_insert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _GetRecorder({**_ok_pair(), _IN: _FakeResponse()})
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert result.success
    assert recorder.fetched_stems() == [_QP, _MS, _IN]
    assert result.qp_path == str(tmp_path / f"{_QP}.pdf")
    assert result.ms_path == str(tmp_path / f"{_MS}.pdf")
    assert result.insert_path == str(tmp_path / f"{_IN}.pdf")
    assert result.insert_error is None
    assert (tmp_path / f"{_IN}.pdf").read_bytes().startswith(b"%PDF")


def test_registers_the_qp_ms_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The store row is the same one ``download()`` writes — insert excluded."""
    recorder = _GetRecorder({**_ok_pair(), _IN: _FakeResponse()})
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert len(store.appended) == 1
    record = store.appended[0]
    assert record.paper_id == _QP
    assert record.status == "Pending"
    assert record.qp_path == str(tmp_path / f"{_QP}.pdf")
    assert record.ms_path == str(tmp_path / f"{_MS}.pdf")


# ---------------------------------------------------------------------------
# The insert is optional
# ---------------------------------------------------------------------------


def test_missing_insert_still_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """404 on the insert = this paper simply hasn't got one."""
    recorder = _GetRecorder(_ok_pair())  # unlisted stems 404
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert result.success
    assert result.insert_path is None
    assert result.insert_error is None
    assert result.qp_path and result.ms_path
    assert len(store.appended) == 1


def test_broken_insert_fetch_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A network blow-up on the insert is a warning, not a failed download."""
    recorder = _GetRecorder(
        {**_ok_pair(), _IN: requests.ConnectionError("connection reset")}
    )
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert result.success
    assert result.insert_path is None
    assert result.insert_error is not None
    assert "connection reset" in result.insert_error
    assert len(store.appended) == 1


def test_insert_http_500_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _GetRecorder({**_ok_pair(), _IN: _FakeResponse(status_code=500)})
    downloader, _ = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert result.success
    assert result.insert_path is None
    assert result.insert_error and "500" in result.insert_error


# ---------------------------------------------------------------------------
# QP / MS failures are still fatal
# ---------------------------------------------------------------------------


def test_missing_qp_fails_and_skips_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _GetRecorder({_MS: _FakeResponse(), _IN: _FakeResponse()})
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert not result.success
    assert result.error and "404" in result.error
    assert recorder.fetched_stems() == [_QP]
    assert store.appended == []


def test_missing_ms_fails_and_skips_the_insert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _GetRecorder({_QP: _FakeResponse(), _IN: _FakeResponse()})
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert not result.success
    assert recorder.fetched_stems() == [_QP, _MS]
    assert store.appended == []


def test_duplicate_paper_id_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _GetRecorder({**_ok_pair(), _IN: _FakeResponse()})
    downloader, store = _make_downloader(
        monkeypatch, tmp_path, recorder, _RecordingStore(existing=(_QP,))
    )

    result = downloader.download_with_insert(DownloadRequest(paper_id=_QP))

    assert not result.success
    assert result.error and "already exists" in result.error


def test_gt_id_is_rejected_without_touching_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GT has no QP/MS pair, so pairing + insert makes no sense for it."""
    recorder = _GetRecorder()
    downloader, store = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download_with_insert(DownloadRequest(paper_id="9701_s25_gt"))

    assert not result.success
    assert recorder.urls == []
    assert store.appended == []


# ---------------------------------------------------------------------------
# Isolation: plain download() is untouched
# ---------------------------------------------------------------------------


def test_plain_download_never_fetches_an_insert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _GetRecorder({**_ok_pair(), _IN: _FakeResponse()})
    downloader, _ = _make_downloader(monkeypatch, tmp_path, recorder)

    result = downloader.download(DownloadRequest(paper_id=_QP))

    assert result.success
    assert recorder.fetched_stems() == [_QP, _MS]
    assert result.insert_path is None
    assert result.insert_error is None


def test_insert_id_derivation() -> None:
    assert DownloadRequest(paper_id=_QP).insert_id == _IN
    assert DownloadRequest(paper_id="9701_s25_gt").insert_id == ""
