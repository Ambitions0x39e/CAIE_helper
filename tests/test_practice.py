"""Tests for ``modules.practice`` — 专项练习."""
from __future__ import annotations

import pytest

from modules.downloader import QueryEntry, QueryResult
from modules.marking.syllabus_parser import SyllabusInfo, SyllabusTopic
from modules.practice import (
    Picked,
    component_topics,
    papers_in_range,
    select,
    sessions_between,
)

# -- sessions_between --------------------------------------------------------


def test_a_range_runs_through_every_season_in_between() -> None:
    assert sessions_between(2023, "s", 2024, "w") == [
        ("2023", "s"), ("2023", "w"),
        ("2024", "m"), ("2024", "s"), ("2024", "w"),
    ]


def test_a_single_session_range_is_that_session() -> None:
    assert sessions_between(2024, "m", 2024, "m") == [("2024", "m")]


def test_a_backwards_range_is_empty() -> None:
    assert sessions_between(2024, "w", 2023, "s") == []


def test_an_unknown_season_is_refused() -> None:
    with pytest.raises(ValueError):
        sessions_between(2023, "x", 2024, "w")


# -- papers_in_range ---------------------------------------------------------


def _listing(*ids: str) -> QueryResult:
    return QueryResult(success=True, entries=[
        QueryEntry(paper_id=i, kind="qp" if "_qp_" in i else "other")
        for i in ids
    ])


def test_only_the_wanted_components_question_papers_are_taken() -> None:
    listings = {
        ("2023", "s"): _listing(
            "9709_s23_qp_41", "9709_s23_ms_41", "9709_s23_qp_42",
            "9709_s23_qp_31", "9709_s23_qp_43",
        ),
        ("2023", "w"): _listing("9709_w23_qp_41"),
    }
    ids, warnings = papers_in_range(
        "9709", "4", [("2023", "s"), ("2023", "w")],
        query=lambda _s, y, season: listings[(y, season)],
    )
    assert ids == [
        "9709_s23_qp_41", "9709_s23_qp_42", "9709_s23_qp_43", "9709_w23_qp_41",
    ]
    assert warnings == []


def test_a_session_that_fails_to_list_is_a_warning_not_an_abort() -> None:
    def query(_s: str, year: str, season: str) -> QueryResult:
        if season == "w":
            return QueryResult(success=False, error="HTTP 500")
        return _listing("9709_s23_qp_42")

    ids, warnings = papers_in_range(
        "9709", "4", [("2023", "s"), ("2023", "w")], query=query,
    )
    assert ids == ["9709_s23_qp_42"]
    assert warnings == ["w23: HTTP 500"]


# -- component_topics --------------------------------------------------------


def _syllabus() -> SyllabusInfo:
    return SyllabusInfo(
        subject_id="9709",
        topics={
            "4.1": SyllabusTopic(topic_id="4.1", name="Forces and equilibrium"),
            "4.2": SyllabusTopic(topic_id="4.2", name="Kinematics"),
            "1.1": SyllabusTopic(topic_id="1.1", name="Quadratics"),
        },
        component_topics={"4": ["4.1", "4.2"], "1": ["1.1"]},
    )


def test_component_topics_are_the_ones_the_syllabus_maps_to_it() -> None:
    assert component_topics(_syllabus(), "4") == {
        "4.1": "Forces and equilibrium", "4.2": "Kinematics",
    }


def test_no_syllabus_or_an_unmapped_component_has_no_topics() -> None:
    assert component_topics(None, "4") == {}
    assert component_topics(_syllabus(), "6") == {}


# -- select ------------------------------------------------------------------


def test_any_matching_topic_selects_the_question_in_paper_order() -> None:
    classified = {
        "9709_s23_qp_41": {"1": ["4.1"], "2": ["4.2", "4.5"], "3": []},
        "9709_w23_qp_41": {"1": ["4.5"], "4": ["4.2"]},
    }
    assert select(classified, {"4.2", "4.5"}) == [
        Picked("9709_s23_qp_41", "2"),
        Picked("9709_w23_qp_41", "1"),
        Picked("9709_w23_qp_41", "4"),
    ]


