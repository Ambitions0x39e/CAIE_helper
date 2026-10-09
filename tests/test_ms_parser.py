# tests/test_ms_parser.py

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fpdf import FPDF

from core.models import PaperType
from core.settings import GraderConfig
from modules.marking import ms_parser
from modules.marking.ms_parser import (
    _MS_START_PAGE_FALLBACK,
    PaperConfig,
    QuestionConfig,
    _cache_path_for,
    _call_vl,
    _load_cached,
    _merge_questions,
    _paper_info_from_text,
    _parse_image_ms_response,
    _save_cache,
    detect_ms_start_page,
    ms_cache_exists,
    normalize_question_id,
    parse_mark_scheme,
    resolve_ms_start_page,
)

# ── normalize_question_id ─────────────────────────────────────


def test_normalize_question_id_simple() -> None:
    assert normalize_question_id("1") == "Q1"


def test_normalize_question_id_with_part() -> None:
    assert normalize_question_id("2(a)") == "Q2a"


def test_normalize_question_id_strips() -> None:
    assert normalize_question_id("  3  ") == "Q3"


# ── Models ────────────────────────────────────────────────────


def test_question_config_model() -> None:
    qc = QuestionConfig(max_marks=7, mark_scheme="B1: correct answer")
    assert qc.max_marks == 7
    assert "B1" in qc.mark_scheme


def test_paper_config_model() -> None:
    pc = PaperConfig(
        paper_id="9231/41/O/N/22",
        total_marks=50,
        questions={"Q1": QuestionConfig(max_marks=7, mark_scheme="test")},
    )
    assert pc.total_marks == 50
    assert "Q1" in pc.questions


# ── _merge_questions ──────────────────────────────────────────


def test_merge_questions_no_overlap() -> None:
    base = {"Q1": QuestionConfig(max_marks=3, mark_scheme="M1: method")}
    new = {"Q2": QuestionConfig(max_marks=5, mark_scheme="B1: answer")}
    merged = _merge_questions(base, new)
    assert set(merged.keys()) == {"Q1", "Q2"}
    assert merged["Q1"].mark_scheme == "M1: method"
    assert merged["Q2"].mark_scheme == "B1: answer"


def test_merge_questions_with_overlap() -> None:
    base = {"Q1": QuestionConfig(max_marks=3, mark_scheme="M1: first part")}
    new = {"Q1": QuestionConfig(max_marks=5, mark_scheme="A1: second part")}
    merged = _merge_questions(base, new)
    assert merged["Q1"].max_marks == 5
    assert "M1: first part" in merged["Q1"].mark_scheme
    assert "A1: second part" in merged["Q1"].mark_scheme


# ── _call_vl ─────────────────────────────────────────────────


