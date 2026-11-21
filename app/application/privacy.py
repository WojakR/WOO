"""Pseudonymisation of text sent to a language model: names, PESEL numbers and e-mails are replaced
with tokens before the call and the names are restored in the answer.

Polish names inflect ("Grzegorz" -> "Grzegorza", "Grzegorzowi"), so a name matches with up to 4 extra
letters; the answer gets the base form back. Used for every AI mode, local included, so the log of what
left the application (AiInteraction) never holds personal data.
"""
from __future__ import annotations

import re
from typing import Iterable

_PESEL = re.compile(r"\b\d{11}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
_TOKEN = re.compile(r"\[OSOBA_(\d+)\]")


class Pseudonymizer:
    def __init__(self, people: Iterable[tuple[str, str]]):
        """people: (first name, last name) of everyone who may appear in the text."""
        self._people: list[tuple[str, str]] = [(f.strip(), l.strip()) for f, l in people if f.strip() or l.strip()]
        patterns = []
        for i, (first, last) in enumerate(self._people, start=1):
            token = f"[OSOBA_{i}]"
            for words in ((first, last), (last, first), (first,), (last,)):
                if all(words):
                    body = r"\s+".join(re.escape(w) + r"\w{0,4}" for w in words)
                    patterns.append((len(" ".join(words)), re.compile(rf"\b{body}\b", re.IGNORECASE), token))
        # longest first, so "Grzegorz Wzór" wins over "Grzegorz"
        self._patterns = [(rx, tok) for _, rx, tok in sorted(patterns, key=lambda p: -p[0])]

    def mask(self, text: str) -> str:
        text = _EMAIL.sub("[EMAIL]", text)
        text = _PESEL.sub("[PESEL]", text)
        for rx, token in self._patterns:
            text = rx.sub(token, text)
        return text

    def unmask(self, text: str) -> str:
        def full_name(m: re.Match) -> str:
            i = int(m.group(1)) - 1
            if 0 <= i < len(self._people):
                return " ".join(p for p in self._people[i] if p)
            return m.group(0)

        return _TOKEN.sub(full_name, text)

    def token_for(self, first: str, last: str) -> str:
        for i, p in enumerate(self._people, start=1):
            if p == (first.strip(), last.strip()):
                return f"[OSOBA_{i}]"
        return f"{first} {last}".strip()
