"""Demo state of the Streamlit app: one EvaluationService per browser session, seeded with cycles in every
stage of the process, plus frontend-only stores (notes, employee requests, meeting invitations) until the
backend has repositories for them. Nothing here contains business rules – those live in app/domain.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import streamlit as st

from app.application.assistant import AiSuggestionService
from app.application.use_cases import EvaluationService
from app.domain.cycle import EvaluationCycle, Status
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.errors import DomainError
from app.domain.notes import Note, Sentiment
from app.infrastructure.assistant_factory import build_assistant
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository

# ---- process stages shown in the UI (the domain has statuses; the UI groups them into 5 stages) ----------
STAGES = (
    "Rozmowa rozpoczynająca",
    "Ocenianie",
    "Rozmowa oceniająca",
    "Arkusz",
    "Zapoznanie i podpis",
)
DONE = len(STAGES) + 1  # cycle finished (evaluation acknowledged)

REQUEST_KINDS = {
    "ZMIANA_TERMINU": "Zmiana terminu oceny",
    "SPRZECIW": "Sprzeciw od oceny (do dyrektora generalnego)",
}
REQUEST_STATUS = {"ZLOZONY": "⏳ w rozpatrzeniu", "PRZYJETY": "✔ przyjęty", "ODRZUCONY": "✖ odrzucony"}


@dataclass
class EmployeeRequest:
    id: str
    employee_id: str
    cycle_id: str
    kind: str  # REQUEST_KINDS key
    text: str
    created: date
    status: str = "ZLOZONY"
    decided: date | None = None


@dataclass
class DemoState:
    service: EvaluationService
    assistant: AiSuggestionService
    clock: FixedClock
    employees: KprmEmployeeDirectory
    notes: dict[str, list[Note]] = field(default_factory=dict)  # cycle id -> notes
    requests: list[EmployeeRequest] = field(default_factory=list)
    invites: dict[tuple[str, int], datetime] = field(default_factory=dict)  # (cycle id, stage) -> meeting
    review_started: set[str] = field(default_factory=set)  # cycles moved from "Ocenianie" to the review meeting
    grade_request: dict[str, dict] = field(default_factory=dict)  # cycle id -> part III of the sheet (frontend only)
    dismissed: set[str] = field(default_factory=set)  # dismissed HR partner cards
    ai_cache: dict[str, object] = field(default_factory=dict)

    # ---- lookups ---------------------------------------------------------------------------------
    @property
    def today(self) -> date:
        return self.clock.today()

    def employee(self, employee_id: str) -> Employee:
        return self.employees.get(employee_id)

    def evaluated(self) -> list[Employee]:
        return [e for e in self.employees.all() if e.evaluator_id]

    def cycle_for(self, employee_id: str) -> EvaluationCycle | None:
        cycles = [c for c in self.service.cycles.list_all() if c.employee_id == employee_id]
        open_ = [c for c in cycles if c.status is not Status.ACKNOWLEDGED]
        if open_:
            return open_[0]
        return max(cycles, key=lambda c: c.acknowledged_on or date.min) if cycles else None

    def cycle(self, cycle_id: str) -> EvaluationCycle:
        return self.service.cycles.get(cycle_id)

    def absences(self, cycle: EvaluationCycle) -> list[Absence]:
        return list(cycle.absences)

    # ---- stages ----------------------------------------------------------------------------------
    def stage(self, cycle: EvaluationCycle) -> int:
        s = cycle.status
        if s in (Status.CYCLE_STARTED, Status.CRITERIA_SET):
            return 1
        if s is Status.CRITERIA_CONFIRMED:
            return 3 if cycle.id in self.review_started else 2
        if s is Status.MEETING_HELD:
            return 4
        if s is Status.EVALUATION_DONE:
            return 5
        return DONE

    def stage_status(self, cycle: EvaluationCycle, stage: int) -> tuple[str, str]:
        """(state, label) of one stage: state is done / active / waiting / todo."""
        current = self.stage(cycle)
        if stage < current:
            return "done", "zakończony"
        if stage > current:
            return "todo", "oczekuje"
        if stage == 1 and cycle.status is Status.CRITERIA_SET:
            return "waiting", "czeka na ocenianego"
        if stage == 5:
            return "waiting", "czeka na ocenianego"
        return "active", "w trakcie"

    def deadline_hint(self, cycle: EvaluationCycle) -> tuple[str, date | None]:
        """What the current stage is racing against."""
        stage = self.stage(cycle)
        if stage == 1:
            return "Termin wyznaczenia kryteriów", cycle.criteria_deadline
        if stage in (2, 3, 4):
            return "Termin sporządzenia oceny", self.service.evaluation_deadline(cycle.id)
        if stage == 5:
            return "Zapoznanie się z oceną", None
        return "Termin sprzeciwu", self.service.objection_deadline(cycle.id)

    # ---- notes -----------------------------------------------------------------------------------
    def add_note(self, cycle_id: str, text: str, on: date, author_id: str | None = None,
                 criterion_id: str | None = None, sentiment: Sentiment | None = None) -> Note:
        note = Note(uuid.uuid4().hex[:10], on, text.strip(), author_id, criterion_id, sentiment)
        self.notes.setdefault(cycle_id, []).append(note)
        return note

    def tag_note(self, cycle_id: str, note_id: str, criterion_id: str | None, sentiment: Sentiment | None,
                 indicator: str | None = None) -> None:
        notes = self.notes.get(cycle_id, [])
        for i, n in enumerate(notes):
            if n.id == note_id:
                notes[i] = Note(n.id, n.on, n.text, n.author_id, criterion_id, sentiment, indicator)

    def delete_note(self, cycle_id: str, note_id: str) -> None:
        self.notes[cycle_id] = [n for n in self.notes.get(cycle_id, []) if n.id != note_id]

    # ---- requests --------------------------------------------------------------------------------
    def submit_request(self, employee_id: str, cycle_id: str, kind: str, text: str) -> EmployeeRequest:
        req = EmployeeRequest(uuid.uuid4().hex[:8], employee_id, cycle_id, kind, text.strip(), self.today)
        self.requests.append(req)
        return req

    def decide_request(self, request_id: str, accept: bool) -> None:
        for r in self.requests:
            if r.id == request_id:
                r.status = "PRZYJETY" if accept else "ODRZUCONY"
                r.decided = self.today

    def pending_requests(self) -> list[EmployeeRequest]:
        return [r for r in self.requests if r.status == "ZLOZONY"]


# ---------------------------------------------------------------- seeding

def _seed_note(state: DemoState, cycle: EvaluationCycle, days_ago: int, text: str,
               criterion: str | None = None, sentiment: Sentiment | None = None) -> None:
    state.add_note(cycle.id, text, state.today - timedelta(days=days_ago), cycle.evaluator_id, criterion, sentiment)


def _run(state: DemoState, employee_id: str, start_ago: int, until: Status, additional: list[str],
         goals: list[str], scores: dict[str, int] | None = None, justification: str = "", iprz: str = "") -> EvaluationCycle:
    """Walk one cycle through the process with the clock set to plausible past dates."""
    real_today = state.today
    svc, clock = state.service, state.clock
    start = real_today - timedelta(days=start_ago)
    clock.set(start)
    cycle = svc.start_cycle(employee_id, start_date=start, after_negative=False)
    steps = [Status.CRITERIA_SET, Status.CRITERIA_CONFIRMED, Status.MEETING_HELD, Status.EVALUATION_DONE,
             Status.ACKNOWLEDGED]
    when = {
        Status.CRITERIA_SET: min(start + timedelta(days=12), real_today),
        Status.CRITERIA_CONFIRMED: min(start + timedelta(days=14), real_today),
        Status.MEETING_HELD: real_today - timedelta(days=12 if until is Status.ACKNOWLEDGED else 6),
        Status.EVALUATION_DONE: real_today - timedelta(days=9 if until is Status.ACKNOWLEDGED else 3),
        Status.ACKNOWLEDGED: real_today - timedelta(days=3),
    }
    try:
        for step in steps:
            if until is Status.CYCLE_STARTED:
                break
            clock.set(when[step])
            if step is Status.CRITERIA_SET:
                svc.set_criteria(cycle.id, cycle.evaluator_id, additional, goals)
            elif step is Status.CRITERIA_CONFIRMED:
                svc.confirm_criteria(cycle.id, cycle.employee_id)
            elif step is Status.MEETING_HELD:
                svc.record_review_meeting(cycle.id, cycle.evaluator_id, when[step])
            elif step is Status.EVALUATION_DONE:
                svc.submit_evaluation(cycle.id, cycle.evaluator_id, scores, justification, iprz)
            elif step is Status.ACKNOWLEDGED:
                svc.acknowledge(cycle.id, cycle.employee_id)
            if step is until:
                break
    finally:
        clock.set(real_today)
    return svc.cycles.get(cycle.id)


def _seed(state: DemoState) -> None:
    rules = state.service.rules

    def all_scores(employee_id: str, additional: list[str], values: list[int]) -> dict[str, int]:
        ids = list(rules.mandatory(state.employee(employee_id).sheet)) + additional
        return {cid: values[i % len(values)] for i, cid in enumerate(ids)}

    # 1. Main demo scenario: observation period, many notes, deadline in about a month.
    add = ["myslenie_analityczne", "orientacja_na_klienta"]
    g = _run(state, "grzegorz.wzor", 700, Status.CRITERIA_CONFIRMED, add,
             ["Terminowe przygotowywanie tłumaczeń dla departamentów merytorycznych",
              "Wdrożenie glosariusza terminów unijnych w referacie"])
    _seed_note(state, g, 160, "Przygotował glosariusz terminów unijnych i udostępnił go całemu referatowi – inni korzystają.",
               "wykorzystywanie_wiedzy", Sentiment.POSITIVE)
    _seed_note(state, g, 120, "Tłumaczenie rozporządzenia oddane z kilkoma błędami w numeracji przepisów, wymagało poprawek.",
               "rzetelnosc", Sentiment.NEGATIVE)
    _seed_note(state, g, 75, "Sam zaproponował harmonogram tłumaczeń na kwartał i dotrzymał wszystkich terminów.",
               "organizacja_pracy", Sentiment.POSITIVE)
    _seed_note(state, g, 50, "Został po godzinach trzeci raz w tym miesiącu, żeby skończyć pilne tłumaczenia dla gabinetu.")
    _seed_note(state, g, 40, "Przejął dodatkowe zadania po koleżance na urlopie macierzyńskim – nowy zakres to korespondencja z KE.")
    _seed_note(state, g, 21, "Pracował w weekend nad materiałami na posiedzenie, mówi, że jest zmęczony i nie wyrabia z zaległościami.")
    _seed_note(state, g, 14, "Bardzo jasno wyjaśnił interesantowi procedurę uwierzytelnienia tłumaczenia – podziękowanie mailowe.",
               "orientacja_na_klienta", Sentiment.POSITIVE)
    _seed_note(state, g, 6, "Świetnie poprowadził spotkanie z wydziałem prawnym, uzgodnił terminologię bez eskalacji.",
               "komunikacja", Sentiment.POSITIVE)

    # 2. New cycle: criteria not set yet.
    _run(state, "adam.wzor", 6, Status.CYCLE_STARTED, [], [])
    # 3. Criteria set, waiting for the evaluated person's confirmation.
    _run(state, "celina.przykladowa", 20, Status.CRITERIA_SET, ["kreatywnosc"],
         ["Uporządkowanie archiwum zakładowego za lata 2015–2018"])
    # 4. Review meeting held: the sheet is being filled in.
    e = _run(state, "ewelina.probka", 725, Status.MEETING_HELD, ["myslenie_analityczne"],
             ["Raport jakości danych co kwartał"])
    _seed_note(state, e, 90, "Raport kwartalny jakości danych oddany tydzień przed terminem, zarząd chwalił wnioski.",
               "myslenie_analityczne", Sentiment.POSITIVE)
    _seed_note(state, e, 30, "Pomogła nowej osobie w zespole wdrożyć się w narzędzia analityczne.",
               "wspolpraca", Sentiment.POSITIVE)
    # 5. Evaluation done, waiting for acknowledgement.
    _run(state, "roman.kowal", 728, Status.EVALUATION_DONE, ["podejmowanie_decyzji"], ["Opinie prawne w terminie 14 dni"],
         all_scores("roman.kowal", ["podejmowanie_decyzji"], [7, 7, 5, 7, 9, 7]),
         iprz="Szkolenie z legislacji UE; udział w zespole ds. deregulacji.")
    # 6. Observation period, deadline far away; has a pending request.
    k = _run(state, "adam.kowalik", 300, Status.CRITERIA_CONFIRMED, ["myslenie_analityczne"],
             ["Rozliczenie projektów FE w terminie"])
    state.submit_request("adam.kowalik", k.id, "ZMIANA_TERMINU",
                         "Proszę o wcześniejszy termin oceny – od marca przechodzę do innego biura.")
    state.requests[-1].created = state.today - timedelta(days=2)
    # 7. Finished and acknowledged – objection window open.
    _run(state, "janina.nowak", 735, Status.ACKNOWLEDGED, ["negocjowanie"], ["Skrócenie czasu obsługi wniosków"],
         all_scores("janina.nowak", ["negocjowanie"], [7, 7, 5, 9, 7, 5]),
         iprz="Program rozwoju menedżerskiego; mentoring dla nowego kierownika oddziału.")
    # 8. Sheet A, long absence extends the deadline.
    a = _run(state, "janina.kowalska", 400, Status.CRITERIA_CONFIRMED, ["kreatywnosc"],
             ["Program zwalczania ASF w powiecie"])
    state.service.register_absence(a.id, Absence(state.today - timedelta(days=110), state.today - timedelta(days=62),
                                                  "zwolnienie lekarskie"))


def new_state(today: date | None = None) -> DemoState:
    rules = kprm_rulebook()
    clock = FixedClock(today or date.today())
    employees = KprmEmployeeDirectory()
    service = EvaluationService(rules, InMemoryCycleRepository(), employees, clock)
    state = DemoState(service, build_assistant(), clock, employees)
    _seed(state)
    return state


def get_state() -> DemoState:
    if "demo" not in st.session_state:
        st.session_state.demo = new_state()
    return st.session_state.demo


def open_evaluation(employee_id: str, stage: int | None = None) -> None:
    """Go to the evaluation screen of one employee, on the given stage (default: the current one)."""
    st.session_state.view = "eval"
    st.session_state.eval_employee = employee_id
    state = get_state()
    cycle = state.cycle_for(employee_id)
    if cycle is not None:
        current = min(state.stage(cycle), len(STAGES))
        st.session_state[f"sel_{cycle.id}"] = stage or current
        st.session_state[f"seen_{cycle.id}"] = state.stage(cycle)


def change_sheet(state: DemoState, cycle_id: str, sheet: str) -> list[str]:
    """Frontend-only workaround until the backend has a use case for it: the evaluator overrides the sheet
    suggested from the position while the criteria can still be edited. Returns problems (empty = done)."""
    from app.domain.scoring import validate_additional_criteria

    cycle = state.cycle(cycle_id)
    if not cycle.is_editable("additional_criteria"):
        return ["Arkusz można zmienić tylko przed potwierdzeniem kryteriów przez ocenianego."]
    rules = state.service.rules
    rules.mandatory(sheet)  # validates the sheet
    cycle.additional_criteria = [c for c in cycle.additional_criteria if c not in rules.mandatory(sheet)]
    if problems := validate_additional_criteria(sheet, cycle.additional_criteria, rules):
        return problems
    cycle.sheet = sheet
    state.service.cycles.save(cycle)
    return []


def reset_state() -> None:
    st.session_state.pop("demo", None)


def ics_invite(title: str, start: datetime, minutes: int, description: str) -> bytes:
    """Calendar invitation (.ics) – opens in Outlook, Thunderbird, Google Calendar."""
    fmt = "%Y%m%dT%H%M%S"
    end = start + timedelta(minutes=minutes)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cyfrowy Asystent Ocen Okresowych//PL", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@asystent-ocen", f"DTSTAMP:{datetime.now():{fmt}}",
        f"DTSTART:{start:{fmt}}", f"DTEND:{end:{fmt}}", f"SUMMARY:{title}",
        "DESCRIPTION:" + description.replace("\n", "\\n"), "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines).encode("utf-8")


def default_meeting(today: date) -> datetime:
    return datetime.combine(today + timedelta(days=3), time(10, 0))


def safe(action, *args, **kwargs):
    """Run a use case; domain errors become (None, [messages]) for the UI."""
    try:
        return action(*args, **kwargs), []
    except DomainError as e:
        return None, list(getattr(e, "problems", None) or [str(e)])
