"""Demo state behind the API: one in-memory set of services per process, seeded from the KPRM sample data.

Evaluation ids are numbers (the contract exposes `int`), so the domain cycle id is just str(int).
A database repository can replace InMemoryCycleRepository later without touching the routes.

Two seeds:
- simple (tests): an open cycle for everyone who has an evaluator, on `today`;
- scenario (the running app, POST /api/demo/reset): evaluations at every stage of the process on the demo
  date, Grzegorz Wzór at the review meeting with the team's tagged test notes (see `demo_seed.py`).
"""
from __future__ import annotations

import dataclasses
import inspect
import itertools
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Iterator

from app.application.assistant import AiSuggestionService, HrReport, NoteClassification
from app.application.use_cases import EvaluationService
from app.domain.access import AccessPolicy
from app.domain.reminder_schedule import ReminderSchedule
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.notes import Note
from app.infrastructure.assistant_factory import build_assistant
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from app.infrastructure.json_codec import JsonCodec
from app.infrastructure.sql_store import SqlStateStore, Snapshot
from app.infrastructure.settings import OfficeSettings, load_office_settings
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
class DeputyRecord:
    """Zastępstwo: `deputy_id` stands in for evaluator `evaluator_id` from `od` to `do` (inclusive)."""
    id: int
    evaluator_id: str
    deputy_id: str
    od: date
    do: date

    def active_on(self, day: date) -> bool:
        return self.od <= day <= self.do


HR = "kadry"  # demo identity of the HR department / office administrator


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
    settings: OfficeSettings = field(default_factory=load_office_settings)
    deputy_records: list[DeputyRecord] = field(default_factory=list)
    reminder_prefs: dict[str, ReminderSchedule] = field(default_factory=dict)  # user id -> own schedule
    read_notifications: set[str] = field(default_factory=set)  # (user, notification key) marked read

    def schedule_for(self, user_id: str) -> ReminderSchedule:
        """The user's own reminder schedule, else the office default (config/ustawienia_urzedu.json)."""
        return self.reminder_prefs.get(user_id, self.settings.reminders)

    def active_deputies(self, evaluator_id: str, day: date) -> set[str]:
        return {d.deputy_id for d in self.deputy_records if d.evaluator_id == evaluator_id and d.active_on(day)}

    def policy(self) -> AccessPolicy:
        """Who may see / act on what today (app/domain/access.py), from the tree, settings and deputies."""
        today = self.clock.today()
        evaluators = {d.evaluator_id for d in self.deputy_records}
        return AccessPolicy(
            evaluator_of={e.id: e.evaluator_id for e in self.directory.all()},
            scope=self.settings.visibility_scope,
            deputies={ev: frozenset(self.active_deputies(ev, today)) for ev in evaluators},
            admins=frozenset({HR, self.settings.objection_reviewer}),  # the reviewer of objections reads all
        )

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


def _empty_state(today: date | None, ai_mode: str | None, scenario: bool, first_cycle_id: int = 1) -> DemoState:
    ids = itertools.count(first_cycle_id)
    clock = FixedClock(today or (DEMO_TODAY if scenario else date.today()))
    directory = KprmEmployeeDirectory()
    evaluations = EvaluationService(kprm_rulebook(), InMemoryCycleRepository(), directory, clock,
                                    new_id=lambda: str(next(ids)))
    mode = (ai_mode or config.AI_MODE).lower()
    st = DemoState(clock, directory, evaluations, build_assistant(mode), mode)
    evaluations.deputies = st.active_deputies  # deputies may act on the evaluator's behalf (use_cases)
    evaluations.objection_reviewer = st.settings.objection_reviewer
    return st


def build_state(today: date | None = None, ai_mode: str | None = None, scenario: bool = False) -> DemoState:
    st = _empty_state(today, ai_mode, scenario)
    if scenario:
        from .demo_seed import seed_scenario

        seed_scenario(st)
    else:
        for employee in st.directory.all():  # simple seed: an open cycle for everyone who has an evaluator
            if employee.evaluator_id:
                st.evaluations.start_cycle(employee.id)
    return st