def test_call_vl_turns_thinking_off(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hybrid models think unless the request says otherwise; left on, one
    # batch spent 3554 of its 4475 output tokens thinking.
    sent: dict[str, Any] = {}

    def _create(**kwargs: Any) -> Any:
        sent.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
        )

    class _FakeClient:
        def __init__(self, **_kw: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    monkeypatch.setattr(ms_parser, "OpenAI", _FakeClient)
    _call_vl(GraderConfig(api_key="test-key"), [b"png"], "prompt")

    assert sent["extra_body"] == {"enable_thinking": False}


# ── _parse_image_ms_response ─────────────────────────────────


def test_parse_image_ms_response_valid() -> None:
    raw = json.dumps({
        "questions": [
            {"id": "1(a)", "max_marks": 3, "mark_scheme": "B1: x = 2"},
            {"id": "2", "max_marks": 5, "mark_scheme": "M1: integrate"},
        ]
    })
    result = _parse_image_ms_response(raw)
    assert "Q1a" in result
    assert "Q2" in result
    assert result["Q1a"].max_marks == 3
    assert result["Q2"].mark_scheme == "M1: integrate"


def test_parse_image_ms_response_with_fences() -> None:
    inner = json.dumps(
        {"questions": [{"id": "3", "max_marks": 2, "mark_scheme": "B1: y"}]}
    )
    raw = f"```json\n{inner}\n```"
    result = _parse_image_ms_response(raw)
    assert "Q3" in result
    assert result["Q3"].max_marks == 2


def test_parse_image_ms_response_empty() -> None:
    raw = json.dumps({"questions": []})
    result = _parse_image_ms_response(raw)
    assert result == {}


def test_parse_image_ms_response_non_integer_marks() -> None:
    # The VL model returns "N/A" (or floats / blanks) for rows without a
    # clean integer mark. A single such row must not crash the whole parse
    # — this is what made the 9701 chemistry mark scheme fail entirely.
    raw = json.dumps({
        "questions": [
            {"id": "2(a)", "max_marks": "N/A", "mark_scheme": "note"},
            {"id": "2(b)", "max_marks": "", "mark_scheme": "note"},
            {"id": "2(c)", "max_marks": 2.0, "mark_scheme": "B2"},
            {"id": "3", "max_marks": "3", "mark_scheme": "M3"},
        ]
    })
    result = _parse_image_ms_response(raw)
    assert result["Q2a"].max_marks == 0
    assert result["Q2b"].max_marks == 0
    assert result["Q2c"].max_marks == 2
    assert result["Q3"].max_marks == 3


def _one_question(mark_scheme: str) -> str:
    """A response carrying one mark scheme, verbatim — not via json.dumps,
    because what is being tested is the escaping on the wire."""
    return (
        '{"questions":[{"id":"1","max_marks":3,"mark_scheme":"'
        + mark_scheme + '"}]}'
    )


@pytest.mark.parametrize(("wire", "expected"), [
    # The prompt asks for every backslash doubled. These are what arrives
    # when one of them is not, and each would otherwise raise and take the
    # rest of the batch — a paid vision-model call — down with it.
    (r"A1: x = \sqrt{33}", r"A1: x = \sqrt{33}"),
    (r"A1: \alpha + \pi", r"A1: \alpha + \pi"),
    # "\u" is its own kind of invalid: JSON wants four hex digits after it.
    (r"A1: \upsilon", r"A1: \upsilon"),
    # A command that was doubled correctly must survive the repair beside
    # one that was not — read one character at a time, the second
    # backslash of "\\sqrt" looks exactly like a lone one.
    (r"A1: \\sqrt{33} then \alpha", r"A1: \sqrt{33} then \alpha"),
    (r"A1: \alpha then \\sqrt{33}", r"A1: \alpha then \sqrt{33}"),
])
def test_parse_image_ms_response_repairs_a_single_backslash(
    wire: str, expected: str
) -> None:
    result = _parse_image_ms_response(_one_question(wire))
    assert result["Q1"].mark_scheme == expected


@pytest.mark.parametrize(("wire", "expected"), [
    # Told to double every backslash, the model doubles the one in "\n"
    # as well — 11 of the 22 breaks on a live re-parse of 9701_w25_ms_23.
    (r"NaCl\\nM2 ethanol", "NaCl\nM2 ethanol"),
    (r"X\\nAND\\n41 is", "X\nAND\n41 is"),
    (r"2(y+1) = -y - 2 \\newline 8(y+1)", "2(y+1) = -y - 2 \n 8(y+1)"),
    # …but "\nu" and "\neq" are commands, and a matrix row break followed
    # by an "n" is a row break.
    (r"\\nu = 2 \\neq 3", r"\nu = 2 \neq 3"),
    (r"a \\\\n", r"a \\n"),
])
def test_parse_image_ms_response_restores_a_doubled_line_break(
    wire: str, expected: str
) -> None:
    result = _parse_image_ms_response(_one_question(wire))
    assert result["Q1"].mark_scheme == expected


def test_parse_image_ms_response_merges_an_id_printed_twice() -> None:
    """9701_w25_ms_23 came back with "4(a)(ii)" twice and no "4(a)(iii)";
    keeping only the second copy lost a marking point without a word."""
    raw = json.dumps({"questions": [
        {"id": "4(a)(ii)", "max_marks": 1, "mark_scheme": "PCl5 / SOCl2"},
        {"id": "4(a)(ii)", "max_marks": 2, "mark_scheme": "M1 NaOH"},
    ]})

    entry = _parse_image_ms_response(raw)["Q4(a)(ii)"]

    assert "PCl5" in entry.mark_scheme and "NaOH" in entry.mark_scheme


@pytest.mark.parametrize("wire", [
    r"B1: one\nM1: two",
    r"B1: say \"yes\"",
    r"B1: café",
    r"A1: \\frac{1}{2}",
])
def test_parse_image_ms_response_leaves_valid_escapes_alone(
    wire: str,
) -> None:
    """The repair runs only after a document has failed to parse, and a
    document that parses must come back exactly as JSON reads it."""
    assert _parse_image_ms_response(
        _one_question(wire)
    )["Q1"].mark_scheme == json.loads(f'"{wire}"')


# ── _paper_info_from_text ─────────────────────────────────────

_READABLE_COVER = (
    "Cambridge International AS & A Level\n"
    "CHEMISTRY 9701/23\n"
    "Paper 2 AS Structured Questions October/November 2025\n"
    "MARK SCHEME\n"
    "Maximum Mark: 60\n"
)


# A cover carrying every field the parser reads, for the cache-repair tests.
_FULL_COVER_PAGE = [
    "Cambridge International AS & A Level",
    "COMPUTER SCIENCE 9618/11",
    "Paper 1 Theory May/June 2024",
    "MARK SCHEME",
    "Maximum Mark: 75",
]


def _garble(text: str) -> str:
    """Mimic how a CID-font cover page actually extracts.

    pdfminer emits one glyph per line and drops the glyphs it cannot map
    (on 9701 the "i" is missing throughout), so "Maximum Mark: 60" arrives
    as a column of characters spelling "MaxmumMark:60".
    """
    return "\n".join(c for c in text if c != "i")


def test_paper_info_from_readable_cover() -> None:
    paper_id, total = _paper_info_from_text(_READABLE_COVER)
    assert paper_id == "9701/23/O/N/25"
    assert total == 60


def test_paper_info_from_garbled_cover() -> None:
    # The 9701 chemistry case: every field is present but shredded across
    # lines with glyphs missing, so the plain regexes matched nothing and
    # the UI showed "已解析: (42 题), 0 总分".
    paper_id, total = _paper_info_from_text(_garble(_READABLE_COVER))
    assert paper_id == "9701/23/O/N/25"
    assert total == 60


def test_paper_info_missing_fields_are_empty() -> None:
    paper_id, total = _paper_info_from_text("nothing useful here")
    assert paper_id == ""
    assert total == 0


# ── detect_ms_start_page ─────────────────────────────────────

_COVER_PAGE = [
    "Cambridge International AS & A Level",
    "COMPUTER SCIENCE",
    "MARK SCHEME",
    "Maximum Mark: 75",
]
_GENERIC_PAGE = [
    "Generic Marking Principles",
    "These general marking principles must be applied by all examiners",
    "GENERIC MARKING PRINCIPLE 1:",
    "Marks must be awarded in line with the specific content",
]


def _content_page(first_qid: str) -> list[str]:
    """A mark-scheme content page, carrying the repeated table header."""
    return [
        "9618/11  Cambridge International AS & A Level - Mark Scheme",
        "Question            Answer            Marks",
        first_qid,
        "1 mark for: (A XOR B) NOR C",
    ]


# An image-only content page: a blank page whose text layer is empty,
# standing in for a scanned/rendered answer page with no extractable text.
_IMAGED_PAGE: list[str] = []


def _make_ms_pdf(pages: list[list[str]]) -> bytes:
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(auto=False)
    for lines in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=10.8)
        y = 60.0
        for line in lines:
            pdf.text(60.0, y, line)
            y += 16.0
    return bytes(pdf.output())


