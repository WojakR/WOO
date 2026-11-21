"""In-memory repository and clocks (tests, demo). A SQLite repository can replace the repo later."""
from __future__ import annotations

import copy
from datetime import date, timedelta

from app.domain.cycle import EvaluationCycle, Status


class InMemoryCycleRepository:
    """Stores deep copies, so a failed use case never leaves a half-modified cycle behind."""

    def __init__(self):
        self._items: dict[str, EvaluationCycle] = {}

    def get(self, cycle_id: str) -> EvaluationCycle | None:
        c = self._items.get(cycle_id)
        return copy.deepcopy(c) if c else None

    def save(self, cycle: EvaluationCycle) -> None:
        self._items[cycle.id] = copy.deepcopy(cycle)

    def list_all(self) -> list[EvaluationCycle]:
        return [copy.deepcopy(c) for c in self._items.values()]

    def find_open_for(self, employee_id: str) -> EvaluationCycle | None:
        for c in self._items.values():
            if c.employee_id == employee_id and c.status is not Status.ACKNOWLEDGED:
                return copy.deepcopy(c)
        return None


class SystemClock:
    def today(self) -> date:
        return date.today()


class FixedClock:
    """Controllable clock for tests and the demo's "przewiń czas" button."""

    def __init__(self, today: date):
        self._today = today

    def today(self) -> date:
        return self._today

    def set(self, today: date) -> None:
        self._today = today

    def advance(self, days: int = 0, weeks: int = 0) -> date:
        self._today += timedelta(days=days, weeks=weeks)
        return self._today
