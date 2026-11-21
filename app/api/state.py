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
from app.application.personnel_export import ExportService, ExportStatus
from app.application.use_cases import EvaluationService
from app.domain.access import AccessPolicy
from app.domain.reminder_schedule import ReminderSchedule
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.notes import Note
from app.domain.wellbeing import WellbeingCheck, overload_evidence as wellbeing_evidence
from app.domain.worktime_signals import WorkDay, indicators, overload_evidence as worktime_evidence
from app.infrastructure.rcp_import import InMemoryWorkTimeStore
from app.infrastructure.assistant_factory import build_assistant
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.clock import FixedClock, SystemClock
from app.infrastructure.memory import InMemoryCycleRepository
from app.infrastructure.json_codec import JsonCodec
from app.infrastructure.sql_store import SqlStateStore, Snapshot
from app.infrastructure.settings import OfficeSettings, load_office_settings
from app.infrastructure import regulations
from app.domain.objection import Reviewer, objection_reviewer
from backend import config, kprm

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
    # the evaluator changed: the predecessor's notes are not passed on automatically – only the author sees them
    # until they hand them over (POST /api/notes/{id}/przekaz)
    withheld: bool = False


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
    requested_by: str = ""  # evaluator / deputy who changed or asked for the change (art. 81 ust. 8)
    decided_by: str | None = None
    decision_note: str = ""


@dataclass
class EvaluatorChangeRecord:
    """Change of the evaluator (HR): planned (date in the future – the leaving one is reminded) or done."""
    id: int
    employee_id: str
    old_evaluator_id: str
    new_evaluator_id: str
    on: date
    status: str  # PLANOWANA | WYKONANA
    variant: str | None = None  # NOWY_CYKL | PRZEJECIE (when done)
    registered_by: str = ""


@dataclass
class EvaluatorAbsenceRecord:
    """A planned absence of an evaluator (art. 81 ust. 8 pkt 3) – the app suggests a deputy or a new deadline."""
    id: int
    evaluator_id: str
    od: date
    do: date
    registered_by: str


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
class RuleChangeRecord:
    """The administrator changed a requirement of the regulation (e.g. after an amendment) – who, when, why."""
    key: str
    old: int
    new: int
    basis: str  # e.g. "nowelizacja rozporządzenia, Dz. U. 2027 poz. 123"
    by: str
    on: date


