"""The answer sheet that goes with the 错题本's cropped question export.

The questions come out of the QP as vector crops (:mod:`mistake_pdf`); the
answers cannot. A mark scheme's answers live in a table that no amount of
geometry cuts reliably into per-question pieces — that is why the Mark tab
reads them with a vision model in the first place. So this typesets the
parse instead, straight out of the cache the Mark tab already filled.
Nothing here parses: a paper whose mark scheme has never been read is
reported, not re-read at the user's expense.

**Base-14 fonts, nothing embedded.** Helvetica for the text and Symbol for
the Greek and the operators — both are built into every PDF reader, so the
sheet needs no font file on disk and no font shipped in the app. That
matters twice over: ``[project.dependencies]`` has to stay pure Python for
``flet build ipa``, which rules out the obvious PDF-writing libraries (they
pull in Pillow), and a font resolved from the host would render differently
on a machine that hasn't got it.

Nothing here may import ``flet``/``app_flet`` — same rule as the rest of
``modules/marking``.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdfminer.fontmetrics import FONT_METRICS
from pypdf import PdfWriter
from pypdf.generic import (
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from modules.marking.mistake_pdf import (
    main_question_id,
    main_questions_by_paper,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from core.models import MistakeRecord
    from modules.marking.ms_parser import PaperConfig

_PAGE_W = 612.0
_PAGE_H = 792.0
_MARGIN = 48.0
_TEXT_W = _PAGE_W - 2 * _MARGIN

_PAPER_SIZE = 13.0
_HEAD_SIZE = 11.0
_BODY_SIZE = 9.5
_LEADING = 1.32          # of the size
_PARA_GAP = 5.0
_QUESTION_GAP = 10.0

_WIDTHS = {
    (False, False): FONT_METRICS["Helvetica"][1],
    (False, True): FONT_METRICS["Helvetica-Bold"][1],
    (True, False): FONT_METRICS["Symbol"][1],
    (True, True): FONT_METRICS["Symbol"][1],
}
_FALLBACK_WIDTH = 500.0

#: Adobe's Symbol encoding: the byte each glyph sits at. Only the glyphs the
#: mark schemes actually use — measured over the 202 questions cached on
#: this machine, which between them hold 41 characters Latin-1 cannot
#: encode. Written out rather than derived because pdfminer ships Symbol's
#: *widths* keyed by Unicode but not its code points.
_SYMBOL_BYTE: dict[str, int] = {
    # Greek, lower case then upper
    "α": 0x61, "β": 0x62, "γ": 0x67, "δ": 0x64,
    "ε": 0x65, "ζ": 0x7A, "η": 0x68, "θ": 0x71,
    "ι": 0x69, "κ": 0x6B, "λ": 0x6C, "ν": 0x6E,
    "ξ": 0x78, "ο": 0x6F, "π": 0x70, "ρ": 0x72,
    "σ": 0x73, "τ": 0x74, "υ": 0x75, "φ": 0x66,
    "χ": 0x63, "ψ": 0x79, "ω": 0x77,
    "Γ": 0x47, "Δ": 0x44, "Θ": 0x51, "Λ": 0x4C,
    "Ξ": 0x58, "Π": 0x50, "Σ": 0x53, "Φ": 0x46,
    "Ψ": 0x59, "Ω": 0x57,
    # Operators
    "√": 0xD6, "∫": 0xF2, "∞": 0xA5, "≠": 0xB9,
    "≤": 0xA3, "≥": 0xB3, "⇒": 0xDE, "→": 0xAE,
    "←": 0xAC, "≈": 0xBB, "∈": 0xCE, "∑": 0xE5,
    "∏": 0xD5, "∂": 0xB6, "∝": 0xB5, "∴": 0x5C,
    "∩": 0xC7, "∪": 0xC8, "≡": 0xBA,
}

#: Raised and lowered characters, mapped to what they say on the line. No
#: base-14 font has any of them, and the mark schemes already write the
#: ASCII form everywhere else ("9r^2", "6^k - 1").
#:
#: The letters are here even though the 202 questions cached on this machine
#: never used one — that set is only what happened to have been marked, and
#: "u₂ₙ is divisible by uₙ" is a sequences question written the ordinary
#: way. It turned up in the very first paper exported.
_SUPERSCRIPT: dict[str, str] = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")",
    "ⁿ": "n", "ⁱ": "i", "ᵃ": "a", "ᵇ": "b", "ᶜ": "c",
    "ᵈ": "d", "ᵉ": "e", "ᵏ": "k", "ᵐ": "m", "ᵖ": "p",
    "ʳ": "r", "ˢ": "s", "ᵗ": "t", "ˣ": "x", "ʸ": "y",
}
_SUBSCRIPT: dict[str, str] = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "₊": "+", "₋": "-", "₌": "=", "₍": "(", "₎": ")",
    "ₐ": "a", "ₑ": "e", "ₕ": "h", "ᵢ": "i", "ⱼ": "j",
    "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₒ": "o",
    "ₚ": "p", "ᵣ": "r", "ₛ": "s", "ₜ": "t", "ᵤ": "u",
    "ᵥ": "v", "ₓ": "x", "ᵦ": "beta", "ᵧ": "gamma",
    "ᵨ": "rho",
}

#: The rest of the rewrites — punctuation and marks, one for one.
_ASCII_MATHS: dict[str, str] = {
    "−": "-", "–": "-", "—": " - ",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "•": "- ", "✓": "[ok]", "✗": "[x]", " ": " ",
    "μ": "µ",
}

#: What a character becomes when neither font can draw it. Visible on
#: purpose: a silently dropped operator changes what an answer says.
_UNRENDERABLE = "?"

#: Symbol code point → the character it draws, for width lookup.
_SYMBOL_CHAR = {byte: char for char, byte in _SYMBOL_BYTE.items()}


def normalise(text: str) -> str:
    """Rewrite the notation both fonts lack into the ASCII the rest uses.

    Raised and lowered characters convert a *run* at a time, not one by
    one: "u₂ₙ" is u sub 2n, so it has to come out as ``u_(2n)``. Done per
    character it reads ``u_2_n``, which says something else — and ``u_2n``
    on its own is no better, since that parses as (u_2)n. A single
    character needs no brackets, so "x²" stays "x^2", the way the mark
    schemes already write it.
    """
    out: list[str] = []
    index = 0
    while index < len(text):
        for table, mark in ((_SUBSCRIPT, "_"), (_SUPERSCRIPT, "^")):
            if text[index] not in table:
                continue
            run = []
            while index < len(text) and text[index] in table:
                run.append(table[text[index]])
                index += 1
            body = "".join(run)
            out.append(mark + (body if len(body) == 1 else f"({body})"))
            break
        else:
            out.append(_ASCII_MATHS.get(text[index], text[index]))
            index += 1
    return "".join(out)


@dataclass(frozen=True)
class _Run:
    """A stretch of one line set in one font."""

    text: str
    symbol: bool
    bold: bool
    size: float

    @property
    def width(self) -> float:
        table = _WIDTHS[(self.symbol, self.bold)]
        chars = (
            [_SYMBOL_CHAR[ord(c)] for c in self.text]
            if self.symbol else list(self.text)
        )
        return self.size * sum(
            table.get(char, _FALLBACK_WIDTH) for char in chars
        ) / 1000.0


def _char_run(char: str, bold: bool, size: float) -> _Run:
    """One character as a run — Symbol if only Symbol has it."""
    if char in _SYMBOL_BYTE:
        return _Run(chr(_SYMBOL_BYTE[char]), True, bold, size)
    try:
        char.encode("latin-1")
    except UnicodeEncodeError:
        char = _UNRENDERABLE
    return _Run(char, False, bold, size)


def _merge(runs: Sequence[_Run]) -> list[_Run]:
    """Join neighbouring runs that share a font, so one Tj covers them."""
    out: list[_Run] = []
    for run in runs:
        if out and out[-1].symbol == run.symbol and out[-1].bold == run.bold:
            out[-1] = _Run(
                out[-1].text + run.text, run.symbol, run.bold, run.size
            )
        else:
            out.append(run)
    return out


def wrap(text: str, size: float, bold: bool, width: float) -> list[list[_Run]]:
    """Break *text* into lines of runs that each fit inside *width*.

    Wrapping happens on the source string, before the font split, so a word
    with a Greek letter in the middle is still one word. A word too long for
    the column is left to overhang rather than broken — mark schemes are
    full of long expressions, and hyphenating "3n^3-6n^2+n" would change
    what it says.
    """
    lines: list[list[_Run]] = []
    for paragraph in normalise(text).split("\n"):
        current: list[_Run] = []
        used = 0.0
        for word in paragraph.split(" "):
            piece = [_char_run(char, bold, size) for char in word]
            word_width = sum(run.width for run in piece)
            space = _char_run(" ", bold, size)
            if current and used + space.width + word_width > width:
                lines.append(_merge(current))
                current, used = [], 0.0
            if current:
                current.append(space)
                used += space.width
            current.extend(piece)
            used += word_width
        lines.append(_merge(current))
    return lines


def _escape(run: _Run) -> bytes:
    body = run.text.encode("latin-1", "replace")
    for old, new in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        body = body.replace(old, new)
    return body


class _Sheet:
    """Lines flowed down pages, then turned into PDF content streams."""

    def __init__(self) -> None:
        self.pages: list[list[tuple[float, list[_Run]]]] = []
        self._cursor = _PAGE_H

    def new_page(self) -> None:
        self.pages.append([])
        self._cursor = _MARGIN

    def _room(self, height: float) -> None:
        if not self.pages or self._cursor + height > _PAGE_H - _MARGIN:
            self.new_page()

    def block(self, text: str, size: float, bold: bool = False) -> None:
        leading = size * _LEADING
        for line in wrap(text, size, bold, _TEXT_W):
            self._room(leading)
            self.pages[-1].append((self._cursor + size, line))
            self._cursor += leading

    def gap(self, height: float) -> None:
        if self.pages:
            self._cursor += height

    def to_bytes(self) -> bytes:
        writer = PdfWriter()
        for lines in self.pages:
            page = writer.add_blank_page(width=_PAGE_W, height=_PAGE_H)
            page[NameObject("/Resources")] = _resources()
            raw = DecodedStreamObject()
            raw.set_data(_content(lines))
            # Wrapped rather than assigned straight: replace_contents wants
            # a ContentStream, and going through one also proves the
            # operators parse.
            page.replace_contents(ContentStream(raw, writer))
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()


def _resources() -> DictionaryObject:
    fonts = DictionaryObject()
    for key, base in (
        ("/F1", "/Helvetica"), ("/F2", "/Helvetica-Bold"), ("/F3", "/Symbol")
    ):
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject(base)
        if base != "/Symbol":
            # Symbol carries its own encoding; overriding it would turn the
            # Greek back into Latin letters.
            font[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
        fonts[NameObject(key)] = font
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    return resources


def _content(lines: Sequence[tuple[float, list[_Run]]]) -> bytes:
    """The page's content stream. y is measured down; PDF measures up."""
    out = bytearray()
    for baseline, runs in lines:
        if not runs:
            continue
        out += b"BT %.2f %.2f Td" % (_MARGIN, _PAGE_H - baseline)
        for run in runs:
            key = b"/F3" if run.symbol else (b"/F2" if run.bold else b"/F1")
            out += b" %s %.2f Tf (%s) Tj" % (key, run.size, _escape(run))
        out += b" ET\n"
    return bytes(out)


