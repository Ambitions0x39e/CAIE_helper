"""Find and download a subject's syllabus from cambridgeinternational.org.

The PDF's address carries an asset number (``/Images/697357-2026-2027-
syllabus.pdf``) that nothing about the subject predicts — 9231's 2028–2030
syllabus is 744603 and 9702's is 744626, numbered in upload order. So it is
read off the site rather than built:

1. The site's navigation, on every page, links each current subject as
   ``…-<code>/``; the home page has all of them.
2. That subject's page links its syllabuses by the years they cover.

A withdrawn syllabus (9707, replaced by 9609) has no subject page, and that
is reported as not found rather than guessed at.
"""
from __future__ import annotations

import datetime
import logging
import re

import requests

from core.settings import app_settings
from modules.marking.syllabus_parser import SyllabusInfo, parse_syllabus

_log = logging.getLogger("cie_helper.syllabus_fetch")

_SITE = "https://www.cambridgeinternational.org"
_TIMEOUT = 30.0
#: The site answers a bare client with a stripped page.
_HEADERS = {"User-Agent": "Mozilla/5.0"}

_SYLLABUS_RE = re.compile(r'href="(/Images/\d+-(\d{4})-(\d{4})-syllabus\.pdf)"')


def subject_page_path(home_html: str, subject_id: str) -> str | None:
    """The subject's page as the site's navigation links it."""
    m = re.search(rf'href="(/[^"]*-{re.escape(subject_id)})/?"', home_html)
    return m.group(1) + "/" if m else None


def syllabus_pdf_path(subject_html: str, year: int) -> str | None:
    """The syllabus covering *year*, else the newest one that has started.

    Update notices (``…-2026-2027-syllabus-update.pdf``) are not syllabuses
    and do not match.
    """
    found = sorted(
        {(int(a), int(b), path) for path, a, b in _SYLLABUS_RE.findall(subject_html)},
    )
    covering = [path for a, b, path in found if a <= year <= b]
    if covering:
        return covering[-1]
    started = [path for a, _, path in found if a <= year]
    return started[-1] if started else None


def _get(path: str) -> requests.Response:
    response = requests.get(_SITE + path, headers=_HEADERS, timeout=_TIMEOUT)
    response.raise_for_status()
    return response


def fetch_syllabus(subject_id: str) -> SyllabusInfo | None:
    """Download, parse and store this year's syllabus; None when it can't.

    Any failure — offline, a withdrawn code, a page the site has redesigned —
    is logged and returns None: grading then runs without topics, as it
    does for a subject nobody imported.

    ponytail: a code the site doesn't list is asked for again on every
    grading run — two page loads; remember misses if that ever shows.
    """
    try:
        page = subject_page_path(_get("/").text, subject_id)
        if page is None:
            _log.info("no subject page for %s", subject_id)
            return None
        pdf = syllabus_pdf_path(_get(page).text, datetime.date.today().year)
        if pdf is None:
            _log.info("no syllabus listed on %s", page)
            return None
        target = app_settings.base_dir / ".cache" / "syllabus" / f"{subject_id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_get(pdf).content)
        return parse_syllabus(target, subject_id, force=True)
    except Exception:
        _log.exception("fetching the %s syllabus failed", subject_id)
        return None
