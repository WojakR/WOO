"""Evaluated person / evaluator as the domain sees them (no storage details)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .cycle import PreviousEvaluation


@dataclass(frozen=True)
class Employee:
    id: str
    first_name: str
    last_name: str
    office: str
    unit: str
    position: str
    sheet: str
    evaluator_id: str | None = None
    previous_evaluation: PreviousEvaluation | None = None
    # from the HR system (app/infrastructure/hr_import.py); the sample data may not have them
    civil_servant: bool = False  # urzędnik służby cywilnej (mianowany) – else "pracownik służby cywilnej"
    grade: int | None = None  # stopień służbowy 1–9 (civil servants only)
    grade_since: date | None = None  # when the current grade was granted (art. 89 ust. 2 counts from it)
    manages_people: bool | None = None  # kieruje zespołem (sheet B); None = unknown
    is_office_head: bool | None = None  # kierownik urzędu / dyrektor generalny (sheet A); None = unknown
    email: str | None = None  # reminders by e-mail; None = in-app notifications only
    position_description: str = ""
    employment_start: date | None = None
    employment_end: date | None = None  # ustanie stosunku pracy (archiving periods count from here)
    # the person's data was deleted (KPRM use case "usunięcie danych pracownika"): only this record stays, so the
    # archived evaluations keep their retention period (counted from employment_end) and the ids stay stable
    removed_on: date | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