def build_answer_sheet(
    records: Iterable[MistakeRecord],
    ms_path_of: Mapping[str, str],
) -> tuple[bytes, list[str]]:
    """Typeset the mark schemes for the questions being exported.

    Args:
        records: the selected mistakes — the same selection the question
            export is built from.
        ms_path_of: paper_id → mark scheme PDF path. Only the file's *stem*
            matters, because that is the cache key; the PDF itself need not
            still be on disk.

    Returns:
        The PDF bytes, and human-readable warnings for what is missing — a
        paper whose mark scheme was never parsed, a question the parse
        doesn't cover. Warnings rather than exceptions: nine answers out of
        ten are worth handing over as long as the tenth is named.

    Raises:
        ValueError: nothing at all could be written.
    """
    from modules.marking.ms_parser import cached_mark_scheme

    items = list(records)
    scored = {
        (record.paper_id, record.question_id): record for record in items
    }
    warnings: list[str] = []
    sheet = _Sheet()
    written = 0

    for paper_id, mains in main_questions_by_paper(items).items():
        config = cached_mark_scheme(ms_path_of.get(paper_id, paper_id))
        if config is None:
            warnings.append(f"{paper_id}: 还没解析过 mark scheme，已跳过")
            continue

        sheet.new_page()
        sheet.block(paper_id, _PAPER_SIZE, bold=True)
        sheet.gap(_PARA_GAP)

        for main in mains:
            ids = [
                qid for qid in config.questions
                if main_question_id(qid) == main
            ]
            if not ids:
                warnings.append(f"{paper_id}: mark scheme 里没有 {main}")
                continue
            _write_question(sheet, paper_id, main, ids, config, scored)
            written += 1

    if not written:
        raise ValueError("没有可导出的答案")

    return sheet.to_bytes(), warnings