@dataclass
class DemoState:
    clock: FixedClock | SystemClock  # the server's own clock (contract rule 7: never the browser's date)
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
    evaluator_absences: list[EvaluatorAbsenceRecord] = field(default_factory=list)
    evaluator_changes: list[EvaluatorChangeRecord] = field(default_factory=list)
    settings: OfficeSettings = field(default_factory=load_office_settings)
    deputy_records: list[DeputyRecord] = field(default_factory=list)
    reminder_prefs: dict[str, ReminderSchedule] = field(default_factory=dict)  # user id -> own schedule
    read_notifications: set[str] = field(default_factory=set)  # (user, notification key) marked read
    # requirements of the regulation changed by the administrator (app/infrastructure/regulations.py)
    rule_overrides: dict[str, int] = field(default_factory=dict)  # values of the version in force today
    rule_changes: list[RuleChangeRecord] = field(default_factory=list)
    rule_versions: regulations.RuleVersions = field(default_factory=regulations.RuleVersions)
    # "off switch" for the AI assistant and the virtual HR partner: office-wide (admin) and per person
    ai_office: bool = True
    hr_partner_office: bool = True
    ai_off_for: set[str] = field(default_factory=set)
    hr_partner_off_for: set[str] = field(default_factory=set)
    # e-mail reminders (app/application/notify_job.py)
    # people imported from the HR system (app/infrastructure/hr_import.py) – on top of the sample data
    imported_employees: dict[str, Employee] = field(default_factory=dict)
    sent_email_keys: set[str] = field(default_factory=set)
    email_off_for: set[str] = field(default_factory=set)
    notify_last_run: date | None = None
    wellbeing: dict[str, WellbeingCheck] = field(default_factory=dict)  # cycle id -> burnout checklist
    worktime: InMemoryWorkTimeStore = field(default_factory=InMemoryWorkTimeStore)  # imported RCP days
    exporter: object | None = None  # PersonnelFileExporter (e-Akt, app/infrastructure/eakt.py); None = off
    legacy_imports: dict = field(default_factory=dict)  # id -> LegacyImportRecord (app/api/legacy_import.py)
    eakt_status: dict[str, ExportStatus] = field(default_factory=dict)  # cycle id -> last export
    _assistant_off: AiSuggestionService | None = None

    def eakt(self) -> ExportService | None:
        if self.exporter is None:
            return None
        from .evaluations import sheet_pdf_bytes

        return ExportService(self.exporter, lambda c: sheet_pdf_bytes(self, c), self.eakt_status)

    def export_to_eakt(self, c) -> None:
        """After the acknowledgement / the objection decision: send the sheet to e-Akt, retrying failed ones."""
        svc = self.eakt()
        if svc is None:
            return
        svc.retry_failed(lambda cid: None if cid == c.id else self.evaluations.cycles.get(cid))
        svc.export(c)

    def archive_store(self):
        """Frozen closed evaluations (table `archiwum` in backend/db.py), shared by every state of this process."""
        global _archive
        if _archive is None:
            from app.infrastructure.archive_store import SqlArchiveStore
            from backend.db import engine

            _archive = SqlArchiveStore(engine)
        return _archive

    def hr_extra_evidence(self, c) -> dict[str, list[str]]:
        """Aggregated evidence for the HR partner from the wellbeing checklist and the RCP indicators."""
        names = {x["id"]: x["nazwa"] for x in kprm.wellbeing()["objawy"]}
        overload = wellbeing_evidence(self.wellbeing.get(c.id), names, self.settings.wellbeing_often_threshold)
        today = self.clock.today()
        days = self.worktime.days_for(c.employee_id, date.min, today)
        overload += worktime_evidence(indicators(days, today, self.settings.rcp), self.settings.rcp)
        return {"PRZECIAZENIE": overload} if overload else {}

    def ai_enabled_for(self, user_id: str) -> bool:
        """The language model is used for this person (else every feature uses its no-AI version)."""
        return self.ai_mode != "off" and self.ai_office and user_id not in self.ai_off_for

    def hr_partner_enabled_for(self, user_id: str) -> bool:
        return self.hr_partner_office and user_id not in self.hr_partner_off_for

    def assistant_for(self, user_id: str) -> AiSuggestionService:
        """The assistant with the model, or – AI switched off for this person – the same service without it."""
        if self.ai_enabled_for(user_id):
            return self.assistant
        if self._assistant_off is None:
            self._assistant_off = build_assistant("off")
            self._assistant_off.rules = self.evaluations.rules
        return self._assistant_off

    def refresh_rules(self) -> None:
        """The version of the regulation in force today becomes the current rule book (new cycles, dictionaries,
        the assistant's texts); every cycle keeps computing by its own version (EvaluationService.rules_for)."""
        today = self.clock.today()
        current = self.rule_versions.at(today)
        self.rule_overrides = dict(current.values)
        rb = self.rule_versions.rulebook(current.id)
        self.evaluations.rules = rb
        self.evaluations.version_at = lambda day: self.rule_versions.at(day).id
        self.evaluations.rulebook_of = self.rule_versions.rulebook
        self.assistant.rules = rb
        if self._assistant_off is not None:
            self._assistant_off.rules = rb

    def import_employees(self, employees: list[Employee]) -> None:
        self.directory.upsert(employees)
        self.imported_employees.update({e.id: e for e in employees})

    def rules_for(self, c) -> "RuleBook":
        """The rule book an evaluation is computed by (its version of the regulation)."""
        return self.evaluations.rules_for(c)

    def schedule_for(self, user_id: str) -> ReminderSchedule:
        """The user's own reminder schedule, else the office default (config/ustawienia_urzedu.json)."""
        return self.reminder_prefs.get(user_id, self.settings.reminders)

    def active_deputies(self, evaluator_id: str, day: date) -> set[str]:
        return {d.deputy_id for d in self.deputy_records if d.evaluator_id == evaluator_id and d.active_on(day)}

    def objection_reviewer(self, c) -> Reviewer:
        """Who decides an objection to this evaluation: the DG, or the edge cases (app/domain/objection.py)."""
        emp = self.directory.get(c.employee_id)
        head = next((e.id for e in self.directory.all() if emp and e.office == emp.office and e.is_office_head),
                    None)
        return objection_reviewer(self.settings.objection, c.employee_id, c.evaluator_id,
                                  bool(emp and emp.is_office_head), head)

    def reviewers(self) -> frozenset[str]:
        """Everyone who may have to decide an objection (reads every evaluation, like HR)."""
        p = self.settings.objection
        return frozenset({self.settings.objection_reviewer, p.director_general, p.superior_body})

    def policy(self) -> AccessPolicy:
        """Who may see / act on what today (app/domain/access.py), from the tree, settings and deputies."""
        today = self.clock.today()
        evaluators = {d.evaluator_id for d in self.deputy_records}
        return AccessPolicy(
            evaluator_of={e.id: e.evaluator_id for e in self.directory.all()},
            scope=self.settings.visibility_scope,
            deputies={ev: frozenset(self.active_deputies(ev, today)) for ev in evaluators},
            # the reviewers of objections read all; accounts with the admin flag (AUTH_MODE=session)
            admins=frozenset({HR}) | self.reviewers() | _account_admins(),
        )

    def notes_of(self, evaluation_id: int, include_withheld: bool = False) -> list[NoteRecord]:
        """Notes of the evaluation – without the previous evaluator's notes they have not handed over."""
        return [r for r in self.notes.values() if r.evaluation_id == evaluation_id
                and (include_withheld or not r.withheld)]

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


