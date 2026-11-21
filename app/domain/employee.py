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
    # HR data for the sheet choice (§ 3 of the regulation); None = not known (app/domain/sheet_choice.py)
    is_office_head: bool | None = None
    manages_people: bool | None = None
    employment_end: date | None = None  # day the employment ended (archive retention, app/application/archive.py)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