@pytest.mark.parametrize("season", ["", "ms", "M"])
def test_a_season_must_be_exactly_one_known_code(season: str) -> None:
    with pytest.raises(ValueError):
        sessions_between(2023, season, 2024, "w")


# -- classify_paper ----------------------------------------------------------

from core.settings import GraderConfig  # noqa: E402
from modules.question_pdf import Band, QuestionCrop  # noqa: E402

TOPICS = {"4.1": "Forces and equilibrium", "4.2": "Kinematics", "4.5": "Energy"}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from core.settings import app_settings

    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    return tmp_path / ".cache" / "topics"


@pytest.fixture
def three_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q1 and Q3 fit on one page; Q2 runs over a page break."""
    def crops(paper_id: str, qp_path: str):
        return [
            QuestionCrop(paper_id, "1", qp_path, [Band(1, 60.0, 300.0)]),
            QuestionCrop(paper_id, "2", qp_path, [
                Band(2, 60.0, 700.0), Band(3, 60.0, 200.0),
            ]),
            QuestionCrop(paper_id, "3", qp_path, [Band(4, 60.0, 500.0)]),
        ], []
    monkeypatch.setattr("modules.practice.crops_for_paper", crops)


class _Renderer:
    def __init__(self) -> None:
        self.calls = 0

    def render_regions(self, source, clips, dpi=200):
        self.calls += 1
        return [b"png"] * len(clips)

    def render_pages(self, source, page_numbers, dpi=200):
        raise AssertionError("not used")


def _classify(call, renderer=None):
    from modules.practice import classify_paper

    return classify_paper(
        "9709_s23_qp_41", "qp.pdf", TOPICS,
        config=GraderConfig(api_key="k"),
        renderer=renderer or _Renderer(),
        call=call,
    )


def test_the_model_sees_which_images_belong_to_which_question(
    cache_dir, three_questions,
) -> None:
    seen: dict[str, object] = {}

    def call(_config, pngs, prompt):
        seen["n"] = len(pngs)
        seen["prompt"] = prompt
        return '{"Q1": ["4.1"], "Q2": ["4.2", "4.5"], "Q3": ["4.5"]}'

    assert _classify(call) == {"1": ["4.1"], "2": ["4.2", "4.5"], "3": ["4.5"]}
    assert seen["n"] == 4
    prompt = str(seen["prompt"])
    assert "图 1 是 Q1" in prompt
    assert "图 2–3 是 Q2" in prompt
    assert "图 4 是 Q3" in prompt
    assert "4.2: Kinematics" in prompt


def test_ids_the_list_does_not_have_are_dropped(cache_dir, three_questions) -> None:
    def call(*_):
        return '```json\n{"Q1": ["4.1", "9.9"], "2": ["nope"], "Q3": "4.5"}\n```'

    assert _classify(call) == {"1": ["4.1"], "2": [], "3": ["4.5"]}


def test_an_unreadable_answer_is_an_error(cache_dir, three_questions) -> None:
    with pytest.raises(ValueError):
        _classify(lambda *_: "I think Q1 is about forces.")


def test_a_classified_paper_is_never_sent_twice(cache_dir, three_questions) -> None:
    calls: list[int] = []

    def call(*_):
        calls.append(1)
        return '{"Q1": ["4.1"], "Q2": [], "Q3": []}'

    first = _classify(call)
    second = _classify(call)
    assert first == second
    assert len(calls) == 1


def test_a_changed_topic_list_classifies_again(
    cache_dir, three_questions,
) -> None:
    from modules.practice import cached_classification

    _classify(lambda *_: '{"Q1": ["4.1"], "Q2": [], "Q3": []}')
    assert cached_classification("9709_s23_qp_41", TOPICS) is not None
    assert cached_classification(
        "9709_s23_qp_41", {**TOPICS, "4.6": "Momentum"},
    ) is None


# -- build_practice ----------------------------------------------------------

from core.models import PaperRecord  # noqa: E402
from modules.downloader import DownloadResult  # noqa: E402


class _Store:
    def __init__(self, records: list[PaperRecord]) -> None:
        self.records = records

    def load_all(self) -> list[PaperRecord]:
        return list(self.records)


class _Downloader:
    def __init__(self, store: _Store, tmp_path, fail: set[str] = frozenset()) -> None:
        self.store, self.tmp, self.fail, self.got = store, tmp_path, fail, []

    def download(self, request):
        pid = request.paper_id
        self.got.append(pid)
        if pid in self.fail:
            return DownloadResult(success=False, paper_id=pid, error="HTTP 404")
        qp = self.tmp / f"{pid}.pdf"
        qp.write_bytes(b"%PDF")
        ms = self.tmp / f"{pid.replace('_qp_', '_ms_')}.pdf"
        self.store.records.append(PaperRecord(
            paper_id=pid, qp_path=str(qp), ms_path=str(ms),
        ))
        return DownloadResult(
            success=True, paper_id=pid, qp_path=str(qp), ms_path=str(ms),
        )


def _request(**over):
    from modules.practice import PracticeRequest

    return PracticeRequest(**{
        "subject": "9709", "component": "4",
        "from_year": 2023, "from_season": "s", "to_year": 2023, "to_season": "w",
        "topic_ids": ["4.2"], **over,
    })


@pytest.fixture
def pipeline(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Two sessions, one 4x paper each; s23 is already on disk."""
    qp = tmp_path / "9709_s23_qp_41.pdf"
    qp.write_bytes(b"%PDF")
    store = _Store([PaperRecord(
        paper_id="9709_s23_qp_41", qp_path=str(qp), ms_path=str(tmp_path / "ms.pdf"),
    )])
    listings = {"s": _listing("9709_s23_qp_41"), "w": _listing("9709_w23_qp_42")}
    classified = {
        "9709_s23_qp_41": {"1": ["4.1"], "2": ["4.2"]},
        "9709_w23_qp_42": {"1": ["4.2", "4.5"], "2": ["4.5"]},
    }
    exported: dict[str, object] = {}

    monkeypatch.setattr(
        "modules.practice.classify_paper",
        lambda pid, *_a, **_k: classified[pid],
    )
    monkeypatch.setattr("modules.practice._parse_answers", lambda *_a, **_k: [])

    def export(records, qp_of, ms_of):
        exported["picks"] = list(records)
        exported["qp"] = dict(qp_of)
        return b"%PDF-practice", ["9709_w23_qp_42: mark scheme 里没有 1 的答案"]

    monkeypatch.setattr("modules.practice.build_export", export)
    return store, (lambda _s, _y, season: listings[season]), exported