def _write_question(
    sheet: _Sheet,
    paper_id: str,
    main: str,
    ids: Sequence[str],
    config: PaperConfig,
    scored: Mapping[tuple[str, str], MistakeRecord],
) -> None:
    """One main question: a heading, then every part's mark scheme.

    Every part, not only the ones marks were lost on — a sub-question read
    without its siblings usually makes no sense. The ones that *were* lost
    carry the score, so they can be picked out at a glance.
    """
    total = sum(config.questions[qid].max_marks for qid in ids)
    sheet.block(f"{main}   [{total}]", _HEAD_SIZE, bold=True)

    for qid in ids:
        entry = config.questions[qid]
        record = scored.get((paper_id, qid))
        # Latin-1 only: the base-14 fonts this sheet is set in have no CJK
        # glyphs, so a Chinese label would come out as question marks.
        got = (
            f"   scored {record.score:g}/{record.max_score:g}"
            if record is not None else ""
        )
        sheet.block(f"{qid}  [{entry.max_marks}]{got}", _BODY_SIZE, bold=True)
        sheet.block(entry.mark_scheme, _BODY_SIZE)
        sheet.gap(_PARA_GAP)

    sheet.gap(_QUESTION_GAP)


def ms_paths_by_paper(
    records: Iterable[MistakeRecord],
    ms_path_of: Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Split the papers into those with a parsed mark scheme and those not.

    Lets the UI say which papers the answer sheet will be missing *before*
    the file dialog opens, rather than after.
    """
    from modules.marking.ms_parser import cached_mark_scheme

    found: dict[str, str] = {}
    missing: list[str] = []
    for paper_id in main_questions_by_paper(records):
        path = ms_path_of.get(paper_id, "")
        if path and cached_mark_scheme(path) is not None:
            found[paper_id] = path
        else:
            missing.append(paper_id)
    return found, missing
