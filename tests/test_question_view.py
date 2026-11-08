"""Where one main question sits in a mark scheme.

Two pure decisions: which labels read off the first table column to believe,
and which slices of which pages a question is shown as. The page geometry is
hand-written here, on a 612pt-high page with a table from y80 to y500.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fpdf import FPDF
from PIL import Image

from core.settings import app_settings
from modules import question_view
from modules.marking.page_segmenter import PageClip
from modules.question_pdf import Band, QuestionCrop
from modules.question_view import (
    MsLabel,
    PageArea,
    accept_labels,
    is_first_part,
    list_questions,
    mark_scheme_clips,
    question_images,
    read_ms_layout,
)

TEXT = PageArea(top=80.0, bottom=500.0, left=50.0, right=740.0, is_image=False)
IMAGE = PageArea(top=80.0, bottom=500.0, left=50.0, right=740.0, is_image=True)


def label(number: int, page: int, y: float, first_part: bool = True) -> MsLabel:
    return MsLabel(number=number, page=page, y=y, first_part=first_part)


def slices(clips):
    return [(c.page_idx, c.y_top, c.y_bottom) for c in clips]


# ── Which labels to believe ──────────────────────────────────────


def test_a_number_ahead_of_the_expected_one_is_not_a_label_on_text_pages():
    """A stray 13 in the column must not swallow questions 2 to 12."""
    candidates = [label(1, 3, 100), label(13, 3, 200), label(2, 3, 300)]
    assert accept_labels(candidates, [1, 2, 13], [TEXT] * 5) == [
        label(1, 3, 100), label(2, 3, 300),
    ]


def test_a_gap_is_believed_when_an_image_page_could_hold_the_missing_question():
    candidates = [label(1, 1, 100), label(3, 3, 100)]
    areas = [TEXT, TEXT, IMAGE, TEXT]
    assert accept_labels(candidates, [1, 2, 3], areas) == candidates


def test_a_gap_may_span_several_questions_lost_on_image_pages():
    candidates = [label(1, 1, 100), label(5, 4, 100)]
    areas = [TEXT, TEXT, IMAGE, IMAGE, TEXT]
    assert accept_labels(candidates, [1, 2, 3, 4, 5], areas) == candidates


def test_a_repeat_of_an_accepted_number_is_ignored():
    """4(a) then 4(b): the question starts at the first one."""
    candidates = [label(4, 2, 100), label(4, 2, 300, first_part=False)]
    assert accept_labels(candidates, [4], [TEXT] * 3) == [label(4, 2, 100)]


# ── What counts as a question's opening row ──────────────────────


def test_first_part_labels():
    for rest in ("", "(a)", "(a)(i)", "(i)", "a"):
        assert is_first_part(rest), rest
    for rest in ("(b)", "(a)(ii)", "(ii)", "(c)(i)"):
        assert not is_first_part(rest), rest


# ── Which slices a question is shown as ──────────────────────────


def test_a_question_runs_to_the_next_ones_label_across_pages():
    labels = [label(1, 3, 100), label(2, 3, 300), label(3, 5, 150)]
    clips = mark_scheme_clips([1, 2, 3], labels, [TEXT] * 7, first_page=3)
    assert slices(clips[1]) == [(3, 100, 300)]
    assert slices(clips[2]) == [(3, 300, 500), (4, 80, 500), (5, 80, 150)]


def test_the_last_question_runs_to_the_end_of_the_last_page():
    labels = [label(1, 1, 100)]
    clips = mark_scheme_clips([1], labels, [TEXT] * 3, first_page=1)
    assert slices(clips[1]) == [(1, 100, 500), (2, 80, 500)]


def test_slices_are_cut_to_the_page_table_width():
    clips = mark_scheme_clips([1], [label(1, 0, 100)], [TEXT], first_page=0)
    assert (clips[1][0].x_left, clips[1][0].x_right) == (50.0, 740.0)


def test_nothing_is_shown_of_a_next_question_starting_at_the_table_top():
    labels = [label(1, 1, 100), label(2, 2, 80)]
    clips = mark_scheme_clips([1, 2], labels, [TEXT] * 3, first_page=1)
    assert slices(clips[1]) == [(1, 100, 500)]


def test_a_sliver_above_the_next_question_is_not_shown():
    """Just the table's top edge, which would show as a stray line."""
    labels = [label(1, 1, 100), label(2, 2, 84)]
    clips = mark_scheme_clips([1, 2], labels, [TEXT] * 3, first_page=1)
    assert slices(clips[1]) == [(1, 100, 500)]


def test_opening_part_on_an_image_page_is_not_lost():
    """Measured on 9231_s25_14: 4(a) is on an image page and the first readable
    label is 4(b), so starting at that label hid half the mark scheme."""
    areas = [TEXT, IMAGE, TEXT, TEXT]
    labels = [label(3, 0, 200), label(4, 2, 214, first_part=False)]
    clips = mark_scheme_clips([3, 4], labels, areas, first_page=0)
    assert slices(clips[4]) == [(1, 80, 500), (2, 80, 500), (3, 80, 500)]
    # The image page may hold the end of Q3 as well, so Q3 keeps it too.
    assert slices(clips[3]) == [(0, 200, 500), (1, 80, 500), (2, 80, 214)]


