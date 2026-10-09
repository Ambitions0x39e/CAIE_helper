"""The answer sheet that goes with the 错题本's cropped question export.

The questions come out of the QP as vector crops (:mod:`modules.question_pdf`); the
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

Nothing here may import ``app_web`` — same rule as the rest of
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

from modules.question_pdf import (
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
#: mark schemes actually use — measured over the 216 questions cached on
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
    # The vulgar fractions and radicals Latin-1 has no glyph for. ½ ¼ ¾ it
    # has, and one glyph reads better there than three characters do.
    "⅓": "1/3", "⅔": "2/3", "∛": "³√",
}

#: What a character becomes when neither font can draw it. Visible on
#: purpose: a silently dropped operator changes what an answer says.
#:
#: Control characters go the same way, and that is the net under the
#: notation. A backslash written single instead of double is a JSON escape
#: — "\f" a form feed, "\t" a tab, "\b" a backspace — so "\frac" and
#: "\theta", the two commonest commands in maths, decode to a control
#: character and a stump of a word without anything raising. Drawn, a tab
#: is nothing at all; drawn as "?", it is a question somebody can ask.
_UNRENDERABLE = "?"

#: What counts as the end of a line: a line break, or LaTeX's name for one.
#: Narrower than ``str.splitlines()``, which also breaks on a form feed —
#: and a form feed is exactly what a single-written "\frac" leaves behind.
_NEWLINE = re.compile("\r\n|[\r\n]|\\\\newline")

#: Symbol code point → the character it draws, for width lookup.
_SYMBOL_CHAR = {byte: char for char, byte in _SYMBOL_BYTE.items()}

# ── Maths layout ──────────────────────────────────────────────────
#
# Three notations arrive mixed, often inside one line: flat ASCII maths
# ("∑x^2"), Unicode scripts ("H₀", "x²") and LaTeX ("\frac{9s_x^2}{7}").
# All three are set as what they mean — "^" and "_" become a smaller run
# of type raised or lowered, "\frac" becomes a stacked box. The mix is
# permanent, not a migration: a cache parsed months ago does not rewrite
# itself, and the model's notation drifts between papers anyway.

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

#: Where a fraction's parts sit, as shares of the size of the line they
#: are set on: the rule's height above the baseline, then the numerator's
#: and denominator's own baselines. The two are far enough from the rule
#: to clear a script of their own — "\frac{9s_x^2 + 7s_y^2}{10 + 8 - 2}"
#: is an ordinary line in these mark schemes, and its subscripts hang
#: below the numerator's baseline.
_FRAC_BAR = 0.28
_FRAC_RISE = 0.55
_FRAC_DROP = 0.50
#: Breathing room either side of the rule, and how thick the rule is.
_FRAC_PAD = 0.10
_RULE = 0.05
#: How far a capital reaches above its baseline, as a share of its size.
#: Helvetica's, rounded up — it is what decides whether a line clears the
#: one above it.
_CAP_HEIGHT = 0.72

#: LaTeX commands that stand for a single character. The character then
#: goes through the same font split as any other, so the Greek lands in
#: Symbol and "\times" in Helvetica.
_LATEX_CHAR: dict[str, str] = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "omicron": "ο", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ",
    "Psi": "Ψ", "Omega": "Ω",
    "int": "∫", "sum": "∑", "prod": "∏", "partial": "∂",
    "infty": "∞", "propto": "∝", "surd": "√", "therefore": "∴",
    "neq": "≠", "ne": "≠", "leq": "≤", "le": "≤",
    "geq": "≥", "ge": "≥", "approx": "≈", "equiv": "≡",
    "in": "∈", "cap": "∩", "cup": "∪",
    "Rightarrow": "⇒", "implies": "⇒", "to": "→", "rightarrow": "→",
    "leftarrow": "←", "gets": "←",
    "times": "×", "cdot": "·", "div": "÷", "pm": "±",
    "circ": "°", "degree": "°", "sim": "~",
    # A radical's unpaired electron, "Cl\bullet". Not "•": that is
    # rewritten to a list dash, and "Cl- " reads as the chloride ion.
    "bullet": "·",
    "ldots": "...", "dots": "...", "cdots": "...",
    # The escapes, where the character is the command's whole name.
    "{": "{", "}": "}", "%": "%", "&": "&", "#": "#",
    "$": "$", "_": "_", "^": "^",
}

#: Spacing commands, and how many spaces each is worth. "\\" is a line
#: break to TeX, but a line here has already been cut out of its paragraph
#: by the time a command is read, so it can only be a gap.
_LATEX_SPACE: dict[str, int] = {
    "quad": 2, "qquad": 4, ",": 1, ":": 1, ";": 1, " ": 1, "!": 0, "\\": 1,
}

#: Commands whose braced argument is set as ordinary text.
_LATEX_TEXT = frozenset({"text", "textbf", "textit", "mathrm", "mathbf",
                         "mathit", "operatorname", "mbox"})

#: Operator names, which TeX sets upright and apart from what follows.
_LATEX_OPERATOR = frozenset({
    "sin", "cos", "tan", "sec", "csc", "cot",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "ln", "log", "exp", "lim", "max", "min", "det",
})

#: Commands that only size a delimiter. The delimiter itself is printed
#: by the ordinary path; "\left." and "\right." name no delimiter at all.
_LATEX_SIZER = frozenset({"left", "right", "big", "Big", "bigg", "Bigg"})

#: The brackets each matrix environment is drawn with.
_MATRIX_FENCE = {"pmatrix": "()", "bmatrix": "[]", "vmatrix": "||",
                 "Vmatrix": "||"}


def _flat_matrix(env: str, body: str) -> str:
    """A LaTeX matrix written flat on one line.

    Cells take commas and rows take semicolons — "(cos θ, -sin θ; sin θ,
    cos θ)" — because a cell is often a whole expression, and with only a
    space between cells nothing says where one ends. A single column is a
    column vector and reads "(3, 2, -1)", the way the mark schemes write
    one.
    """
    rows = [
        [cell.strip() for cell in row.split("&")]
        for row in body.split("\\\\") if row.strip()
    ]
    inner = (
        ", ".join(row[0] for row in rows)
        if all(len(row) == 1 for row in rows)
        else "; ".join(", ".join(row) for row in rows)
    )
    fence = _MATRIX_FENCE.get(env, "  ")
    return f"{fence[0]}{inner}{fence[1]}".strip()

_LATEX_NAME = re.compile("[A-Za-z]+")

#: A radicand that needs no brackets around it: "\sqrt{33}" is √33, but
#: "\sqrt{2x}" written √2x reads as √2 times x, which is a different
#: number. Brackets are printed rather than a bar drawn over the radicand.
_SIMPLE_RADICAND = re.compile("[A-Za-z]|[0-9]+")


@dataclass(frozen=True)
class _Atom:
    """One character, at the size and height its nesting gives it."""

    char: str
    size: float
    rise: float
    #: A space at the base level, i.e. somewhere a line may be broken.
    breaks: bool = False


@dataclass(frozen=True)
class _Frac:
    """A fraction: two laid-out rows that will be stacked and ruled.

    *size* is the size of the line it sits on rather than of its own type,
    because that is what the geometry above is measured in; the rows are
    already at the shrunken size by the time they get here.
    """

    top: list[_Piece]
    bottom: list[_Piece]
    size: float
    rise: float
    #: A fraction is never a place to break a line.
    breaks: bool = False


_Piece = _Atom | _Frac


def _delimited(
    text: str, index: int, opening: str, closing: str
) -> tuple[str, int]:
    """What is inside the bracket at *index*, and how much it consumed."""
    depth = 0
    for position in range(index, len(text)):
        if text[position] == opening:
            depth += 1
        elif text[position] == closing:
            depth -= 1
            if depth == 0:
                return text[index + 1:position], position - index + 1
    return text[index + 1:], len(text) - index   # unbalanced: take it all


def _operand(text: str, index: int) -> tuple[str, int]:
    """What "^" or "_" at *index*-1 applies to, and how much it consumed.

    A bracketed group loses its brackets: "e^(¼θ)" means e to the ¼θ, and
    once the ¼θ is actually raised the brackets say nothing — printing them
    is what made these lines look like code.
    """
    char = text[index]
    if char in "({":
        return _delimited(text, index, char, ")" if char == "(" else "}")
    if char == "\\":
        # "36.7^\circ" is raised as a whole; taken a character at a time it
        # was a raised backslash and the word "circ" on the baseline.
        name = _LATEX_NAME.match(text, index + 1)
        length = 1 + (len(name.group(0)) if name else 1)
        return text[index:index + length], length
    bare = _BARE_OPERAND.match(text, index)
    if bare:
        return bare.group(0), len(bare.group(0))
    return char, 1


def _argument(text: str, index: int) -> tuple[str, int]:
    """A command's argument: a braced group, or the next character alone.

    A brace only groups when a command or a script reaches for it. One met
    while scanning is a brace the mark scheme meant — a piecewise
    definition is written "F(x) = { 0 (x<0); 3/17 x² (0≤x<1); … }", and
    swallowing those would take the shape of the answer with them.
    """
    if text[index:index + 1] == "{":
        return _delimited(text, index, "{", "}")
    return (text[index], 1) if index < len(text) else ("", 0)


def _command(
    text: str, index: int, size: float, rise: float, base: float, step: float
) -> tuple[list[_Piece], int]:
    """The LaTeX command starting at the backslash *index* points at.

    Returns what it draws and how much of *text* it ate. A command nobody
    here knows becomes "?" and its argument is left to print: silently
    dropping half an expression is how a mark scheme comes to say
    something it does not say.
    """
    name_match = _LATEX_NAME.match(text, index + 1)
    name = name_match.group(0) if name_match else text[index + 1:index + 2]
    after = index + 1 + len(name)

    def whole(pieces: list[_Piece], used: int) -> tuple[list[_Piece], int]:
        return pieces, after - index + used

    if name in _LATEX_CHAR:
        return whole(
            atoms(_LATEX_CHAR[name], size, rise, base, math=False), 0
        )
    if name in _LATEX_OPERATOR:
        # "2\sin\theta" is "2 sin θ": the spaces TeX puts there by itself.
        following = text[after:after + 1]
        lead = " " if index and text[index - 1].isalnum() else ""
        trail = " " if following.isalpha() or following == "\\" else ""
        return whole(
            atoms(lead + name + trail, size, rise, base, math=False), 0
        )
    if name == "begin":
        env, used_env = _argument(text, after)
        start = after + used_env
        end = text.find(f"\\end{{{env}}}", start)
        stop = len(text) if end == -1 else end + len(f"\\end{{{env}}}")
        body = text[start:len(text) if end == -1 else end]
        return whole(
            atoms(_flat_matrix(env, body), size, rise, base), stop - after
        )
    if name == "end":   # one with no "\begin" before it
        return whole([], _argument(text, after)[1])
    if name in ("overrightarrow", "vec"):
        body, used = _argument(text, after)
        return whole(atoms(f"{body}^→", size, rise, base), used)
    if name == "overset":
        # Stacked in the source, raised here: "\overset{a}{b}" is b with a
        # above it, and a superscript is the nearest thing a single line of
        # type has to "above".
        over, used_over = _argument(text, after)
        under, used_under = _argument(text, after + used_over)
        return whole(
            atoms(under, size, rise, base)
            + atoms(over, step, rise + size * _SUP_RISE, base),
            used_over + used_under,
        )
    if name in _LATEX_SPACE:
        return whole(atoms(" " * _LATEX_SPACE[name], size, rise, base), 0)
    if name in _LATEX_SIZER:
        # "\left." and "\right." size nothing and name no delimiter.
        return whole([], 1 if text[after:after + 1] == "." else 0)
    if name in _LATEX_TEXT:
        body, used = _argument(text, after)
        return whole(atoms(body, size, rise, base, math=False), used)
    if name in ("frac", "dfrac", "tfrac"):
        top, used_top = _argument(text, after)
        bottom, used_bottom = _argument(text, after + used_top)
        return whole([_Frac(
            atoms(top, step, 0.0, base),
            atoms(bottom, step, 0.0, base),
            size, rise,
        )], used_top + used_bottom)
    if name == "sqrt":
        degree, used_degree = (
            _delimited(text, after, "[", "]")
            if text[after:after + 1] == "[" else ("", 0)
        )
        body, used = _argument(text, after + used_degree)
        if not _SIMPLE_RADICAND.fullmatch(body):
            body = f"({body})"
        return whole(
            atoms(f"^{{{degree}}}√{body}" if degree else f"√{body}",
                  size, rise, base),
            used_degree + used,
        )
    return whole([_Atom(_UNRENDERABLE, size, rise)], 0)


def atoms(
    text: str,
    size: float,
    rise: float = 0.0,
    base: float | None = None,
    *,
    math: bool = True,
) -> list[_Piece]:
    """Lay a line of the mark scheme's maths out into positioned characters.

    Recursive, so "e^(x^2)" nests properly. *base* is the size of the line
    this belongs to, and it is what the shrinking floor is measured against
    — floored against the *parent* instead, every level shrinks by the same
    ratio and the floor never binds at all (four levels down reached 2.7pt
    on a 10pt line).

    *math* off treats "^" and "_" as the characters they are. Headings need
    that: a paper id is "9231_s25_qp_11", and read as maths it comes out as
    9231 with a subscript s, then 25, then a subscript q — which is exactly
    how an early answer sheet printed it.
    """
    base = size if base is None else base
    step = max(size * _SCRIPT_SCALE, base * _MIN_SCALE)
    out: list[_Piece] = []
    index = 0
    while index < len(text):
        char = text[index]

        if math and char == "\\" and index + 1 < len(text):
            drawn, used = _command(text, index, size, rise, base, step)
            out.extend(drawn)
            index += used
            continue

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


@dataclass(frozen=True)
class _Stack:
    """A fraction as it gets drawn: two rows and the rule between them.

    Its own width is the wider row's, so the shorter one centres over the
    other — and the rule is drawn, not set, because none of the base-14
    fonts carries a rule that stretches.
    """

    top: list[_Piece2]
    bottom: list[_Piece2]
    size: float
    rise: float = 0.0

    @property
    def width(self) -> float:
        return max(_width(self.top), _width(self.bottom)) + (
            2 * self.size * _FRAC_PAD
        )

    @property
    def span(self) -> tuple[float, float]:
        """How far the box reaches above and below the line's baseline.

        Measured through the rows, not just to their baselines: a fraction
        inside a denominator is what actually reaches furthest down, and a
        box that under-reports its own height is one the next line is set
        on top of.
        """
        high = self.rise + self.size * _FRAC_RISE
        low = self.rise - self.size * _FRAC_DROP
        for row, baseline in ((self.top, high), (self.bottom, low)):
            for run in row:
                reach = run.span if isinstance(run, _Stack) else (
                    run.rise, run.rise
                )
                high = max(high, baseline + reach[0])
                low = min(low, baseline + reach[1])
        return high, low


_Piece2 = _Run | _Stack


def _width(runs: Sequence[_Piece2]) -> float:
    return sum(run.width for run in runs)


def _run_for(piece: _Piece, bold: bool) -> _Piece2:
    """One laid-out piece as something drawable.

    Symbol when only Symbol has the character, a stacked box for a
    fraction, Helvetica otherwise.
    """
    if isinstance(piece, _Frac):
        return _Stack(
            _merge([_run_for(part, bold) for part in piece.top]),
            _merge([_run_for(part, bold) for part in piece.bottom]),
            piece.size, piece.rise,
        )
    if piece.char in _SYMBOL_BYTE:
        return _Run(
            chr(_SYMBOL_BYTE[piece.char]), True, bold, piece.size, piece.rise
        )
    char = piece.char
    try:
        char.encode("latin-1")
    except UnicodeEncodeError:
        char = _UNRENDERABLE
    if char < " ":
        char = _UNRENDERABLE
    return _Run(char, False, bold, piece.size, piece.rise)


def _merge(runs: Sequence[_Piece2]) -> list[_Piece2]:
    """Join neighbouring runs that match, so one Tj covers them."""
    out: list[_Piece2] = []
    for run in runs:
        last = out[-1] if out else None
        if (
            isinstance(last, _Run) and isinstance(run, _Run)
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
) -> list[list[_Piece2]]:
    """Break *text* into lines of runs that each fit inside *width*.

    Wrapping happens on the laid-out atoms rather than the source string,
    so an exponent never gets separated from what it is an exponent of. A
    word too long for the column is left to overhang rather than broken —
    mark schemes are full of long expressions, and hyphenating
    "3n^3-6n^2+n" would change what it says.
    """
    lines: list[list[_Piece2]] = []
    for paragraph in _NEWLINE.split(text):
        words: list[list[_Piece]] = [[]]
        for atom in atoms(paragraph, size, math=math):
            if atom.breaks:
                words.append([])
            else:
                words[-1].append(atom)

        current: list[_Piece2] = []
        used = 0.0
        space = _Run(" ", False, bold, size)
        for word in words:
            piece = [_run_for(atom, bold) for atom in word]
            word_width = _width(piece)
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


def ascent(runs: Sequence[_Piece2], size: float) -> float:
    """How far above its own baseline a line reaches.

    A line is normally set one *size* below the last one, which is room
    enough for anything Helvetica draws and for a superscript. A fraction
    is taller than that, so it needs measuring or it prints over the line
    above — the extra leading :func:`line_height` asks for all lands
    *below* the baseline, and does nothing for what is above it.
    """
    reach = 0.0
    for run in runs:
        high = run.span[0] if isinstance(run, _Stack) else run.rise
        reach = max(reach, high + run.size * _CAP_HEIGHT)
    return max(reach, size)


def line_height(runs: Sequence[_Piece2], size: float) -> float:
    """How much room a line needs, given how far its scripts reach.

    A line of plain text gets the plain leading; one carrying a superscript
    and a subscript needs the span between them on top, or the raised
    characters collide with the line above. A fraction reports the box it
    occupies rather than a single height, which is most of what makes a
    line of them sit clear of its neighbours.
    """
    if not runs:
        return size * _LEADING
    rises: list[float] = []
    for run in runs:
        rises.extend(run.span if isinstance(run, _Stack) else [run.rise])
    return size * _LEADING + (max(rises) - min(rises)) * 0.5


def _escape(run: _Run) -> bytes:
    body = run.text.encode("latin-1", "replace")
    for old, new in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        body = body.replace(old, new)
    return body


class _Sheet:
    """Lines flowed down pages, then turned into PDF content streams."""

    def __init__(
        self, width: float = _PAGE_W, height: float = _PAGE_H
    ) -> None:
        self.width = width
        self.height = height
        self.text_width = width - 2 * _MARGIN
        self.pages: list[list[tuple[float, list[_Piece2]]]] = []
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
            top = ascent(line, size)
            leading = line_height(line, size) + top - size
            self._room(leading)
            self.pages[-1].append((self._cursor + top, line))
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


def _show(x: float, y: float, runs: Sequence[_Run]) -> bytes:
    """A stretch of runs set left to right from (*x*, *y*)."""
    if not runs:
        return b""
    out = bytearray(b"BT %.2f %.2f Td" % (x, y))
    for run in runs:
        key = b"/F3" if run.symbol else (b"/F2" if run.bold else b"/F1")
        # Ts is the text rise — how a superscript gets set above the
        # baseline without moving the pen, so Tj keeps advancing the
        # line normally afterwards.
        out += b" %s %.2f Tf %.2f Ts (%s) Tj" % (
            key, run.size, run.rise, _escape(run)
        )
    return bytes(out + b" ET\n")


def _place(x: float, y: float, runs: Sequence[_Piece2]) -> bytes:
    """A row drawn from (*x*, *y*), fractions positioned by hand.

    Text advances the pen by itself, which is why a stretch of it goes out
    as one Td and a string of Tj. A fraction cannot: its two rows sit at
    coordinates of their own. So the run of text breaks there, the box is
    drawn where the pen had got to, and the text picks up past its width.
    """
    out = bytearray()
    pen = start = x
    batch: list[_Run] = []
    for run in runs:
        if isinstance(run, _Stack):
            out += _show(start, y, batch)
            batch = []
            out += _stack(pen, y, run)
            start = pen + run.width
        else:
            batch.append(run)
        pen += run.width
    return bytes(out + _show(start, y, batch))


def _stack(x: float, y: float, box: _Stack) -> bytes:
    """One fraction: numerator, denominator, and the rule between them."""
    base = y + box.rise
    out = bytearray()
    for row, rise in (
        (box.top, box.size * _FRAC_RISE), (box.bottom, -box.size * _FRAC_DROP)
    ):
        out += _place(x + (box.width - _width(row)) / 2, base + rise, row)
    pad = box.size * _FRAC_PAD
    out += b"%.2f %.2f %.2f %.2f re f\n" % (
        x + pad, base + box.size * _FRAC_BAR,
        box.width - 2 * pad, box.size * _RULE,
    )
    return bytes(out)


def _content(
    lines: Sequence[tuple[float, list[_Piece2]]], page_height: float = _PAGE_H
) -> bytes:
    """The page's content stream. y is measured down; PDF measures up."""
    out = bytearray()
    for baseline, runs in lines:
        out += _place(_MARGIN, page_height - baseline, runs)
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