def test_detect_ms_start_page_finds_first_content_page() -> None:
    # 9618-style: cover, generic principles, then content on page 3.
    pdf = _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    assert detect_ms_start_page(pdf) == 3


def test_detect_ms_start_page_ignores_front_matter() -> None:
    # 9231-style: five pages of front matter, content starts on page 6.
    pdf = _make_ms_pdf(
        [_COVER_PAGE, _GENERIC_PAGE, _GENERIC_PAGE, _GENERIC_PAGE,
         _GENERIC_PAGE, _content_page("1(a)")]
    )
    assert detect_ms_start_page(pdf) == 6


def test_detect_ms_start_page_content_without_sub_parts() -> None:
    # Q1 has no (a)/(b) — the table header still marks the content page.
    pdf = _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1")])
    assert detect_ms_start_page(pdf) == 3


def test_detect_ms_start_page_none_when_only_front_matter() -> None:
    # Only text front matter, no content marker of any kind → nothing.
    pdf = _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE])
    assert detect_ms_start_page(pdf) is None


def test_detect_ms_start_page_catches_imaged_first_question() -> None:
    # Q1 is a scanned image (empty text layer) on page 3; the table
    # header first reappears on page 4. Detection must pick page 3, or
    # Q1 would be skipped — the exact failure this fix targets.
    pdf = _make_ms_pdf(
        [_COVER_PAGE, _GENERIC_PAGE, _IMAGED_PAGE, _content_page("2(a)")]
    )
    assert detect_ms_start_page(pdf) == 3


def test_detect_ms_start_page_fully_imaged_content() -> None:
    # Every content page is an image (no header anywhere); the first
    # blank page after the cover still anchors the start.
    pdf = _make_ms_pdf(
        [_COVER_PAGE, _GENERIC_PAGE, _IMAGED_PAGE, _IMAGED_PAGE]
    )
    assert detect_ms_start_page(pdf) == 3


def test_resolve_ms_start_page_prefers_explicit_override() -> None:
    pdf = _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    assert resolve_ms_start_page(pdf, 5) == 5


def test_resolve_ms_start_page_autodetects_when_unset() -> None:
    pdf = _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    assert resolve_ms_start_page(pdf, None) == 3


