"""In-memory repository (tests, demo). Clocks live in clock.py (re-exported here for old imports)."""
from __future__ import annotations

import copy

from app.domain.cycle import EvaluationCycle, Status
from app.infrastructure.clock import FixedClock, SystemClock  # noqa: F401 – old import path


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
        """The running cycle. An acknowledged evaluation – also one under objection – is not "open": the next
        cycle already runs next to it."""
        for c in self._items.values():
            if c.employee_id == employee_id and c.status not in (Status.ACKNOWLEDGED, Status.OBJECTION):
                return copy.deepcopy(c)
        return None

    def delete(self, cycle_id: str) -> None:
        self._items.pop(cycle_id, None)
