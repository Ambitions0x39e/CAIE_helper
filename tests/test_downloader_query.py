"""Tests for the CIEFrank session query in modules.downloader.

Every test fakes the network with monkeypatch: nothing here may touch
cie.fraft.cn, and only ``requests.post`` is faked — ``query_available``
itself always runs for real, or these tests would prove nothing.

The season mapping is the dangerous part. ``m``/``s``/``w`` are the codes
that appear in every filename, but the endpoint wants ``Mar``/``Jun``/``Nov``.
Get it wrong and nothing raises — the response is still perfectly valid JSON,
just for a session the user didn't ask for. Hence test_season_code_mapping,
which pins all three codes against the wire values verified against the live
endpoint on 2026-07-31 (Nov → 9701_w25_*, Mar → 9701_m25_*, Jun → 9701_s25_*).
"""
from __future__ import annotations

from typing import Any

import pytest
import requests

from core.models import PaperRecord
from modules import downloader as downloader_mod
from modules.downloader import QueryResult, classify_paper_id, query_available

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stands in for requests.Response."""

    def __init__(
        self,
        *,
        payload: object = None,
        ok: bool = True,
        status_code: int = 200,
        raise_on_json: bool = False,
    ) -> None:
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self._raise_on_json = raise_on_json

    def json(self) -> object:
        if self._raise_on_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class _PostRecorder:
    """Captures the form data every ``requests.post`` call was made with."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        return self.response

    @property
    def last_form(self) -> dict[str, str]:
        data = self.calls[-1]["data"]
        assert isinstance(data, dict)
        return data


class _FakeStore:
    """Minimal CSVStore stand-in — only load_all() is ever called."""

    def __init__(self, paper_ids: list[str]) -> None:
        self._records = [
            PaperRecord(paper_id=pid, status="Pending") for pid in paper_ids
        ]

    def load_all(self) -> list[PaperRecord]:
        return list(self._records)


def _rows(*names: str) -> dict[str, object]:
    """The real success shape: total + rows[{file, lessons}] + collection."""
    return {
        "total": len(names),
        "rows": [{"file": name, "lessons": []} for name in names],
        "collection": True,
    }


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: object) -> _PostRecorder:
    recorder = _PostRecorder(response)
    monkeypatch.setattr(downloader_mod.requests, "post", recorder)
    return recorder


def _empty_store() -> _FakeStore:
    return _FakeStore([])


# ---------------------------------------------------------------------------
# ① Normal result + season mapping
# ---------------------------------------------------------------------------


