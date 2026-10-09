"""A data.csv carried over from another machine still finds its PDFs.

Rows written on Windows hold ``C:\\Users\\…\\pdfs\\<id>.pdf``. On a Mac that
path does not exist, but the file usually does — synced into this machine's
``pdfs/`` under the same name. Measured on a real store: 64 of 79 rows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.models import PaperRecord
from core.settings import app_settings
from core.storage import CSVStore


@pytest.fixture
def pdfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    app_settings.pdfs_dir.mkdir()
    return app_settings.pdfs_dir


def _store(tmp_path: Path, qp_path: str, ms_path: str) -> CSVStore:
    store = CSVStore(csv_path=tmp_path / "data.csv")
    store.save_all([PaperRecord(
        paper_id="9709_w24_qp_41", qp_path=qp_path, ms_path=ms_path,
    )])
    return store


def test_a_foreign_path_resolves_to_this_machines_copy(
    tmp_path: Path, pdfs: Path,
) -> None:
    (pdfs / "9709_w24_qp_41.pdf").write_bytes(b"%PDF")
    (pdfs / "9709_w24_ms_41.pdf").write_bytes(b"%PDF")
    store = _store(
        tmp_path,
        r"C:\Users\someone\.cie_helper\pdfs\9709_w24_qp_41.pdf",
        r"C:\Users\someone\.cie_helper\pdfs\9709_w24_ms_41.pdf",
    )

    [record] = store.load_all()

    assert record.qp_path == str(pdfs / "9709_w24_qp_41.pdf")
    assert record.ms_path == str(pdfs / "9709_w24_ms_41.pdf")


def test_a_path_with_no_local_copy_is_left_as_written(
    tmp_path: Path, pdfs: Path,
) -> None:
    foreign = r"C:\Users\someone\.cie_helper\pdfs\9709_w24_qp_41.pdf"
    store = _store(tmp_path, foreign, "")

    [record] = store.load_all()

    assert record.qp_path == foreign
    assert record.ms_path == ""


def test_an_existing_path_is_never_redirected(tmp_path: Path, pdfs: Path) -> None:
    elsewhere = tmp_path / "elsewhere" / "9709_w24_qp_41.pdf"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"%PDF")
    (pdfs / "9709_w24_qp_41.pdf").write_bytes(b"%PDF")
    store = _store(tmp_path, str(elsewhere), "")

    [record] = store.load_all()

    assert record.qp_path == str(elsewhere)
