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
matters twice over: the obvious PDF-writing libraries pull in Pillow, whose
vendored dylibs break the universal macOS build (see ``pyproject.toml``), and
a font resolved from the host would render differently on a machine that
hasn't got it.

Nothing here may import ``flet``/``app_flet`` — same rule as the rest of
``modules/marking``.
"""
from __future__ import annotations

import io
import re
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

#: Raised and lowered characters, mapped to the character they say. They
#: are not rewritten into "^2" any more — they are *set* raised or lowered
#: (see :func:`atoms`), which is the whole point of this module's layout.
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
    "ᵥ": "v", "ₓ": "x", "ᵦ": "β", "ᵧ": "γ", "ᵨ": "ρ",
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

# ── Maths layout ──────────────────────────────────────────────────
#
# The mark schemes come out of the vision model as flat ASCII maths —
# "½ ∫_0^2π θ^2 e^(¼θ) dθ". Printed flat it is close to unreadable, so the
# "^" and "_" are turned back into what they mean: a smaller run of type,
# raised or lowered. Nothing here is LaTeX, because the source is not
# LaTeX — measured over the 202 cached questions, it contains exactly zero
# backslash commands.

#: Each level of nesting shrinks the type by this much, TeX-style.
_SCRIPT_SCALE = 0.72
#: …down to this share of the base size, so a doubly-nested exponent stays
#: legible rather than shrinking to a dot.
_MIN_SCALE = 0.5
#: How far a superscript rises and a subscript drops, as a share of the
#: size they are attached to.
_SUP_RISE = 0.42
_SUB_RISE = -0.20

#: What "^" and "_" take when the operand is not bracketed. Measured over
#: the cached mark schemes: a single digit 39 times, a signed number 12,
#: a single letter 6, a two-digit number 2. The trailing Greek letter is
#: for limits like "∫_0^2π", where the whole "2π" is the limit — a digit
#: followed by a Greek letter is a coefficient and its constant, never two
#: separate things.
_BARE_OPERAND = re.compile("[+-]?\\d+[Ͱ-Ͽ]?")


@dataclass(frozen=True)
class _Atom:
    """One character, at the size and height its nesting gives it."""

    char: str
    size: float
    rise: float
    #: A space at the base level, i.e. somewhere a line may be broken.
    breaks: bool = False


def _operand(text: str, index: int) -> tuple[str, int]:
    """What "^" or "_" at *index*-1 applies to, and how much it consumed.

    A bracketed group loses its brackets: "e^(¼θ)" means e to the ¼θ, and
    once the ¼θ is actually raised the brackets say nothing — printing them
    is what made these lines look like code.
    """
    char = text[index]
    if char in "({":
        closing = ")" if char == "(" else "}"
        depth = 0
        for position in range(index, len(text)):
            if text[position] == char:
                depth += 1
            elif text[position] == closing:
                depth -= 1
                if depth == 0:
                    return text[index + 1:position], position - index + 1
        return text[index + 1:], len(text) - index   # unbalanced: take it all
    bare = _BARE_OPERAND.match(text, index)
    if bare:
        return bare.group(0), len(bare.group(0))
    return char, 1


def atoms(
    text: str,
    size: float,
    rise: float = 0.0,
    base: float | None = None,
    *,
    math: bool = True,
) -> list[_Atom]:
    """Lay a line of the mark scheme's maths out into positioned characters.

    Recursive, so "e^(x^2)" nests properly. *base* is the size of the line
    this belongs to, and it is what the shrinking floor is measured against
    — floored against the *parent* instead, every level shrinks by the same
    ratio and the floor never binds at all (four levels down reached 2.7pt
    on a 10pt line).

    *math* off treats "^" and "_" as the characters they are. Headings need
    that: a paper id is "9231_s25_qp_11", and read as maths it comes out as
    9231 with a subscript s, then 25, then a subscript q — which is exactly
    how the first interleaved export printed it.
    """
    base = size if base is None else base
    step = max(size * _SCRIPT_SCALE, base * _MIN_SCALE)
    out: list[_Atom] = []
    index = 0
    while index < len(text):
        char = text[index]

        if math and char in "^_" and index + 1 < len(text):
            body, used = _operand(text, index + 1)
            out.extend(atoms(
                body, step,
                rise + size * (_SUP_RISE if char == "^" else _SUB_RISE),
                base, math=math,
            ))
            index += 1 + used
            continue

        for table, direction in (
            (_SUPERSCRIPT, _SUP_RISE), (_SUBSCRIPT, _SUB_RISE)
        ):
            if char not in table:
                continue
            body = ""
            while index < len(text) and text[index] in table:
                body += table[text[index]]
                index += 1
            out.extend(atoms(
                body, step, rise + size * direction, base, math=math,
            ))
            break
        else:
            for plain in _ASCII_MATHS.get(char, char):
                out.append(_Atom(
                    plain, size, rise, breaks=plain == " " and rise == 0.0
                ))
            index += 1
    return out


@dataclass(frozen=True)
class _Run:
    """A stretch of one line set in one font at one height."""

    text: str
    symbol: bool
    bold: bool
    size: float
    rise: float = 0.0

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


def _run_for(atom: _Atom, bold: bool) -> _Run:
    """One atom as a run — Symbol if only Symbol has its character."""
    if atom.char in _SYMBOL_BYTE:
        return _Run(
            chr(_SYMBOL_BYTE[atom.char]), True, bold, atom.size, atom.rise
        )
    char = atom.char
    try:
        char.encode("latin-1")
    except UnicodeEncodeError:
        char = _UNRENDERABLE
    return _Run(char, False, bold, atom.size, atom.rise)


def _merge(runs: Sequence[_Run]) -> list[_Run]:
    """Join neighbouring runs that match, so one Tj covers them."""
    out: list[_Run] = []
    for run in runs:
        last = out[-1] if out else None
        if (
            last is not None
            and (last.symbol, last.bold, last.size, last.rise)
            == (run.symbol, run.bold, run.size, run.rise)
        ):
            out[-1] = _Run(
                last.text + run.text, run.symbol, run.bold, run.size, run.rise
            )
        else:
            out.append(run)
    return out


def wrap(
    text: str, size: float, bold: bool, width: float, *, math: bool = True
) -> list[list[_Run]]:
    """Break *text* into lines of runs that each fit inside *width*.

    Wrapping happens on the laid-out atoms rather than the source string,
    so an exponent never gets separated from what it is an exponent of. A
    word too long for the column is left to overhang rather than broken —
    mark schemes are full of long expressions, and hyphenating
    "3n^3-6n^2+n" would change what it says.
    """
    lines: list[list[_Run]] = []
    for paragraph in text.splitlines() or [""]:
        words: list[list[_Atom]] = [[]]
        for atom in atoms(paragraph, size, math=math):
            if atom.breaks:
                words.append([])
            else:
                words[-1].append(atom)

        current: list[_Run] = []
        used = 0.0
        space = _Run(" ", False, bold, size)
        for word in words:
            piece = [_run_for(atom, bold) for atom in word]
            word_width = sum(run.width for run in piece)
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


def line_height(runs: Sequence[_Run], size: float) -> float:
    """How much room a line needs, given how far its scripts reach.

    A line of plain text gets the plain leading; one carrying a superscript
    and a subscript needs the span between them on top, or the raised
    characters collide with the line above.
    """
    if not runs:
        return size * _LEADING
    rises = [run.rise for run in runs]
    return size * _LEADING + (max(rises) - min(rises)) * 0.5


def _escape(run: _Run) -> bytes:
    body = run.text.encode("latin-1", "replace")
    for old, new in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        body = body.replace(old, new)
    return body


class _Sheet:
    """Lines flowed down pages, then turned into PDF content streams.

    The page size is a parameter because these pages get interleaved with
    pages cropped out of a question paper, and two of the papers on disk are
    A4 rather than letter — a document that changes size halfway prints
    badly.
    """

    def __init__(
        self, width: float = _PAGE_W, height: float = _PAGE_H
    ) -> None:
        self.width = width
        self.height = height
        self.text_width = width - 2 * _MARGIN
        self.pages: list[list[tuple[float, list[_Run]]]] = []
        self._cursor = height

    def new_page(self) -> None:
        self.pages.append([])
        self._cursor = _MARGIN

    def _room(self, height: float) -> None:
        if not self.pages or self._cursor + height > self.height - _MARGIN:
            self.new_page()

    def block(
        self, text: str, size: float, bold: bool = False, math: bool = True
    ) -> None:
        for line in wrap(text, size, bold, self.text_width, math=math):
            leading = line_height(line, size)
            self._room(leading)
            self.pages[-1].append((self._cursor + size, line))
            self._cursor += leading

    def gap(self, height: float) -> None:
        if self.pages:
            self._cursor += height

    def to_bytes(self) -> bytes:
        writer = PdfWriter()
        for lines in self.pages:
            page = writer.add_blank_page(width=self.width, height=self.height)
            page[NameObject("/Resources")] = _resources()
            raw = DecodedStreamObject()
            raw.set_data(_content(lines, self.height))
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


def _content(
    lines: Sequence[tuple[float, list[_Run]]], page_height: float = _PAGE_H
) -> bytes:
    """The page's content stream. y is measured down; PDF measures up."""
    out = bytearray()
    for baseline, runs in lines:
        if not runs:
            continue
        out += b"BT %.2f %.2f Td" % (_MARGIN, page_height - baseline)
        for run in runs:
            key = b"/F3" if run.symbol else (b"/F2" if run.bold else b"/F1")
            # Ts is the text rise — how a superscript gets set above the
            # baseline without moving the pen, so Tj keeps advancing the
            # line normally afterwards.
            out += b" %s %.2f Tf %.2f Ts (%s) Tj" % (
                key, run.size, run.rise, _escape(run)
            )
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
    warnings: list[str] = []
    sheet = _Sheet()
    written = 0

    for paper_id, mains in main_questions_by_paper(items).items():
        config = cached_mark_scheme(ms_path_of.get(paper_id, ""))
        if config is None:
            warnings.append(f"{paper_id}: 还没解析过 mark scheme，已跳过")
            continue

        sheet.new_page()
        sheet.block(paper_id, _PAPER_SIZE, bold=True, math=False)
        sheet.gap(_PARA_GAP)

        for main in mains:
            ids = [
                qid for qid in config.questions
                if main_question_id(qid) == main
            ]
            if not ids:
                warnings.append(f"{paper_id}: mark scheme 里没有 {main}")
                continue
            _write_question(sheet, main, ids, config)
            written += 1

    if not written:
        raise ValueError("没有可导出的答案")

    return sheet.to_bytes(), warnings


