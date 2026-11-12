"""French text helpers for command matching.

Vosk writes lowercase words and spells numbers out ("dix huit heures trente"), while typed
commands may have accents, capitals and digits. Commands match on a *folded* copy of the
text (lowercase, no accents, no punctuation) that has exactly the same length as the
original, so captured arguments can be cut from the original text with accents intact.
"""
from __future__ import annotations

import re
import unicodedata

_PUNCT = set(".,;:!?«»\"()[]{}…")


def _fold_char(c: str) -> str:
    if c in _PUNCT:
        return " "
    if c in "’`":
        return "'"
    base = unicodedata.normalize("NFKD", c)
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    return base[0] if len(base) == 1 else c


def fold(text: str) -> str:
    """Same-length folded copy: 'Arrête-toi !' -> 'arrete-toi  '."""
    return "".join(_fold_char(c) for c in text.lower())


def simple(text: str) -> str:
    """Folded and compacted, for comparisons: 'Arrête-toi !' -> 'arrete toi'."""
    return re.sub(r"[\s\-']+", " ", fold(text)).strip()


# Polite openings and endings that never change the meaning of a command.
_PREFIX = re.compile(
    r"^\s*(?:jarvis\s+)?(?:(?:est[ -]ce que\s+)?(?:tu peux|peux[ -]tu|pourrais[ -]tu|tu pourrais|veux[ -]tu|"
    r"tu veux bien|je veux que tu|j'aimerais que tu|je voudrais que tu|merci de|s'il te plait)\s+)+"
)
_SUFFIX = re.compile(r"\s+(?:s'il te plait|s'il vous plait|stp|svp|merci)\s*$")


class Utterance:
    """A command sentence: `original` (as said/typed, trimmed) and `folded` (same length)."""

    def __init__(self, text: str):
        original = text.strip()
        folded = fold(original)
        if len(folded) != len(original):  # exotic characters change length when lowercased
            original = original.lower()
            folded = fold(original)
        start, end = 0, len(folded)
        m = _PREFIX.match(folded)
        if m:
            start = m.end()
        m = _SUFFIX.search(folded[start:end])
        if m:
            end = start + m.start()
        self.original = original[start:end].strip()
        self.folded = fold(self.original)

    def span(self, start: int, end: int) -> str:
        return self.original[start:end].strip()


# ---------------------------------------------------------------------------------------
# French numbers in words ("vingt et un", "quatre vingt dix", "dix huit") -> int
# ---------------------------------------------------------------------------------------
_UNITS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40,
    "cinquante": 50, "soixante": 60, "cent": 100, "cents": 100, "mille": 1000,
}
NUMBER_WORDS = set(_UNITS) | {"et"}


def words_to_number(text: str) -> int | None:
    """Parse '42', 'quarante deux', 'soixante dix', 'quatre vingt dix neuf', 'deux cents'."""
    text = simple(text)
    if re.fullmatch(r"\d+", text):
        return int(text)
    total, current, seen = 0, 0, False
    for word in text.replace("-", " ").split():
        if word == "et":
            continue
        if word not in _UNITS:
            return None
        value = _UNITS[word]
        seen = True
        if value == 1000:
            total += max(current, 1) * 1000
            current = 0
        elif value == 100:
            current = max(current, 1) * 100
        elif value == 20 and current % 100 == 4:  # quatre vingt(s)
            current = current - 4 + 80
        elif value < 10 and current % 10 == 0 and current % 100 in (20, 30, 40, 50, 60, 80):
            current += value
        elif 10 <= value <= 16 and current % 100 in (60, 80):  # soixante dix, quatre vingt douze
            current += value
        elif value < 10 and current % 100 in (70, 90) and current % 10 == 0:
            current += value
        elif value < 10 and current % 100 == 10 and current >= 10:  # dix sept
            current += value
        else:
            current += value
    return total + current if seen else None


_NUM_RUN = re.compile(r"\b(?:(?:%s)(?:[\s-]+|$))+" % "|".join(sorted(NUMBER_WORDS - {"et"}, key=len, reverse=True)))


def numbers_to_digits(text: str) -> str:
    """'dans dix huit minutes' -> 'dans 18 minutes' (works on folded/simple text)."""
    def repl(m: re.Match) -> str:
        chunk = m.group(0)
        value = words_to_number(chunk)
        trailing = " " if chunk[-1:].isspace() else ""
        return f"{value}{trailing}" if value is not None else chunk
    text = re.sub(r"\bpour\s*cents?\b", "%", text)
    out = _NUM_RUN.sub(repl, text)
    return re.sub(r"(\d+)\s+et\s+(\d+)", lambda m: str(int(m.group(1)) + int(m.group(2))), out)