def _account_admins() -> frozenset[str]:
    from app.api.auth import admin_employee_ids  # late: auth imports backend.db

    return admin_employee_ids()


def _empty_state(today: date | None, ai_mode: str | None, scenario: bool, first_cycle_id: int = 1) -> DemoState:
    ids = itertools.count(first_cycle_id)
    clock = SystemClock() if is_production() else FixedClock(today or (DEMO_TODAY if scenario else date.today()))
    directory = KprmEmployeeDirectory()
    evaluations = EvaluationService(kprm_rulebook(), InMemoryCycleRepository(), directory, clock,
                                    new_id=lambda: str(next(ids)))
    mode = (ai_mode or config.AI_MODE).lower()
    st = DemoState(clock, directory, evaluations, build_assistant(mode), mode)
    evaluations.deputies = st.active_deputies  # deputies may act on the evaluator's behalf (use_cases)
    evaluations.objection_reviewer = st.settings.objection_reviewer
    evaluations.objection_reviewer_for = lambda c: st.objection_reviewer(c).id
    evaluations.sheet_mapping = kprm.sheets().get("dobor_arkusza")
    st.refresh_rules()
    from app.infrastructure.eakt import build_exporter

    st.exporter = build_exporter(config.EAKT_MODE, config.EAKT_DIR, config.EAKT_URL, config.EAKT_TOKEN)
    evaluations.on_final.append(st.export_to_eakt)
    return st


def is_production() -> bool:
    """APP_MODE=production: system clock, no demo endpoints, no demo data (backend/config.py)."""
    return config.APP_MODE == "production"


def build_state(today: date | None = None, ai_mode: str | None = None, scenario: bool = False) -> DemoState:
    st = _empty_state(today, ai_mode, scenario)
    if is_production():
        return st  # the office's real data comes from the HR import, never from the demo seed
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

    from app.application import assistant, legacy_import, personnel_export
    from app.api import legacy_import as legacy_api
    from app.domain import (access, cycle, deadlines, employee, notes, reminder_schedule, scoring, wellbeing,
                            worktime_signals)

    mods = [cycle, deadlines, scoring, notes, reminder_schedule, access, employee, assistant, wellbeing,
            worktime_signals, regulations, personnel_export, legacy_import, legacy_api, sys.modules[__name__]]
    types = [obj for m in mods for _, obj in inspect.getmembers(m, inspect.isclass)
             if obj.__module__ == m.__name__ and (dataclasses.is_dataclass(obj) or issubclass(obj, Enum))]
    return JsonCodec(types)


