"""Pseudonymisation of text sent to a language model: names, PESEL numbers, e-mails and phone numbers are
replaced with tokens before the call and the names are restored in the answer.

Polish names inflect, so each name word becomes a pattern that also matches its declined forms:
- the final vowel may go: Janina -> Janinie / Janinę, Kowalska -> Kowalskiej, Przełożony -> Przełożonego;
- a mobile "e" in the last syllable may drop: Marek -> Marka, Paweł -> Pawła;
- the last consonant may soften: Kładka -> Kładce, Olga -> Oldze, Marta -> Marcie, Miranda -> Mirandzie;
- Polish letters may alternate or be typed without diacritics: Wzór -> Wzorem / Wzor, Wąsik -> Wasik;
- up to 4 more letters of ending follow (Grzegorzowi, Kowalskiego).
The first letter must be a capital (as names are written), so "wzorem pisma" or "gut feeling" stay text;
a name typed all in lower case is NOT masked. The answer gets the base form of the name back.
Used for every AI mode, local included, so the log of what left the application (AiInteraction) never
holds personal data.
"""
from __future__ import annotations

import re
from typing import Iterable

_PESEL = re.compile(r"\b\d{11}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
# Polish numbers: optional +48 / 0048, then 3-3-3 (mobile) or 2-3-2-2 (landline), spaces or hyphens allowed
_PHONE = re.compile(
    r"(?<![\d\w])(?:(?:\+|00)48[\s-]?)?(?:\d{3}[\s-]?\d{3}[\s-]?\d{3}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?![\d\w])"
)

_VOWELS = set("aeiouyąęó")
# letter -> what it may appear as in a declined form or when typed without Polish diacritics
_LETTER_VARIANTS = {"ą": "ąa", "ę": "ęe", "ó": "óo", "ł": "łl", "ś": "śs", "ć": "ćc", "ń": "ńn", "ź": "źzż", "ż": "żz"}
# last consonant of the stem -> its softened forms before -e/-i endings
_SOFTENING_AFTER_A = {"k": ("k", "c"), "g": ("g", "dz"), "t": ("t", "c"), "d": ("d", "dz"), "r": ("r", "rz"),
                      "ł": ("ł", "l"), "ch": ("ch", "sz")}  # Kładka -> Kładce, Olga -> Oldze, Marta -> Marcie
_SOFTENING_CONSONANT_FINAL = {"r": ("r", "rz"), "ł": ("ł", "l"), "t": ("t", "c"), "d": ("d", "dz")}
# Wzór -> Wzorze, Paweł -> Pawle, Robert -> Robercie, Konrad -> Konradzie (but Marek -> Marku, never "Marc-")
# case endings of Polish names (nouns and -ski/-ny adjectives); anything else is a different word (Adam ≠ Adamczyk)
_ENDINGS = ("a", "e", "i", "y", "o", "u", "ą", "ę", "em", "om", "ie", "iem", "owi", "owie", "ów", "ego", "emu",
            "iego", "iemu", "ej", "iej", "im", "ym", "ich", "ych", "imi", "ymi", "ami", "ach")


def _letter(ch: str) -> str:
    variants = _LETTER_VARIANTS.get(ch.lower(), ch.lower())
    return re.escape(variants) if len(variants) == 1 else "[" + variants + "]"


def _first_letter(ch: str) -> str:
    """Case-sensitive: a capital, also without its diacritic (Ł -> Ł or L)."""
    variants = _LETTER_VARIANTS.get(ch.lower(), ch.lower())
    caps = "".join(dict.fromkeys(v.upper() for v in variants))
    return re.escape(caps) if len(caps) == 1 else "[" + caps + "]"


_ENDINGS_RX = "(?:" + "|".join("".join(_letter(c) for c in e) for e in sorted(_ENDINGS, key=len, reverse=True)) + ")?"


def _word_pattern(word: str) -> str:
    """Regex for one name word and its Polish inflected forms (see the module docstring)."""
    w = word.lower()
    vowel_final = len(w) >= 3 and w[-1] in _VOWELS
    stem = w[:-1] if vowel_final else w
    softening = _SOFTENING_AFTER_A if vowel_final else _SOFTENING_CONSONANT_FINAL
    ending = "ch" if stem.endswith("ch") and "ch" in softening else (stem[-1] if stem[-1:] in softening else None)
    body = stem[: -len(ending)] if ending else stem

    letters = [_letter(c) for c in body]
    # mobile "e" in the last syllable of a consonant-final name: Marek -> Marka, Paweł -> Pawła, Wróbel -> Wróbla
    if not vowel_final and len(w) >= 4 and w[-2] == "e" and w[-1] not in _VOWELS:
        letters[len(body) - 1 if ending else len(body) - 2] = "e?"
    if ending:
        letters.append("(?:" + "|".join("".join(_letter(c) for c in alt) for alt in softening[ending]) + ")")
    return _first_letter(word[0]) + "(?i:" + "".join(letters[1:]) + _ENDINGS_RX + ")"


class Pseudonymizer:
    def __init__(self, people: Iterable[tuple[str, str]], label: str = "OSOBA_"):
        """people: (first name, last name) of everyone who may appear in the text.
        label: token prefix, "[OSOBA_1]" by default. A second, independent layer (backend.llm) uses its own
        label so that it never restores – and never confuses – tokens put into the text by another one."""
        if not re.fullmatch(r"[A-Z_]+", label):
            raise ValueError("label: tylko wielkie litery A-Z i podkreślenie")
        self._label = label
        self._token_rx = re.compile(rf"\[{label}(\d+)\]")
        self._people: list[tuple[str, str]] = [(f.strip(), l.strip()) for f, l in people if f.strip() or l.strip()]
        patterns = []
        for i, (first, last) in enumerate(self._people, start=1):
            token = f"[{label}{i}]"
            for words in ((first, last), (last, first), (first,), (last,)):
                if all(words):
                    body = r"\s+".join(_word_pattern(w) for w in words)
                    patterns.append((len(" ".join(words)), re.compile(rf"(?<!\w){body}(?!\w)"), token))
        # longest first, so "Grzegorz Wzór" wins over "Grzegorz"
        self._patterns = [(rx, tok) for _, rx, tok in sorted(patterns, key=lambda p: -p[0])]

    def mask(self, text: str) -> str:
        text = _EMAIL.sub("[EMAIL]", text)
        text = _PESEL.sub("[PESEL]", text)
        text = _PHONE.sub("[TELEFON]", text)
        for rx, token in self._patterns:
            text = rx.sub(token, text)
        return text

    def unmask(self, text: str) -> str:
        def full_name(m: re.Match) -> str:
            i = int(m.group(1)) - 1
            if 0 <= i < len(self._people):
                return " ".join(p for p in self._people[i] if p)
            return m.group(0)

        return self._token_rx.sub(full_name, text)

    def token_for(self, first: str, last: str) -> str:
        for i, p in enumerate(self._people, start=1):
            if p == (first.strip(), last.strip()):
                return f"[{self._label}{i}]"
        return f"{first} {last}".strip()