def answer_pages(
    paper_id: str,
    question_id: str,
    ms_path: str,
    width: float = _PAGE_W,
    height: float = _PAGE_H,
) -> bytes | None:
    """One main question's mark scheme, as its own page(s), or None.

    This is what goes on the page *after* the question in the interleaved
    export, so it opens with the paper and question it answers — a sheet
    that is going to be flipped past needs to say what it belongs to.

    None when the paper has never been parsed or the parse doesn't cover
    this question; the caller turns that into a warning rather than a gap.
    """
    from modules.marking.ms_parser import cached_mark_scheme

    config = cached_mark_scheme(ms_path)
    if config is None:
        return None
    main = main_question_id(question_id)
    ids = [qid for qid in config.questions if main_question_id(qid) == main]
    if not ids:
        return None

    sheet = _Sheet(width, height)
    sheet.new_page()
    # Latin-1 only: the base-14 fonts this is set in have no CJK glyphs, so
    # a Chinese heading would come out as a row of question marks.
    sheet.block(
        f"{paper_id}   mark scheme", _PAPER_SIZE, bold=True, math=False,
    )
    sheet.gap(_PARA_GAP)
    _write_question(sheet, main, ids, config)
    return sheet.to_bytes()


def _write_question(
    sheet: _Sheet,
    main: str,
    ids: Sequence[str],
    config: PaperConfig,
) -> None:
    """One main question: a heading, then every part's mark scheme.

    Every part, not only the ones marks were lost on — a sub-question read
    without its siblings usually makes no sense. No first-attempt score
    either: this sheet is the answer to redo against, and the old marks
    belong in the 错题本, not on it.
    """
    total = sum(config.questions[qid].max_marks for qid in ids)
    sheet.block(f"{main}   [{total}]", _HEAD_SIZE, bold=True)

    for qid in ids:
        entry = config.questions[qid]
        sheet.block(f"{qid}  [{entry.max_marks}]", _BODY_SIZE, bold=True)
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
