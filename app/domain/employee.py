"""Evaluated person / evaluator as the domain sees them (no storage details)."""
from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
