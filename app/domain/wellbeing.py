"""Burnout checklist (spec, point 3): during the review meeting the evaluator goes through 8 symptoms and notes
what they observe at work – not a diagnosis. The list itself is data (data/kprm/wellbeing.json).

The answers are the evaluator's working material: only the evaluator, their deputy and the HR partner see them
(AccessPolicy.can_see_working_material) – never the evaluated person, never the PDF of the sheet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Mapping

from .errors import ValidationError


class Frequency(str, Enum):
    NOT_SEEN = "NIE_ZAUWAZAM"
    SOMETIMES = "CZASAMI"
    OFTEN = "CZESTO"


@dataclass(frozen=True)
class SymptomAnswer:
    answer: Frequency
    comment: str = ""


@dataclass
class WellbeingCheck:
    cycle_id: str
    answers: dict[str, SymptomAnswer] = field(default_factory=dict)
    updated_on: date | None = None
    updated_by: str = ""

    def often(self) -> list[str]:
        return [sid for sid, a in self.answers.items() if a.answer is Frequency.OFTEN]


MAX_COMMENT = 500


def parse_answers(raw: Mapping[str, Mapping], symptom_ids: list[str]) -> dict[str, SymptomAnswer]:
    """`raw`: {symptom id: {"odpowiedz": "CZESTO", "komentarz": "..."}}. Every id must be on the list."""
    problems, out = [], {}
    for sid, item in raw.items():
        if sid not in symptom_ids:
            problems.append(f"Nieznany obszar listy kontrolnej: „{sid}”.")
            continue
        try:
            answer = Frequency(item.get("odpowiedz"))
        except ValueError:
            problems.append(f"{sid}: odpowiedź musi być jedną z: {', '.join(f.value for f in Frequency)}.")
            continue
        comment = str(item.get("komentarz") or "").strip()
        if len(comment) > MAX_COMMENT:
            problems.append(f"{sid}: komentarz może mieć najwyżej {MAX_COMMENT} znaków.")
            continue
        out[sid] = SymptomAnswer(answer, comment)
    if problems:
        raise ValidationError(problems)
    return out


def overload_evidence(check: WellbeingCheck | None, names: Mapping[str, str], threshold: int) -> list[str]:
    """Evidence for the HR partner's PRZECIAZENIE signal: at least `threshold` symptoms seen "often"."""
    if check is None:
        return []
    often = check.often()
    if len(often) < threshold:
        return []
    when = f" ({check.updated_on:%d.%m.%Y})" if check.updated_on else ""
    out = [f"Lista kontrolna dobrostanu{when}: „często” w {len(often)} z {len(names)} obszarów – "
           + ", ".join(names.get(s, s).lower() for s in often)]
    out += [f"{names.get(s, s)}: {check.answers[s].comment}" for s in often if check.answers[s].comment]
    return out