def _run(store, query, tmp_path, request=None, fail=frozenset()):
    from modules.practice import build_practice

    events: list[tuple[str, int, int, str]] = []
    downloader = _Downloader(store, tmp_path, set(fail))
    out = build_practice(
        request or _request(), TOPICS,
        store=store, downloader=downloader,
        config=GraderConfig(api_key="k"), renderer=_Renderer(),
        on_progress=lambda *e: events.append(e), query=query,
    )
    return out, downloader, events


def test_missing_papers_are_downloaded_and_matching_questions_exported(
    pipeline, tmp_path,
) -> None:
    store, query, exported = pipeline
    (data, count, warnings), downloader, events = _run(store, query, tmp_path)

    assert downloader.got == ["9709_w23_qp_42"]
    assert exported["picks"] == [
        Picked("9709_s23_qp_41", "2"), Picked("9709_w23_qp_42", "1"),
    ]
    assert data == b"%PDF-practice"
    assert count == 2
    assert warnings == ["9709_w23_qp_42: mark scheme 里没有 1 的答案"]
    assert ("下载", 1, 1, "9709_w23_qp_42") in events
    assert ("分类", 2, 2, "9709_w23_qp_42") in events


def test_a_paper_that_fails_to_download_is_named_and_skipped(
    pipeline, tmp_path,
) -> None:
    store, query, exported = pipeline
    (_, count, warnings), _, _ = _run(
        store, query, tmp_path, fail={"9709_w23_qp_42"},
    )
    assert exported["picks"] == [Picked("9709_s23_qp_41", "2")]
    assert count == 1
    assert "9709_w23_qp_42: 下载失败（HTTP 404）" in warnings


