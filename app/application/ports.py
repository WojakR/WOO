"""Ports the use cases depend on. Adapters live in app/infrastructure (or backend/ later, e.g. SQLite)."""
from __future__ import annotations

from datetime import date
from typing import Protocol

from app.domain.cycle import EvaluationCycle
from app.domain.employee import Employee


class CycleRepository(Protocol):
    def get(self, cycle_id: str) -> EvaluationCycle | None: ...

    def save(self, cycle: EvaluationCycle) -> None: ...

    def list_all(self) -> list[EvaluationCycle]: ...

    def find_open_for(self, employee_id: str) -> EvaluationCycle | None:
        """The employee's cycle that is not yet acknowledged, if any."""
        ...


class EmployeeDirectory(Protocol):
    def get(self, employee_id: str) -> Employee | None: ...


class Clock(Protocol):
    def today(self) -> date: ...