# ---------------------------------------------------------------- persistence (app/infrastructure/sql_store.py)

def _codec() -> JsonCodec:
    """Every dataclass / enum that can sit inside the stored state – nothing else can be rebuilt from the DB."""
    import sys

    from app.application import assistant
    from app.domain import cycle, deadlines, notes, reminder_schedule, scoring

    mods = [cycle, deadlines, scoring, notes, reminder_schedule, assistant, sys.modules[__name__]]
    types = [obj for m in mods for _, obj in inspect.getmembers(m, inspect.isclass)
             if obj.__module__ == m.__name__ and (dataclasses.is_dataclass(obj) or issubclass(obj, Enum))]
    return JsonCodec(types)


_store: SqlStateStore | None = None


def store() -> SqlStateStore:
    global _store
    if _store is None:
        from backend.db import engine

        _store = SqlStateStore(engine, _codec())
    return _store


def snapshot(st: DemoState) -> Snapshot:
    return Snapshot(
        cycles=st.evaluations.cycles.list_all(), notes=list(st.notes.values()), absences=list(st.absences),
        deadline_changes=list(st.deadline_changes), deputies=list(st.deputy_records),
        meta={"dzis": st.clock.today(), "wersje": dict(st.versions), "hr_sygnaly_id": dict(st.hr_signal_ids),
              "hr_decyzje": dict(st.hr_decisions), "przypomnienia_wlasne": dict(st.reminder_prefs),
              "przeczytane": set(st.read_notifications),
              # office default changed by HR in the app (else the file config/ustawienia_urzedu.json applies)
              **({"przypomnienia_urzedu": st.settings.reminders}
                 if st.settings.reminders != load_office_settings().reminders else {})},
    )


def restore(snap: Snapshot, ai_mode: str | None = None) -> DemoState:
    last_cycle = max((int(c.id) for c in snap.cycles if str(c.id).isdigit()), default=0)
    st = _empty_state(snap.meta.get("dzis"), ai_mode, scenario=False, first_cycle_id=last_cycle + 1)
    for c in snap.cycles:
        st.evaluations.cycles.save(c)
    st.notes = {int(r.note.id): r for r in snap.notes}
    st.note_ids = itertools.count(max(st.notes, default=0) + 1)
    st.absences = list(snap.absences)
    st.deadline_changes = list(snap.deadline_changes)
    st.deputy_records = list(snap.deputies)
    st.versions = dict(snap.meta.get("wersje", {}))
    st.hr_signal_ids = dict(snap.meta.get("hr_sygnaly_id", {}))
    st.hr_decisions = dict(snap.meta.get("hr_decyzje", {}))
    st.reminder_prefs = dict(snap.meta.get("przypomnienia_wlasne", {}))
    st.read_notifications = set(snap.meta.get("przeczytane", set()))
    if "przypomnienia_urzedu" in snap.meta:
        st.settings = dataclasses.replace(st.settings, reminders=snap.meta["przypomnienia_urzedu"])
    return st


def save_state() -> None:
    """Called after every successful change (middleware in backend/main.py) and after background work."""
    if _state is not None:
        store().save(snapshot(_state))


_state: DemoState | None = None


def get_state() -> DemoState:
    """FastAPI dependency. Loads the saved state from the database; an empty database gets the demo scenario."""
    global _state
    if _state is None:
        if store().is_empty():
            _state = build_state(scenario=True)
            save_state()
        else:
            _state = restore(store().load())
    return _state


def reset_state(today: date | None = None, ai_mode: str | None = None, scenario: bool = False) -> DemoState:
    """Fresh seed (tests: simple; POST /api/demo/reset: scenario – saved by the middleware right after)."""
    global _state
    _state = build_state(today, ai_mode, scenario)
    return _state