def test_nothing_on_the_chosen_topics_is_an_error(pipeline, tmp_path) -> None:
    store, query, _ = pipeline
    with pytest.raises(ValueError, match="没有考到所选 topic"):
        _run(store, query, tmp_path, request=_request(topic_ids=["4.9"]))


def test_a_request_with_no_topics_is_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _request(topic_ids=[])


def test_a_paper_whose_classification_fails_is_named_and_the_rest_still_export(
    pipeline, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, query, exported = pipeline

    def classify(pid, *_a, **_k):
        if pid == "9709_w23_qp_42":
            raise ValueError("模型没有返回 JSON")
        return {"1": ["4.1"], "2": ["4.2"]}

    monkeypatch.setattr("modules.practice.classify_paper", classify)
    (_, count, warnings), _, _ = _run(store, query, tmp_path)

    assert "9709_w23_qp_42: 分类失败（模型没有返回 JSON）" in warnings
    assert exported["picks"] == [Picked("9709_s23_qp_41", "2")]
    assert count == 1


# -- _parse_answers ----------------------------------------------------------


def test_only_papers_without_a_cached_parse_are_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.practice import _parse_answers

    parsed: list[str] = []
    events: list[tuple[str, int, int, str]] = []
    monkeypatch.setattr(
        "modules.marking.ms_parser.cached_mark_scheme",
        lambda path: object() if path == "cached.pdf" else None,
    )
    monkeypatch.setattr(
        "modules.marking.ms_parser.parse_mark_scheme",
        lambda path, **_k: parsed.append(path),
    )
    monkeypatch.setattr(
        "modules.marking.syllabus_parser.resolve_grading_type", lambda _pid: "mark",
    )

    warnings = _parse_answers(
        ["a", "b", "c", "d"],
        {"a": "cached.pdf", "b": "", "c": "c.pdf", "d": "d.pdf"},
        GraderConfig(api_key="k"), _Renderer(),
        lambda *e: events.append(e),
    )

    assert warnings == []
    assert parsed == ["c.pdf", "d.pdf"]
    assert events == [("答案", 1, 2, "c"), ("答案", 2, 2, "d")]


def test_an_unknown_grading_type_and_a_failed_parse_are_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.practice import _parse_answers

    parsed: list[str] = []

    def parse(path, **_k):
        parsed.append(path)
        if path == "bad.pdf":
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "modules.marking.ms_parser.cached_mark_scheme", lambda _path: None,
    )
    monkeypatch.setattr("modules.marking.ms_parser.parse_mark_scheme", parse)
    monkeypatch.setattr(
        "modules.marking.syllabus_parser.resolve_grading_type",
        lambda pid: None if pid == "unknown" else "mark",
    )

    warnings = _parse_answers(
        ["unknown", "bad", "good"],
        {"unknown": "u.pdf", "bad": "bad.pdf", "good": "good.pdf"},
        GraderConfig(api_key="k"), _Renderer(), lambda *_e: None,
    )

    assert parsed == ["bad.pdf", "good.pdf"]
    assert warnings == [
        "unknown: 不知道这份卷的批改类型，没有解析 mark scheme",
        "bad: mark scheme 解析失败（boom）",
    ]
