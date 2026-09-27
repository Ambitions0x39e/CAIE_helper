"""Tests for ``modules.marking.syllabus_fetch`` — reading the links off the
site's pages, offline. The snippets are the real links as the site served
them."""
from __future__ import annotations

import pytest
import requests

from modules.marking import syllabus_fetch
from modules.marking.syllabus_fetch import (
    fetch_syllabus,
    subject_page_path,
    syllabus_pdf_path,
)

_VIEW = "/programmes-and-qualifications/view/cambridge-international-as-and-a-level"
_HOME = f"""
<a href="{_VIEW}-mathematics-9709/">Mathematics</a>
<a href="{_VIEW}-mathematics-further-9231/">Further</a>
<a href="/programmes-and-qualifications/cambridge-igcse-physics-0625/">Physics</a>
"""

_SUBJECT = """
<a href="/Images/597381-2023-2025-syllabus.pdf">2023-2025</a>
<a href="/Images/697357-2026-2027-syllabus.pdf">2026-2027</a>
<a href="/Images/729291-2026-2027-syllabus-update.pdf">Update</a>
<a href="/Images/744603-2028-2030-syllabus.pdf">2028-2030</a>
"""


def test_the_subject_page_is_found_by_the_code_its_link_ends_in() -> None:
    assert subject_page_path(_HOME, "9231") == (
        "/programmes-and-qualifications/view/"
        "cambridge-international-as-and-a-level-mathematics-further-9231/"
    )
    assert subject_page_path(_HOME, "0625") == (
        "/programmes-and-qualifications/cambridge-igcse-physics-0625/"
    )


def test_a_withdrawn_code_has_no_subject_page() -> None:
    assert subject_page_path(_HOME, "9707") is None


@pytest.mark.parametrize(
    "year,expected",
    [
        (2026, "/Images/697357-2026-2027-syllabus.pdf"),
        (2024, "/Images/597381-2023-2025-syllabus.pdf"),
        (2029, "/Images/744603-2028-2030-syllabus.pdf"),
        # Past every range: the newest that has started.
        (2031, "/Images/744603-2028-2030-syllabus.pdf"),
        (2020, None),
    ],
)
def test_the_syllabus_is_the_one_covering_the_year(
    year: int, expected: str | None,
) -> None:
    assert syllabus_pdf_path(_SUBJECT, year) == expected


def test_an_unreachable_site_is_none_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _offline(*_: object, **__: object) -> None:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(syllabus_fetch.requests, "get", _offline)
    assert fetch_syllabus("9231") is None
