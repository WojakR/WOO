"""Demo state behind the API: one in-memory set of services per process, seeded from the KPRM sample data.

Evaluation ids are numbers (the contract exposes `int`), so the domain cycle id is just str(int).
A database repository can replace InMemoryCycleRepository later without touching the routes.

Two seeds:
- simple (tests): an open cycle for everyone who has an evaluator, on `today`;
- scenario (the running app, POST /api/demo/reset): evaluations at every stage of the process on the demo
  date, Grzegorz Wzór at the review meeting with the team's tagged test notes (see `demo_seed.py`).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Iterator

from app.application.assistant import AiSuggestionService, HrReport, NoteClassification
from app.application.use_cases import EvaluationService
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.notes import Note
from app.infrastructure.assistant_factory import build_assistant
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from backend import config

DEMO_TODAY = date(2026, 5, 25)  # Grzegorz Wzór's deadline 12.06.2026 is then 18 days away


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
class RecordVersion:
    """Optimistic locking for PATCH (contract rule 3): `wersja` + `updated_at` of one evaluation."""
    version: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class AbsenceRecord:
    """A registered absence (UC8) + what only the API needs."""
    id: int
    employee_id: str
    cycle_id: str
    absence: Absence
    typ: str  # TypNieobecnosci
    deadline_after: date  # evaluation deadline right after registering it (server-computed)
    change_id: int | None = None  # the DeadlineChangeRecord this absence caused (AUTO), if any


@dataclass
class DeadlineChangeRecord:
    id: int
    cycle_id: str
    reason: str  # PowodZmianyTerminu
    old: date
    new: date | None
    status: str  # StatusWniosku
    justification: str
    decided_at: datetime | None


@dataclass
class DemoState:
    clock: FixedClock  # the server's own clock (contract rule 7: never the browser's date)
    directory: KprmEmployeeDirectory
    evaluations: EvaluationService
    assistant: AiSuggestionService
    ai_mode: str  # off | local | api
    notes: dict[int, NoteRecord] = field(default_factory=dict)
    note_ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))
    versions: dict[str, RecordVersion] = field(default_factory=dict)
    hr_reports: dict[str, tuple[tuple, HrReport]] = field(default_factory=dict)  # cycle id -> (inputs key, report)
    hr_signal_ids: dict[tuple[str, str], int] = field(default_factory=dict)  # (cycle id, signal kind) -> stable id
    hr_decisions: dict[int, str] = field(default_factory=dict)  # signal id -> ZAAKCEPTOWANY / ODRZUCONY
    absences: list[AbsenceRecord] = field(default_factory=list)
    deadline_changes: list[DeadlineChangeRecord] = field(default_factory=list)

    def notes_of(self, evaluation_id: int) -> list[NoteRecord]:
        return [r for r in self.notes.values() if r.evaluation_id == evaluation_id]

    def add_note(self, evaluation_id: int, note: Note, kind: str = "OBSERWACJA") -> NoteRecord:
        """Store a note under a fresh int id (the domain Note gets the same id as text)."""
        nid = next(self.note_ids)
        note = Note(str(nid), note.on, note.text, note.author_id, note.criterion_id, note.sentiment, note.indicator)
        record = NoteRecord(note, evaluation_id, kind, status="RECZNA" if note.criterion_id else "BRAK")
        self.notes[nid] = record
        return record

    def employee_number(self, employee_id: str) -> int:
        """The contract's int id of a person: position in the directory (data ids are text, e.g. 'jan.kowalski')."""
        ids = [e.id for e in self.directory.all()]
        return ids.index(employee_id) + 1 if employee_id in ids else 0

    def employee_by_number(self, number: int) -> Employee | None:
        """Inverse of `employee_number`."""
        people = self.directory.all()
        return people[number - 1] if 1 <= number <= len(people) else None

    def version_of(self, cycle_id: str) -> RecordVersion:
        return self.versions.setdefault(cycle_id, RecordVersion())

    def touch(self, cycle_id: str) -> None:
        self.version_of(cycle_id).touch()

    def signal_id(self, cycle_id: str, kind: str) -> int:
        key = (cycle_id, kind)
        if key not in self.hr_signal_ids:
            self.hr_signal_ids[key] = len(self.hr_signal_ids) + 1
        return self.hr_signal_ids[key]

    def model_available(self) -> bool:
        try:
            return bool(self.assistant.model.available())
        except Exception:  # noqa: BLE001 – a broken model only means "use templates"
            return False


def build_state(today: date | None = None, ai_mode: str | None = None, scenario: bool = False) -> DemoState:
    ids = itertools.count(1)
    clock = FixedClock(today or (DEMO_TODAY if scenario else date.today()))
    directory = KprmEmployeeDirectory()
    evaluations = EvaluationService(kprm_rulebook(), InMemoryCycleRepository(), directory, clock,
                                    new_id=lambda: str(next(ids)))
    mode = (ai_mode or config.AI_MODE).lower()
    st = DemoState(clock, directory, evaluations, build_assistant(mode), mode)
    if scenario:
        from .demo_seed import seed_scenario

        seed_scenario(st)
    else:
        for employee in directory.all():  # simple seed: an open cycle for everyone who has an evaluator
            if employee.evaluator_id:
                evaluations.start_cycle(employee.id)
    return st


_state: DemoState | None = None


def get_state() -> DemoState:
    """FastAPI dependency. The running app starts with the demo scenario."""
    global _state
    if _state is None:
        _state = build_state(scenario=True)
    return _state


def reset_state(today: date | None = None, ai_mode: str | None = None, scenario: bool = False) -> DemoState:
    """Fresh seed (tests: simple; POST /api/demo/reset: scenario)."""
    global _state
    _state = build_state(today, ai_mode, scenario)
    return _state