def test_resolve_ms_start_page_falls_back_when_undetectable() -> None:
    pdf = _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE])
    assert resolve_ms_start_page(pdf, None) == _MS_START_PAGE_FALLBACK


# ── Cache keying ─────────────────────────────────────────────


@pytest.fixture
def cache_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the MS cache at a temp dir and return it."""
    from core.settings import app_settings

    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    app_settings.ms_cache_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_cache_path_differs_by_start_page(cache_env: Path) -> None:
    pdf = cache_env / "9618_s24_ms_11.pdf"
    plain = _cache_path_for(pdf)
    sp3 = _cache_path_for(pdf, 3)
    sp6 = _cache_path_for(pdf, 6)
    assert len({plain, sp3, sp6}) == 3


def test_ms_cache_exists_math_keyed_by_resolved_start_page(
    cache_env: Path,
) -> None:
    # Content detected on page 3; the cache entry is keyed to that page.
    pdf_path = cache_env / "9618_s24_ms_11.pdf"
    pdf_path.write_bytes(
        _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    )
    config = PaperConfig(paper_id="9618/11", total_marks=75, questions={})

    assert not ms_cache_exists(pdf_path, PaperType.MATH)
    _save_cache(pdf_path, config, 3)
    assert ms_cache_exists(pdf_path, PaperType.MATH)
    # A different explicit start page is a different cache entry.
    assert not ms_cache_exists(pdf_path, PaperType.MATH, start_page=6)


def test_ms_cache_exists_is_always_false_for_mcq(cache_env: Path) -> None:
    """MCQ mark schemes are parsed locally in a fraction of a second, so they
    are never cached — a cache entry would only preserve a bad parse across
    parser fixes (an earlier layout bug cached 2 questions instead of 40)."""
    pdf_path = cache_env / "9702_s24_ms_11.pdf"
    pdf_path.write_bytes(_make_ms_pdf([_COVER_PAGE]))
    config = PaperConfig(paper_id="9702/11", total_marks=40, questions={})
    _save_cache(pdf_path, config)

    assert not ms_cache_exists(pdf_path, PaperType.MCQ)


def test_cache_hit_backfills_missing_cover_info(cache_env: Path) -> None:
    # Papers parsed before the cover-text fix cached an empty paper_id and 0
    # total marks. Re-deriving those two fields is local and free, so a hit
    # repairs them in place rather than forcing a paid VL re-parse.
    pdf_path = cache_env / "9618_s24_ms_11.pdf"
    pdf_path.write_bytes(
        _make_ms_pdf([_FULL_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    )
    stale = PaperConfig(
        paper_id="",
        total_marks=0,
        questions={"Q1a": QuestionConfig(max_marks=3, mark_scheme="B1")},
    )
    _save_cache(pdf_path, stale, 3)

    result = parse_mark_scheme(pdf_path, paper_type=PaperType.MATH)

    assert result.total_marks == 75
    assert result.paper_id == "9618/11/M/J/24"
    assert "Q1a" in result.questions  # questions survive untouched
    # The repair is persisted, not recomputed on every hit.
    assert _load_cached(pdf_path, 3).total_marks == 75  # type: ignore[union-attr]


def test_cache_hit_keeps_good_cover_info(cache_env: Path) -> None:
    pdf_path = cache_env / "9618_s24_ms_11.pdf"
    pdf_path.write_bytes(
        _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    )
    good = PaperConfig(
        paper_id="9618/11/M/J/24",
        total_marks=75,
        questions={"Q1a": QuestionConfig(max_marks=3, mark_scheme="B1")},
    )
    _save_cache(pdf_path, good, 3)

    result = parse_mark_scheme(pdf_path, paper_type=PaperType.MATH)

    assert result.paper_id == "9618/11/M/J/24"
    assert result.total_marks == 75


def test_the_grading_type_is_cached_with_the_mark_scheme(cache_env: Path) -> None:
    """A cache written before the type was stored learns it on the next parse,
    and ``cached_mark_scheme`` hands it back to whoever reads the cache."""
    pdf_path = cache_env / "9702_s24_ms_21.pdf"
    pdf_path.write_bytes(
        _make_ms_pdf([_COVER_PAGE, _GENERIC_PAGE, _content_page("1(a)")])
    )
    untyped = PaperConfig(
        paper_id="9702/21/M/J/24",
        total_marks=60,
        questions={"Q1a": QuestionConfig(max_marks=3, mark_scheme="B1")},
    )
    _save_cache(pdf_path, untyped, 3)

    result = parse_mark_scheme(pdf_path, paper_type=PaperType.PHYSICS)

    assert result.paper_type is PaperType.PHYSICS
    cached = ms_parser.cached_mark_scheme(pdf_path)
    assert cached is not None
    assert cached.paper_type is PaperType.PHYSICS