_store: SqlStateStore | None = None
_archive = None  # SqlArchiveStore, created on first use


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
              "reguly_nadpisane": dict(st.rule_overrides), "zmiany_regul": list(st.rule_changes),
              "wersje_regul": list(st.rule_versions.versions),
              "ai_urzad": st.ai_office, "hr_partner_urzad": st.hr_partner_office,
              "ai_wylaczone": set(st.ai_off_for), "hr_partner_wylaczony": set(st.hr_partner_off_for),
              "pracownicy_import": list(st.imported_employees.values()),
              "nieobecnosci_oceniajacych": list(st.evaluator_absences),
              "zmiany_oceniajacych": list(st.evaluator_changes),
              "email_wyslane": set(st.sent_email_keys), "email_wylaczony": set(st.email_off_for),
              "email_ostatnie_uruchomienie": st.notify_last_run,
              "dobrostan": dict(st.wellbeing), "rcp": st.worktime.all(), "eakt": dict(st.eakt_status),
              "import_ocen": dict(st.legacy_imports),
              **({"zakres_widocznosci": st.settings.visibility_scope}
                 if st.settings.visibility_scope != load_office_settings().visibility_scope else {}),
              # office default changed by HR in the app (else the file config/ustawienia_urzedu.json applies)
              **({"przypomnienia_urzedu": st.settings.reminders}
                 if st.settings.reminders != load_office_settings().reminders else {})},
    )


def restore(snap: Snapshot, ai_mode: str | None = None) -> DemoState:
    last_cycle = max((int(c.id) for c in snap.cycles if str(c.id).isdigit()), default=0)
    st = _empty_state(snap.meta.get("dzis"), ai_mode, scenario=False, first_cycle_id=last_cycle + 1)  # demo clock
    st.import_employees(list(snap.meta.get("pracownicy_import", [])))  # before the cycles: they refer to people
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
    if "zakres_widocznosci" in snap.meta:
        st.settings = dataclasses.replace(st.settings, visibility_scope=snap.meta["zakres_widocznosci"])
    st.rule_changes = list(snap.meta.get("zmiany_regul", []))
    if "wersje_regul" in snap.meta:
        st.rule_versions = regulations.RuleVersions(list(snap.meta["wersje_regul"]))
    elif snap.meta.get("reguly_nadpisane"):  # saved before versioning: one version, in force since forever
        st.rule_versions = regulations.RuleVersions([regulations.RuleVersion(
            1, date.min, dict(snap.meta["reguly_nadpisane"]), {}, "zmiany sprzed wersjonowania", "kadry", None)])
    st.refresh_rules()
    st.ai_office = snap.meta.get("ai_urzad", True)
    st.hr_partner_office = snap.meta.get("hr_partner_urzad", True)
    st.ai_off_for = set(snap.meta.get("ai_wylaczone", set()))
    st.hr_partner_off_for = set(snap.meta.get("hr_partner_wylaczony", set()))
    st.evaluator_absences = list(snap.meta.get("nieobecnosci_oceniajacych", []))
    st.evaluator_changes = list(snap.meta.get("zmiany_oceniajacych", []))
    st.sent_email_keys = set(snap.meta.get("email_wyslane", set()))
    st.email_off_for = set(snap.meta.get("email_wylaczony", set()))
    st.notify_last_run = snap.meta.get("email_ostatnie_uruchomienie")
    st.wellbeing = dict(snap.meta.get("dobrostan", {}))
    st.worktime = InMemoryWorkTimeStore(snap.meta.get("rcp", []))
    st.eakt_status = dict(snap.meta.get("eakt", {}))
    st.legacy_imports = dict(snap.meta.get("import_ocen", {}))
    return st


def save_state() -> None:
    """Called after every successful change (middleware in backend/main.py) and after background work."""
    if _state is not None:
        store().save(snapshot(_state))


_state: DemoState | None = None


def get_state() -> DemoState:
    """FastAPI dependency. Loads the saved state from the database; an empty database gets the demo scenario
    (production: stays empty)."""
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
    _state.archive_store().clear()  # a fresh scenario starts with an empty archive
    return _state