def test_normal_nov_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real-shaped Nov response comes back classified, in order."""
    recorder = _patch_post(
        monkeypatch,
        _FakeResponse(
            payload=_rows(
                "9701_w25_qp_11.pdf",
                "9701_w25_ms_11.pdf",
                "9701_w25_ci_31.pdf",
                "9701_w25_gt.pdf",
            )
        ),
    )

    result = query_available("9701", "2025", "w", store=_empty_store())

    assert isinstance(result, QueryResult)
    assert result.success is True
    assert result.error is None
    assert [(e.paper_id, e.kind) for e in result.entries] == [
        ("9701_w25_qp_11", "qp"),
        ("9701_w25_ms_11", "other"),
        ("9701_w25_ci_31", "other"),
        ("9701_w25_gt", "gt"),
    ]
    # .pdf stripped -> exactly what DownloadRequest accepts
    assert all(not e.paper_id.endswith(".pdf") for e in result.entries)
    assert all(e.already_downloaded is False for e in result.entries)

    assert recorder.calls[0]["url"] == downloader_mod._URL_RENUM
    assert recorder.last_form == {"subject": "9701", "year": "2025", "season": "Nov"}


@pytest.mark.parametrize(
    ("season", "wire"),
    [("m", "Mar"), ("s", "Jun"), ("w", "Nov")],
)
def test_season_code_mapping(
    monkeypatch: pytest.MonkeyPatch, season: str, wire: str
) -> None:
    """m/s/w must reach the endpoint as Mar/Jun/Nov — verified live 2026-07-31."""
    recorder = _patch_post(monkeypatch, _FakeResponse(payload=_rows()))

    result = query_available("9701", "2025", season, store=_empty_store())  # type: ignore[arg-type]

    assert result.success is True
    assert recorder.last_form["season"] == wire


def test_unknown_season_code_never_hits_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_post(monkeypatch, _FakeResponse(payload=_rows()))

    result = query_available("9701", "2025", "x", store=_empty_store())  # type: ignore[arg-type]

    assert result.success is False
    assert result.error is not None
    assert recorder.calls == []


def test_inputs_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_post(monkeypatch, _FakeResponse(payload=_rows()))

    query_available("  9701 ", " 2025 ", "w", store=_empty_store())

    assert recorder.last_form == {"subject": "9701", "year": "2025", "season": "Nov"}


# ---------------------------------------------------------------------------
# ② Empty result — a future session is not an error
# ---------------------------------------------------------------------------


def test_empty_result_is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(
        monkeypatch,
        _FakeResponse(payload={"total": 0, "rows": [], "collection": True}),
    )

    result = query_available("9701", "2099", "w", store=_empty_store())

    assert result.success is True
    assert result.entries == []
    assert result.error is None


# ---------------------------------------------------------------------------
# ③ Error shapes
# ---------------------------------------------------------------------------


def test_illegal_subject_shape_is_an_error_not_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """{"status":101,...} carries no rows key — must never read as 'no papers'."""
    _patch_post(
        monkeypatch,
        _FakeResponse(
            payload={"status": 101, "data": None, "message": "路径非法。"}
        ),
    )

    result = query_available("notasubject", "2025", "w", store=_empty_store())

    assert result.success is False
    assert result.entries == []
    assert result.error is not None
    assert "路径非法。" in result.error


def test_network_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str, **kwargs: Any) -> object:
        raise requests.ConnectionError("proxy said no")

    monkeypatch.setattr(downloader_mod.requests, "post", _boom)

    result = query_available("9701", "2025", "w", store=_empty_store())

    assert result.success is False
    assert result.error is not None
    assert "proxy said no" in result.error


def test_http_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _FakeResponse(ok=False, status_code=503, payload=None))

    result = query_available("9701", "2025", "w", store=_empty_store())

    assert result.success is False
    assert result.error is not None
    assert "503" in result.error


def test_non_json_body_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _FakeResponse(raise_on_json=True))

    result = query_available("9701", "2025", "w", store=_empty_store())

    assert result.success is False
    assert result.error is not None


def test_rows_of_the_wrong_type_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(monkeypatch, _FakeResponse(payload={"total": 1, "rows": "nope"}))

    result = query_available("9701", "2025", "w", store=_empty_store())

    assert result.success is False
    assert result.error is not None


def test_junk_rows_are_skipped_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(
        monkeypatch,
        _FakeResponse(
            payload={
                "total": 4,
                "rows": [
                    {"file": "9701_w25_qp_11.pdf"},
                    {"file": ""},
                    {"lessons": []},
                    "not-a-dict",
                ],
                "collection": True,
            }
        ),
    )

    result = query_available("9701", "2025", "w", store=_empty_store())

    assert result.success is True
    assert [e.paper_id for e in result.entries] == ["9701_w25_qp_11"]


# ---------------------------------------------------------------------------
# ④ already_downloaded
# ---------------------------------------------------------------------------


def test_already_downloaded_flags_stored_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        _FakeResponse(
            payload=_rows(
                "9701_w25_qp_11.pdf",
                "9701_w25_qp_12.pdf",
                "9701_w25_gt.pdf",
            )
        ),
    )
    store = _FakeStore(["9701_w25_qp_12", "9999_s24_qp_11"])

    result = query_available("9701", "2025", "w", store=store)

    assert result.success is True
    flags = {e.paper_id: e.already_downloaded for e in result.entries}
    assert flags == {
        "9701_w25_qp_11": False,
        "9701_w25_qp_12": True,
        "9701_w25_gt": False,
    }


def test_unreadable_store_degrades_to_no_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenStore:
        def load_all(self) -> list[PaperRecord]:
            raise OSError("data.csv is gone")

    _patch_post(monkeypatch, _FakeResponse(payload=_rows("9701_w25_qp_11.pdf")))

    result = query_available("9701", "2025", "w", store=_BrokenStore())  # type: ignore[arg-type]

    assert result.success is True
    assert result.entries[0].already_downloaded is False


# ---------------------------------------------------------------------------
# kind classification (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("paper_id", "kind"),
    [
        ("9701_w25_qp_11", "qp"),
        ("9231_s25_qp_31", "qp"),
        ("9701_w25_gt", "gt"),
        ("9701_w25_ms_11", "other"),
        ("9701_w25_ci_31", "other"),
        ("9701_w25_in_31", "other"),
        ("9701_w25_er", "other"),
        ("9701_w25_qp", "other"),
        ("9701_w25_gt_11", "other"),
        ("nonsense", "other"),
        ("", "other"),
    ],
)
def test_classify_paper_id(paper_id: str, kind: str) -> None:
    assert classify_paper_id(paper_id) == kind


# ---------------------------------------------------------------------------
# has_insert — which QPs come with an insert
# ---------------------------------------------------------------------------


def test_qp_is_marked_when_the_session_lists_its_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0500_s25_qp_11 + 0500_s25_in_11 in one listing → the QP carries the flag.

    This is what makes the UI hang the insert under its QP instead of dumping
    it in the unsupported pile, and what makes the download run with
    insert=True for that row.
    """
    _patch_post(
        monkeypatch,
        _FakeResponse(
            payload=_rows(
                "0500_s25_qp_11.pdf",
                "0500_s25_ms_11.pdf",
                "0500_s25_in_11.pdf",
                "0500_s25_qp_12.pdf",
                "0500_s25_ms_12.pdf",
            )
        ),
    )

    result = query_available("0500", "2025", "s", store=_empty_store())
    flags = {e.paper_id: e.has_insert for e in result.entries}

    assert flags["0500_s25_qp_11"] is True
    # No 0500_s25_in_12 in the listing → no insert to fetch.
    assert flags["0500_s25_qp_12"] is False
    # The flag only ever rides on the QP row.
    assert flags["0500_s25_in_11"] is False
    assert flags["0500_s25_ms_11"] is False


def test_orphan_insert_marks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """An insert whose QP isn't in the listing leaves every entry unflagged."""
    _patch_post(
        monkeypatch,
        _FakeResponse(payload=_rows("0500_s25_qp_11.pdf", "0500_s25_in_21.pdf")),
    )

    result = query_available("0500", "2025", "s", store=_empty_store())

    assert all(e.has_insert is False for e in result.entries)