def test_a_labelled_opening_part_does_not_reach_back_over_an_image_page():
    areas = [TEXT, IMAGE, TEXT, TEXT]
    labels = [label(3, 0, 200), label(4, 2, 214)]
    clips = mark_scheme_clips([3, 4], labels, areas, first_page=0)
    assert slices(clips[4])[0] == (2, 214, 500)


def test_a_question_with_no_label_starts_at_the_first_image_page_after_the_last():
    areas = [TEXT, TEXT, IMAGE, IMAGE, TEXT]
    labels = [label(4, 1, 100), label(6, 4, 150)]
    clips = mark_scheme_clips([4, 5, 6], labels, areas, first_page=0)
    assert slices(clips[5]) == [(2, 80, 500), (3, 80, 500), (4, 80, 150)]


def test_a_question_with_no_label_and_no_image_page_shows_from_the_last_label():
    labels = [label(1, 0, 100), label(3, 1, 150)]
    clips = mark_scheme_clips([1, 2, 3], labels, [TEXT] * 2, first_page=0)
    assert slices(clips[2]) == [(0, 100, 500), (1, 80, 150)]


def test_an_unlabelled_first_question_starts_at_the_first_content_page():
    areas = [TEXT, IMAGE, IMAGE, TEXT]
    labels = [label(2, 3, 150)]
    clips = mark_scheme_clips([1, 2], labels, areas, first_page=2)
    assert slices(clips[1]) == [(2, 80, 500), (3, 80, 150)]


def test_every_question_is_shown_when_no_label_was_read_at_all():
    areas = [TEXT, IMAGE, IMAGE]
    clips = mark_scheme_clips([1, 2], [], areas, first_page=1)
    assert slices(clips[1]) == [(1, 80, 500), (2, 80, 500)]
    assert slices(clips[2]) == [(1, 80, 500), (2, 80, 500)]


# ── Reading a mark scheme PDF ────────────────────────────────────


def _table_row(pdf: FPDF, cells: tuple[str, str, str], height: float = 24) -> None:
    # The Answer column starts 52pt in, as narrow as 9231's: its text must not
    # read as part of the label.
    pdf.cell(52, height, cells[0], border=1)
    align = "C" if cells[1] == "Answer" else "L"
    pdf.cell(568, height, cells[1], border=1, align=align)
    pdf.cell(60, height, cells[2], border=1, new_x="LMARGIN", new_y="NEXT")


def _mark_scheme(path: Path) -> None:
    """Cover, a page of table holding two tables, then a page that is an image."""
    pdf = FPDF(unit="pt", format=(792, 612))
    pdf.set_font("Helvetica", size=10)
    pdf.set_auto_page_break(False)
    pdf.set_left_margin(56)
    pdf.add_page()
    pdf.text(100, 100, "Cambridge International A Level mark scheme, published.")
    pdf.line(100, 30, 500, 30)

    pdf.add_page()
    # Measured on 9709_w25_31: a rule hanging off the page is no table edge.
    pdf.line(-100, 10, 900, 10)
    # Measured on 9709_w25_31 too: nor is one on the page, above the table.
    pdf.line(20, 40, 780, 40)
    pdf.set_xy(56, 80)
    _table_row(pdf, ("Question", "Answer", "Marks"))
    _table_row(pdf, ("1(a)", "first answer", "2"))
    _table_row(pdf, ("1(b)", "second answer", "3"))
    pdf.set_xy(56, 300)
    _table_row(pdf, ("Question", "Answer", "Marks"))
    # A rule inside the header row, between its top edge and its text.
    pdf.line(116, 304, 700, 304)
    _table_row(pdf, ("2(b)", "third answer", "1"))
    pdf.text(56, 560, "Footer copyright line for this page")

    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="PNG")
    buffer.seek(0)
    pdf.add_page()
    pdf.image(buffer, x=0, y=0, w=792, h=612)
    pdf.output(str(path))


def test_labels_are_read_from_the_first_column(tmp_path):
    path = tmp_path / "ms.pdf"
    _mark_scheme(path)
    layout = read_ms_layout(str(path))
    read = [(c.number, c.page, c.first_part) for c in layout.candidates]
    assert read == [(1, 1, True), (1, 1, False), (2, 1, False)]


def test_a_label_opening_a_table_cuts_above_that_table_header(tmp_path):
    """Otherwise the question before ends on a stray Question/Answer/Marks row."""
    path = tmp_path / "ms.pdf"
    _mark_scheme(path)
    second = read_ms_layout(str(path)).candidates[2]
    assert second.y == pytest.approx(300, abs=2)


def test_page_kinds_and_first_content_page(tmp_path):
    path = tmp_path / "ms.pdf"
    _mark_scheme(path)
    layout = read_ms_layout(str(path))
    assert [a.is_image for a in layout.areas] == [False, False, True]
    assert layout.first_page == 1


