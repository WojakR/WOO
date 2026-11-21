"""Demo state behind the API: one in-memory set of services per process, seeded from the KPRM sample data.

Evaluation ids are numbers (the contract exposes `int`), so the domain cycle id is just str(int).
A database repository can replace InMemoryCycleRepository later without touching the routes.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

from app.application.assistant import AiSuggestionService, NoteClassification
from app.application.use_cases import EvaluationService
from app.domain.notes import Note
from app.infrastructure.assistant_factory import build_assistant
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from backend import config


@dataclass
class NoteRecord:
    """A stored note: the domain Note (what counts as evidence) + what only the API/UI needs."""
    note: Note  # criterion_id/sentiment set only by the evaluator (manually or by accepting a suggestion)
    evaluation_id: int
    kind: str  # TypNotatki
    visible_to_employee: bool = False
    status: str = "BRAK"  # status_klasyfikacji
    classification: NoteClassification | None = None  # AI / rule suggestions – never applied automatically


@dataclass
class DemoState:
    clock: FixedClock  # the server's own clock (contract rule 7: never the browser's date)
    directory: KprmEmployeeDirectory
    evaluations: EvaluationService
    assistant: AiSuggestionService
    ai_mode: str  # off | local | api
    notes: dict[int, NoteRecord] = field(default_factory=dict)
    note_ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    def notes_of(self, evaluation_id: int) -> list[NoteRecord]:
        return [r for r in self.notes.values() if r.evaluation_id == evaluation_id]

    def employee_number(self, employee_id: str) -> int:
        """The contract's int id of a person: position in the directory (data ids are text, e.g. 'jan.kowalski')."""
        ids = [e.id for e in self.directory.all()]
        return ids.index(employee_id) + 1 if employee_id in ids else 0


def build_state(today: date | None = None, ai_mode: str | None = None) -> DemoState:
    ids = itertools.count(1)
    clock = FixedClock(today or date.today())
    directory = KprmEmployeeDirectory()
    evaluations = EvaluationService(kprm_rulebook(), InMemoryCycleRepository(), directory, clock,
                                    new_id=lambda: str(next(ids)))
    for employee in directory.all():  # demo seed: an open cycle for everyone who has an evaluator
        if employee.evaluator_id:
            evaluations.start_cycle(employee.id)
    mode = (ai_mode or config.AI_MODE).lower()
    return DemoState(clock, directory, evaluations, build_assistant(mode), mode)


_state: DemoState | None = None


def get_state() -> DemoState:
    """FastAPI dependency."""
    global _state
    if _state is None:
        _state = build_state()
    return _state


def reset_state(today: date | None = None, ai_mode: str | None = None) -> DemoState:
    """Fresh seed (tests; later POST /api/demo/reset)."""
    global _state
    _state = build_state(today, ai_mode)
    return _state
