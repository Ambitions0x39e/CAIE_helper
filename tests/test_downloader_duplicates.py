"""Two variants of one component that are the same paper.

The PDFs are drawn with Pillow: a page is a white sheet with black boxes, and
the "paper number" is a small box on the cover — the only thing two copies of
one paper differ by.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
import requests
from PIL import Image, ImageDraw

from core.models import PaperRecord
from modules.downloader import DownloadRequest, PaperDownloader, same_pages

Box = tuple[int, int, int, int]


def _pdf(boxes_per_page: list[list[Box]]) -> bytes:
    pages = []
    for boxes in boxes_per_page:
        page = Image.new("L", (400, 560), 255)
        draw = ImageDraw.Draw(page)
        for box in boxes:
            draw.rectangle(box, fill=0)
        pages.append(page)
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


_QUESTIONS: list[list[Box]] = [
    [(40, 40, 360, 120)],
    [(40, 40, 360, 200), (40, 260, 200, 400)],
    [(40, 300, 360, 520)],
]
_OTHER_QUESTIONS: list[list[Box]] = [
    [(40, 40, 360, 120)],
    [(40, 300, 360, 520)],
    [(40, 40, 360, 200), (40, 260, 200, 400)],
]


def _paper(questions: list[list[Box]], number: int) -> bytes:
    """A paper whose cover carries ``number`` as a small mark."""
    cover = [*questions[0], (40 + number * 6, 500, 44 + number * 6, 506)]
    return _pdf([cover, *questions[1:]])


def test_variants_differing_only_in_the_paper_number_are_the_same(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(_paper(_QUESTIONS, 1))
    b.write_bytes(_paper(_QUESTIONS, 2))
    assert same_pages(a, b)


def test_different_questions_are_not_the_same(tmp_path: Path) -> None:
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(_paper(_QUESTIONS, 1))
    b.write_bytes(_paper(_OTHER_QUESTIONS, 2))
    assert not same_pages(a, b)


def test_different_page_counts_are_not_the_same(tmp_path: Path) -> None:
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(_paper(_QUESTIONS, 1))
    b.write_bytes(_paper(_QUESTIONS[:2], 1))
    assert not same_pages(a, b)


# ---------------------------------------------------------------------------
# download() refuses the copy
# ---------------------------------------------------------------------------


class _Response:
    status_code = 200
    ok = True
    headers = {"Content-Type": "application/pdf"}

    def __init__(self, body: bytes) -> None:
        self._body = body

    def iter_content(self, chunk_size: int = 1) -> Any:
        yield self._body


class _Store:
    def __init__(self) -> None:
        self.appended: list[PaperRecord] = []

    def append(self, record: PaperRecord) -> None:
        self.appended.append(record)


def _download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qp: bytes,
) -> tuple[Any, _Store, list[str]]:
    (tmp_path / "9618_s25_qp_31.pdf").write_bytes(_paper(_QUESTIONS, 1))
    urls: list[str] = []

    def get(url: str, **kwargs: Any) -> _Response:
        urls.append(url)
        return _Response(qp if "_qp_" in url else b"%PDF-1.7\nms\n")

    monkeypatch.setattr(requests, "get", get)
    store = _Store()
    downloader = PaperDownloader(store=store)  # type: ignore[arg-type]
    downloader._pdfs_dir = tmp_path
    result = downloader.download(DownloadRequest(paper_id="9618_s25_qp_32"))
    return result, store, urls


def test_a_copy_of_a_downloaded_variant_is_not_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    result, store, urls = _download(monkeypatch, tmp_path, _paper(_QUESTIONS, 2))

    assert not result.success
    assert result.duplicate_of == "9618_s25_qp_31"
    assert len(urls) == 1  # the MS is never fetched
    assert not (tmp_path / "9618_s25_qp_32.pdf").exists()
    assert store.appended == []


def test_a_different_variant_downloads_as_usual(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    result, store, _ = _download(monkeypatch, tmp_path, _paper(_OTHER_QUESTIONS, 2))

    assert result.success
    assert result.duplicate_of is None
    assert [r.paper_id for r in store.appended] == ["9618_s25_qp_32"]