def test_table_area_excludes_the_footer_and_side_margins(tmp_path):
    path = tmp_path / "ms.pdf"
    _mark_scheme(path)
    area = read_ms_layout(str(path)).areas[1]
    assert area.top == pytest.approx(80, abs=3)
    assert area.bottom == pytest.approx(348, abs=3)
    assert area.left == pytest.approx(56, abs=3)
    assert area.right == pytest.approx(736, abs=3)


def test_an_image_page_is_cut_to_where_the_text_pages_put_their_table(tmp_path):
    path = tmp_path / "ms.pdf"
    _mark_scheme(path)
    area = read_ms_layout(str(path)).areas[2]
    assert area.top == pytest.approx(80, abs=3)
    # Above the footer's text, wherever the table of a text page happened to end.
    assert 500 < area.bottom < 560
    assert area.left == pytest.approx(56, abs=3)


# ── The two calls the page makes ─────────────────────────────────


@pytest.fixture
def papers(tmp_path, monkeypatch):
    """A QP whose crops are faked — the segmenter has its own tests — and a real
    MS, with the cache redirected."""
    monkeypatch.setattr(type(app_settings), "question_cache_dir", property(
        lambda _self: tmp_path / "cache"
    ))
    qp = tmp_path / "9231_s25_qp_11.pdf"
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.set_font("Helvetica", size=10)
    pdf.add_page()
    pdf.text(72, 100, "1 First question")
    pdf.text(72, 300, "2 Second question")
    pdf.output(str(qp))
    ms = tmp_path / "9231_s25_ms_11.pdf"
    _mark_scheme(ms)

    calls = []

    def crops(paper_id, qp_path, wanted=None, *, trim=True):
        calls.append(paper_id)
        return [
            QuestionCrop(paper_id, "Q1", qp_path, [Band(0, 80, 200, 60, 500)]),
            QuestionCrop(paper_id, "Q2", qp_path, [Band(0, 280, 400, 60, 500)]),
            QuestionCrop(paper_id, "Q3", qp_path, []),
        ], []

    monkeypatch.setattr("modules.question_view.crops_for_paper", crops)
    return qp, ms, calls


def test_list_questions_leaves_out_a_question_with_nothing_to_show(papers):
    qp, ms, _ = papers
    result = list_questions(str(qp), str(ms))
    assert result.success
    assert result.questions == ["Q1", "Q2"]
    assert result.has_ms


def test_second_look_at_a_paper_reads_the_cache(papers):
    qp, ms, calls = papers
    list_questions(str(qp), str(ms))
    list_questions(str(qp), str(ms))
    assert len(calls) == 1


def test_a_cache_from_an_older_layout_is_not_trusted(papers, monkeypatch):
    qp, ms, calls = papers
    list_questions(str(qp), str(ms))
    newer = question_view._CACHE_VERSION + 1
    monkeypatch.setattr(question_view, "_CACHE_VERSION", newer)
    list_questions(str(qp), str(ms))
    assert len(calls) == 2


def test_a_paper_without_its_mark_scheme_yet_is_located_again_once_it_has_one(papers):
    qp, ms, calls = papers
    without = list_questions(str(qp), "")
    assert without.success
    assert not without.has_ms
    assert list_questions(str(qp), str(ms)).has_ms
    assert len(calls) == 2


def test_images_are_png_data_urls_for_both_sides(papers):
    qp, ms, _ = papers
    result = question_images(str(qp), str(ms), "Q1")
    assert result.success
    assert len(result.question) == 1
    assert result.question[0].startswith("data:image/png;base64,")
    assert len(result.mark_scheme) == 1
    assert result.mark_scheme[0].startswith("data:image/png;base64,")


def test_an_unknown_question_is_an_error_not_an_exception(papers):
    qp, ms, _ = papers
    result = question_images(str(qp), str(ms), "Q9")
    assert not result.success
    assert result.error


def test_multiple_choice_papers_are_refused(tmp_path, monkeypatch):
    """The segmenter cannot split them into their questions."""
    monkeypatch.setattr("modules.question_view.crops_for_paper", pytest.fail)
    result = list_questions(str(tmp_path / "9702_s25_qp_12.pdf"), "")
    assert not result.success
    assert result.error


def test_a_missing_file_is_an_error_not_an_exception(tmp_path):
    result = list_questions(str(tmp_path / "9231_s25_qp_11.pdf"), "")
    assert not result.success
    assert result.error


def test_blank_slices_are_dropped_from_the_images(papers, monkeypatch):
    qp, ms, _ = papers
    list_questions(str(qp), str(ms))
    monkeypatch.setattr(
        "modules.question_view._load_map",
        lambda *_a: {"Q1": question_view.QuestionClips(
            question=[PageClip(page_idx=0, y_top=500, y_bottom=600)],
            mark_scheme=[],
        )},
    )
    assert question_images(str(qp), str(ms), "Q1").question == []
