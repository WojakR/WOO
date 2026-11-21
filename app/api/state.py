"""Demo state behind the API: one in-memory set of services per process, seeded from the KPRM sample data.

Evaluation ids are numbers (the contract exposes `int`), so the domain cycle id is just str(int).
A database repository can replace InMemoryCycleRepository later without touching the routes.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date

from app.application.assistant import AiSuggestionService
from app.application.use_cases import EvaluationService
from app.infrastructure.assistant_factory import build_assistant
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from backend import config


@dataclass
class DemoState:
    clock: FixedClock  # the server's own clock (contract rule 7: never the browser's date)
    directory: KprmEmployeeDirectory
    evaluations: EvaluationService
    assistant: AiSuggestionService
    ai_mode: str  # off | local | api


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
