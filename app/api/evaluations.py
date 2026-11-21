"""Evaluation sheet, dashboard and demo endpoints (docs/api.md) – what the web UI (frontend/web) uses.

Thin: every rule (average, level, outcome, deadlines, locks, allowed actions) comes from the domain; this
module looks things up, calls the services and shapes the contract schemas.
Identity on the demo: `X-User-Id` = employee id from pracownicy.json (e.g. `henryk.pryncypal`) or `kadry`
(HR: sees everything, acts on nothing). Without the header the caller is treated like HR.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Response

from app.domain.cycle import EDITABLE_IN, TRANSITIONS, EvaluationCycle, Status
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.errors import NotAuthorized, NotFound, ValidationError
from app.domain.evidence_hint import suggest_points
from app.domain.notes import Note, evidence_by_criterion
from app.domain.scoring import EvaluationResult, Outcome, compute_result
from app.domain.timeline import deadlines_of

from . import assistant_mapping as m
from . import schemas as s
from .errors import ApiProblem
from .access import actor as _actor
from .access import require_read, require_working_material
from .state import HR, AbsenceRecord, DeadlineChangeRecord, DemoState, get_state, reset_state

router = APIRouter(prefix="/api")


STATUS_MAP = {
    Status.CYCLE_STARTED: s.StatusOceny.KRYTERIA_DO_WYZNACZENIA,
    Status.CRITERIA_SET: s.StatusOceny.KRYTERIA_DO_POTWIERDZENIA,
    Status.CRITERIA_CONFIRMED: s.StatusOceny.OKRES_OCENY,
    Status.MEETING_HELD: s.StatusOceny.ROZMOWA_OCENIAJACA,
    Status.EVALUATION_DONE: s.StatusOceny.OCENA_DO_ZAPOZNANIA,
    Status.ACKNOWLEDGED: s.StatusOceny.ZAKONCZONA,
    Status.OBJECTION: s.StatusOceny.SPRZECIW,
}

# API action -> (domain step, who performs it)
ACTIONS = {
    s.Akcja.ZATWIERDZ_KRYTERIA: ("set_criteria", "evaluator"),
    s.Akcja.POTWIERDZ_KRYTERIA: ("confirm_criteria", "employee"),
    s.Akcja.ROZPOCZNIJ_ROZMOWE: ("record_review_meeting", "evaluator"),
    s.Akcja.ZATWIERDZ_OCENE: ("submit_evaluation", "evaluator"),
    s.Akcja.POTWIERDZ_ZAPOZNANIE: ("acknowledge", "employee"),
    s.Akcja.ZLOZ_SPRZECIW: ("file_objection", "employee"),
    s.Akcja.ROZPATRZ_SPRZECIW: ("decide_objection", "reviewer"),  # director general (office setting)
}

# API field (EvaluationOut / EvaluationPatch) <-> domain field
FIELDS = {
    "kryteria_dodatkowe": "additional_criteria",
    "termin_oceny": "deadline_override",
    "data_rozmowy_oceniajacej": "meeting_date",
    "okres_od": "period_from",
    "okres_do": "period_to",
    "punkty": "scores",
    "uzasadnienie": "justification",
    "wnioski_iprz": "iprz_conclusions",
    "poprzednia_ocena": "previous_evaluation",
}
FIELDS_BACK = {v: k for k, v in FIELDS.items()}

NEXT_STEP = {
    Status.CYCLE_STARTED: ("Wyznacz kryteria", "OCENIAJACY"),
    Status.CRITERIA_SET: ("Potwierdzenie kryteriów", "OCENIANY"),
    Status.CRITERIA_CONFIRMED: ("Przeprowadź rozmowę oceniającą", "OCENIAJACY"),
    Status.MEETING_HELD: ("Sporządź ocenę", "OCENIAJACY"),
    Status.EVALUATION_DONE: ("Zapoznanie się z oceną", "OCENIANY"),
    Status.ACKNOWLEDGED: (None, "NIKT"),
    Status.OBJECTION: ("Rozpatrz sprzeciw", "KADRY"),
}


# ---------------------------------------------------------------- helpers

def _dt(d: date | None) -> datetime | None:
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc) if d else None


def _osoba(st: DemoState, e: Employee | None) -> s.OsobaRef:
    if e is None:
        return s.OsobaRef(id=0, imie="", nazwisko="")
    return s.OsobaRef(id=st.employee_number(e.id), imie=e.first_name, nazwisko=e.last_name, stanowisko=e.position)


def _employee_out(st: DemoState, e: Employee) -> s.EmployeeOut:
    boss = st.directory.get(e.evaluator_id) if e.evaluator_id else None
    return s.EmployeeOut(
        id=st.employee_number(e.id), imie=e.first_name, nazwisko=e.last_name, email=f"{e.id}@urzad.example",
        stanowisko=e.position, komorka=e.unit, arkusz=s.Arkusz(e.sheet),
        # pracownicy.json has no civil-servant status (its "zalozenia_demo"): the demo assumes PRACOWNIK
        typ_zatrudnienia=s.TypZatrudnienia.PRACOWNIK,
        przelozony=_osoba(st, boss) if boss else None, rola=s.Rola.PRACOWNIK, aktywny=True,
    )


def _cycle(st: DemoState, evaluation_id: int, actor: str) -> EvaluationCycle:
    c = st.evaluations.cycles.get(str(evaluation_id))
    if c is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    require_read(st, actor, c)
    return c


def _notes(st: DemoState, c: EvaluationCycle) -> list[Note]:
    return [r.note for r in st.notes_of(int(c.id))]


def _live_result(st: DemoState, c: EvaluationCycle) -> EvaluationResult | None:
    if c.result is not None:
        return c.result
    ids = c.criteria_ids(st.evaluations.rules)
    if ids and all(c.scores.get(i) is not None for i in ids):
        return compute_result([c.scores[i] for i in ids], st.evaluations.rules)
    return None


def _wynik(result: EvaluationResult | None) -> s.Wynik | None:
    if result is None:
        return None
    return s.Wynik.POZYTYWNA if result.outcome is Outcome.POSITIVE else s.Wynik.NEGATYWNA


def _criteria_out(st: DemoState, c: EvaluationCycle) -> list[s.EvaluationCriterionOut]:
    rules = st.evaluations.rules
    ids = c.criteria_ids(rules)
    mandatory = set(rules.mandatory(c.sheet))
    ev = evidence_by_criterion(_notes(st, c), ids)
    out = []
    for i, cid in enumerate(ids, start=1):
        e = ev[cid]
        hint = suggest_points(len(e.positive), len(e.negative), list(rules.scale))
        out.append(s.EvaluationCriterionOut(
            criterion_kod=m.criterion_code(cid), nazwa=rules.criterion_name(cid),
            typ=s.TypKryterium.OBOWIAZKOWE if cid in mandatory else s.TypKryterium.DODATKOWE,
            kolejnosc=i, punkty=c.scores.get(cid), sugerowane_punkty=hint.points if hint else None,
            liczba_dowodow={s.Wydzwiek.POZYTYWNY: len(e.positive), s.Wydzwiek.NEUTRALNY: len(e.neutral),
                            s.Wydzwiek.NEGATYWNY: len(e.negative)},
        ))
    return out


def _validations(st: DemoState, c: EvaluationCycle) -> list[s.Walidacja]:
    """Current blocking problems for submitting the evaluation (rules from the domain's rule book)."""
    if c.status is not Status.MEETING_HELD:
        return []
    rules = st.evaluations.rules
    out: list[s.Walidacja] = []
    for cid in c.criteria_ids(rules):
        if c.scores.get(cid) is None:
            out.append(s.Walidacja(kod="BRAK_OCENY", pole=f"kryteria.{m.criterion_code(cid)}", waga=s.Waga.BLAD,
                                   komunikat=f"Brak oceny cząstkowej: {rules.criterion_name(cid)}."))
    result = _live_result(st, c)
    if (result is not None and result.outcome is Outcome.NEGATIVE
            and rules.justification_required_if_negative and not c.justification.strip()):
        out.append(s.Walidacja(kod="UZASADNIENIE_WYMAGANE", pole="uzasadnienie", waga=s.Waga.BLAD,
                               komunikat="Uzasadnienie oceny jest obowiązkowe przy ocenie negatywnej (§ 11 ust. 3)."))
    if rules.iprz_required and not c.iprz_conclusions.strip():
        out.append(s.Walidacja(kod="IPRZ_WYMAGANE", pole="wnioski_iprz", waga=s.Waga.BLAD,
                               komunikat="Wnioski dotyczące indywidualnego programu rozwoju zawodowego są obowiązkowe."))
    return out


def _allowed_actions(c: EvaluationCycle, actor: str, as_evaluator: bool, reviewer: str) -> list[s.Akcja]:
    """`as_evaluator`: the evaluator or their active deputy (access policy); managers above only read.
    `reviewer`: who decides objections (office setting)."""
    out = []
    for akcja, (step, who) in ACTIONS.items():
        allowed = {"evaluator": as_evaluator, "employee": actor == c.employee_id, "reviewer": actor == reviewer}[who]
        # set_criteria may repeat while not confirmed, but "approve criteria" is offered only once
        repeat = step == "set_criteria" and c.status is Status.CRITERIA_SET
        if allowed and c.status in TRANSITIONS[step][0] and not repeat:
            out.append(akcja)
    return out


def _editable(c: EvaluationCycle, as_evaluator: bool) -> list[str]:
    if not as_evaluator:
        return []
    return [FIELDS_BACK[f] for f, statuses in EDITABLE_IN.items() if c.status in statuses and f in FIELDS_BACK]


def _objection_out(st: DemoState, c: EvaluationCycle) -> s.SprzeciwOut | None:
    if c.objection_filed_on is None:
        return None
    rules, cal = st.evaluations.rules, st.evaluations.calendar
    return s.SprzeciwOut(zlozony=c.objection_filed_on, tresc=c.objection_text,
                         termin_rozpatrzenia=c.objection_review_deadline(rules, cal), decyzja=c.objection_decision,
                         rozstrzygnieto=c.objection_decided_on, uzasadnienie_decyzji=c.objection_reason,
                         termin_odwolania_do_sadu=c.labour_court_deadline(rules, cal))


def _podpis(st: DemoState, day: date | None, who: Employee | None) -> s.Podpis:
    return s.Podpis(at=_dt(day), osoba=_osoba(st, who) if (day and who) else None)


def _evaluation_out(st: DemoState, c: EvaluationCycle, actor: str) -> s.EvaluationOut:
    as_evaluator = st.policy().can_act_as_evaluator(actor, c.employee_id, c.evaluator_id)
    emp = st.directory.get(c.employee_id)
    boss = st.directory.get(c.evaluator_id)
    result = _live_result(st, c)
    ver = st.version_of(c.id)
    svc = st.evaluations
    return s.EvaluationOut(
        id=int(c.id), wersja=ver.version, status=STATUS_MAP[c.status], arkusz=s.Arkusz(c.sheet),
        urzad=emp.office, oceniany=_employee_out(st, emp), oceniajacy=_osoba(st, boss),
        kryteria=_criteria_out(st, c),
        czesc_i=s.CzescI(
            data_wyznaczenia_kryteriow=c.criteria_set_on,
            termin_oceny=c.evaluation_deadline(svc.rules, svc.calendar),
            termin_wyznaczenia_kryteriow=c.criteria_deadline,
            potw_oceniajacy=_podpis(st, c.criteria_set_on, boss),
            potw_oceniany=_podpis(st, c.criteria_confirmed_on, emp),
        ),
        czesc_ii=s.CzescII(
            data_rozmowy_oceniajacej=c.meeting_date, okres_od=c.period_from, okres_do=c.period_to,
            srednia=result.average_display if result else None,
            poziom=m.level(result.level) if result else None, wynik=_wynik(result),
            uzasadnienie=c.justification or None, wnioski_iprz=c.iprz_conclusions or None,
            poprzednia_ocena=m.previous(c.previous_evaluation or emp.previous_evaluation),
            wniosek_o_stopien=s.WniosekOStopien.NIE_DOTYCZY,
            data_sporzadzenia=_dt(c.evaluated_on), podpis_oceniajacego=_podpis(st, c.evaluated_on, boss),
            zapoznanie=_podpis(st, c.acknowledged_on, emp),
            termin_sprzeciwu=c.objection_deadline(svc.rules, svc.calendar),
        ),
        jako_oceniajacy=as_evaluator,
        sprzeciw=_objection_out(st, c),
        dozwolone_akcje=_allowed_actions(c, actor, as_evaluator, st.settings.objection_reviewer), edytowalne_pola=_editable(c, as_evaluator),
        walidacje=_validations(st, c), updated_at=ver.updated_at,
        terminy=[s.TerminOut(rodzaj=d.kind, nazwa=d.label, data=d.due, podstawa=d.basis, stan=d.state,
                             spelniony_at=d.done_on, opis=d.note)
                 for d in deadlines_of(c, svc.rules, svc.calendar, st.clock.today())],
    )


def _urgency(days: int | None) -> str:
    if days is None:
        return "OK"
    if days < 0:
        return "PO_TERMINIE"
    if days <= 7:
        return "PILNE"
    if days <= 30:
        return "WKROTCE"
    return "OK"


# ---------------------------------------------------------------- session & dictionaries

@router.get("/users", tags=["demo"])
def users(st: DemoState = Depends(get_state)) -> list[dict]:
    """Demo only: identities to switch between (no real login). `id` goes into X-User-Id."""
    people = st.directory.all()
    out = [{"id": HR, "nazwa": "Dział kadr", "opis": "Kadry – cały urząd"}]
    for e in people:
        role = "Oceniający" if any(x.evaluator_id == e.id for x in people) else "Oceniany"
        out.append({"id": e.id, "nazwa": e.full_name, "opis": f"{role} – {e.position}"})
    return out


@router.get("/me", response_model=s.UserContext, tags=["sesja"])
def me(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> s.UserContext:
    actor = _actor(st, x_user_id)
    if actor == HR:
        return s.UserContext(pracownik=s.OsobaRef(id=0, imie="Dział", nazwisko="kadr"), rola=s.Rola.KADRY,
                             czy_oceniajacy=False, urzad="Wszystkie urzędy (dane przykładowe)")
    e = st.directory.get(actor)
    policy = st.policy()
    visible = policy.visible_employees(actor)  # subtree or direct reports (office setting), incl. as a deputy
    subs = [st.employee_number(x.id) for x in st.directory.all() if x.id in visible]
    evaluates = any(policy.can_act_as_evaluator(actor, x.id, x.evaluator_id) for x in st.directory.all())
    return s.UserContext(pracownik=_osoba(st, e), rola=s.Rola.PRACOWNIK, czy_oceniajacy=evaluates,
                         podwladni_ids=subs, urzad=e.office)


@router.get("/criteria", response_model=list[s.CriterionOut], tags=["słowniki"])
def criteria(arkusz: s.Arkusz | None = None, st: DemoState = Depends(get_state)) -> list[s.CriterionOut]:
    rules = st.evaluations.rules
    mandatory = set(rules.mandatory(arkusz.value)) if arkusz else set()
    out = []
    for c in sorted(rules.criteria.values(), key=lambda c: c.number):
        typ = None
        if arkusz:
            typ = s.TypKryterium.OBOWIAZKOWE if c.id in mandatory else s.TypKryterium.DODATKOWE
        out.append(s.CriterionOut(kod=m.criterion_code(c.id), nazwa=c.name, opis="", wskazniki=list(c.indicators),
                                  typ_dla_arkusza=typ, kolejnosc=c.number))
    return out


@router.get("/dashboard", response_model=s.DashboardOut, tags=["sesja"])
def dashboard(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> s.DashboardOut:
    actor = _actor(st, x_user_id)
    svc = st.evaluations
    today = st.clock.today()
    visible = st.policy().visible_employees(actor)  # HR: everyone; manager: subtree / direct reports (setting)
    people = [e for e in st.directory.all() if e.evaluator_id and e.id in visible]
    items = []
    all_cycles = svc.cycles.list_all()
    for e in people:
        # one row per evaluation: a finished one stays (its year, its result) next to the cycle that followed it
        mine = sorted((x for x in all_cycles if x.employee_id == e.id), key=lambda x: (x.start_date, int(x.id)))
        if not mine:
            items.append(s.DashboardItem(evaluation_id=None, oceniany=_osoba(st, e), arkusz=s.Arkusz(e.sheet),
                                         status=None, nastepny_krok="Rozpocznij cykl oceny", kto_dziala="KADRY",
                                         termin=None, dni_do_terminu=None, komorka=e.unit))
            continue
        for c in mine:
            items.append(_dashboard_item(st, e, c, today))
    return s.DashboardOut(pozycje=items, nieprzeczytane_powiadomienia=0)


def _dashboard_item(st: DemoState, e: Employee, c: EvaluationCycle, today: date) -> s.DashboardItem:
    svc = st.evaluations
    step, who = NEXT_STEP[c.status]
    deadline = c.evaluation_deadline(svc.rules, svc.calendar)
    if c.status in (Status.CYCLE_STARTED, Status.CRITERIA_SET):
        due = c.criteria_deadline
    elif c.status in (Status.CRITERIA_CONFIRMED, Status.MEETING_HELD):
        due = deadline
    elif c.status is Status.OBJECTION:
        due = c.objection_review_deadline(svc.rules, svc.calendar)
    else:
        due = None
    days = (due - today).days if due else None
    done = c.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION)
    return s.DashboardItem(
        evaluation_id=int(c.id), oceniany=_osoba(st, e), arkusz=s.Arkusz(c.sheet), status=STATUS_MAP[c.status],
        nastepny_krok=step, kto_dziala=who, termin=due or deadline, dni_do_terminu=days, pilnosc=_urgency(days),
        wynik=_wynik(_live_result(st, c)) if done else None, komorka=e.unit, termin_oceny=deadline,
    )


# ---------------------------------------------------------------- the evaluation sheet

def _employee(st: DemoState, number: int) -> Employee:
    e = st.employee_by_number(number)
    if e is None:
        raise NotFound(f"Nie ma pracownika o identyfikatorze {number}.")
    return e


@router.post("/evaluations", response_model=s.EvaluationOut, status_code=201, tags=["ocena"])
def create_evaluation(body: s.EvaluationCreate, x_user_id: str | None = Header(default=None),
                      st: DemoState = Depends(get_state)) -> s.EvaluationOut:
    """Start a cycle (UC1). Sheet, evaluator, mandatory criteria and deadlines come from the server.
    Allowed for HR and for the employee's own evaluator; one open cycle per person (else 409)."""
    actor = _actor(st, x_user_id)
    emp = _employee(st, body.oceniany_id)
    if actor != HR and not st.policy().can_act_as_evaluator(actor, emp.id, emp.evaluator_id):
        raise NotAuthorized("Cykl oceny może rozpocząć dział kadr albo oceniający pracownika (lub jego zastępca).")
    if not emp.evaluator_id:
        raise ApiProblem(409, "BRAK_OCENIAJACEGO", f"{emp.full_name} nie ma przypisanego oceniającego.")
    if st.evaluations.cycles.find_open_for(emp.id) is not None:
        raise ApiProblem(409, "CYKL_OTWARTY", f"{emp.full_name} ma już otwarty cykl oceny.")
    c = st.evaluations.start_cycle(emp.id, start_date=body.data_poczatku_cyklu)
    st.touch(c.id)
    return _evaluation_out(st, c, actor)


@router.get("/evaluations/{evaluation_id}", response_model=s.EvaluationOut, tags=["ocena"])
def get_evaluation(evaluation_id: int, x_user_id: str | None = Header(default=None),
                   st: DemoState = Depends(get_state)) -> s.EvaluationOut:
    actor = _actor(st, x_user_id)
    return _evaluation_out(st, _cycle(st, evaluation_id, actor), actor)


@router.patch("/evaluations/{evaluation_id}", response_model=s.EvaluationOut, tags=["ocena"])
def patch_evaluation(evaluation_id: int, body: s.EvaluationPatch, x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)) -> s.EvaluationOut:
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    if body.updated_at != st.version_of(c.id).updated_at:
        raise ApiProblem(409, "KONFLIKT_WERSJI", "Ocena została zmieniona w międzyczasie – odśwież widok.")
    changes: dict[str, Any] = {}
    for name, value in body.model_dump(exclude_unset=True, exclude={"updated_at"}).items():
        if name not in FIELDS:
            raise ApiProblem(409, "POLE_ZABLOKOWANE", f"Pola „{name}” nie można jeszcze zmieniać w tej wersji.")
        if name in ("uzasadnienie", "wnioski_iprz"):
            value = value or ""
        changes[FIELDS[name]] = value
    st.evaluations.edit(c.id, actor, **changes)
    st.touch(c.id)
    return _evaluation_out(st, st.evaluations.cycles.get(c.id), actor)


@router.put("/evaluations/{evaluation_id}/criteria/additional", response_model=s.EvaluationOut, tags=["ocena"])
def put_additional(evaluation_id: int, body: s.AdditionalCriteriaIn, x_user_id: str | None = Header(default=None),
                   st: DemoState = Depends(get_state)) -> s.EvaluationOut:
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    st.evaluations.edit(c.id, actor, additional_criteria=[m.criterion_id(k) for k in body.kody])
    st.touch(c.id)
    return _evaluation_out(st, st.evaluations.cycles.get(c.id), actor)


@router.put("/evaluations/{evaluation_id}/scores", response_model=s.ScoresOut, tags=["ocena"])
def put_scores(evaluation_id: int, body: s.ScoresIn, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> s.ScoresOut:
    """Live recalculation for the score matrix – rules only, no AI."""
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    scores = dict(c.scores)
    for code, pts in body.punkty.items():
        if pts is None:
            scores.pop(m.criterion_id(code), None)
        else:
            scores[m.criterion_id(code)] = pts
    st.evaluations.edit(c.id, actor, scores=scores)
    st.touch(c.id)
    c = st.evaluations.cycles.get(c.id)
    result = _live_result(st, c)
    return s.ScoresOut(srednia=result.average_display if result else None,
                       poziom=m.level(result.level) if result else None, wynik=_wynik(result),
                       kryteria=_criteria_out(st, c), walidacje=_validations(st, c))


@router.post("/evaluations/{evaluation_id}/actions/{akcja}", response_model=s.EvaluationOut, tags=["ocena"])
def action(evaluation_id: int, akcja: s.Akcja, body: s.ActionIn | None = None,
           x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> s.EvaluationOut:
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    if akcja not in ACTIONS:
        raise ApiProblem(409, "PRZEJSCIE_NIEDOZWOLONE", "Ta akcja nie jest jeszcze dostępna.")
    if akcja is s.Akcja.ZATWIERDZ_OCENE and (checks := _validations(st, c)):
        raise ApiProblem(422, "WALIDACJA", "Uzupełnij wymagane pola przed zatwierdzeniem oceny.", checks)
    svc = st.evaluations
    if akcja is s.Akcja.ZATWIERDZ_KRYTERIA:
        svc.set_criteria(c.id, actor, c.additional_criteria, c.goals, c.deadline_override)
    elif akcja is s.Akcja.POTWIERDZ_KRYTERIA:
        svc.confirm_criteria(c.id, actor)
    elif akcja is s.Akcja.ROZPOCZNIJ_ROZMOWE:
        svc.record_review_meeting(c.id, actor)
    elif akcja is s.Akcja.ZATWIERDZ_OCENE:
        svc.submit_evaluation(c.id, actor)
    elif akcja is s.Akcja.POTWIERDZ_ZAPOZNANIE:
        svc.acknowledge(c.id, actor)
    elif akcja is s.Akcja.ZLOZ_SPRZECIW:
        svc.file_objection(c.id, actor, (body.komentarz if body else None) or "")
    elif akcja is s.Akcja.ROZPATRZ_SPRZECIW:
        if actor != st.settings.objection_reviewer:
            raise NotAuthorized("Sprzeciw rozpatruje dyrektor generalny urzędu (art. 83 ust. 1) – w ustawieniach "
                                "urzędu wskazana osoba.")
        if body is None or body.uwzglednij is None:
            raise ValidationError(["Wybierz rozstrzygnięcie: sprzeciw uwzględniony albo nieuwzględniony."])
        svc.decide_objection(c.id, actor, body.uwzglednij, body.komentarz or "")
    st.touch(c.id)
    return _evaluation_out(st, svc.cycles.get(c.id), actor)


def _range_text(band, low: int) -> str:
    def n(x) -> str:
        return f"{float(x):g}".replace(".", ",")
    if band.lower_exclusive is None:
        return f"od {n(low)} do {n(band.upper_inclusive)} pkt"
    return f"powyżej {n(band.lower_exclusive)} do {n(band.upper_inclusive)} pkt"


def _sheet_pdf_data(st: DemoState, c: EvaluationCycle):
    from backend.sheet_pdf import Person, SheetPdf

    rules = st.evaluations.rules

    def person(e: Employee) -> Person:
        return Person(e.first_name, e.last_name, e.unit, e.position)

    emp = st.directory.get(c.employee_id)
    boss = st.directory.get(c.evaluator_id)
    mandatory = set(rules.mandatory(c.sheet))
    crit = [(rules.criterion_name(cid), c.scores.get(cid), cid in mandatory) for cid in c.criteria_ids(rules)]
    result = _live_result(st, c)
    return SheetPdf(
        sheet=c.sheet, office=emp.office, employee=person(emp),
        evaluator=person(boss) if boss else Person(c.evaluator_id, ""),
        scale=sorted(rules.scale.items()),
        levels=[(b.level, _range_text(b, min(rules.scale))) for b in rules.level_bands],
        mandatory=[(n, p) for n, p, mand in crit if mand], additional=[(n, p) for n, p, mand in crit if not mand],
        max_additional=rules.max_additional_criteria,
        deadline=st.evaluations.evaluation_deadline(c.id),
        criteria_set_on=c.criteria_set_on, criteria_confirmed_on=c.criteria_confirmed_on,
        meeting_date=c.meeting_date, period_from=c.period_from, period_to=c.period_to,
        average=result.average_display if result else None, level=result.level if result else None,
        positive=(result.outcome is Outcome.POSITIVE) if result else None,
        justification=c.justification, iprz=c.iprz_conclusions,
        civil_servant=False,  # pracownicy.json has no civil-servant status (demo assumes PRACOWNIK)
        evaluated_on=c.evaluated_on, acknowledged_on=c.acknowledged_on,
        objection_days=rules.objection_days,
        draft=c.status not in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED),
    )


@router.get("/evaluations/{evaluation_id}/pdf", response_class=Response, tags=["ocena"],
            responses={200: {"content": {"application/pdf": {}}}})
def pdf(evaluation_id: int, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    """Sheet A/B/C as PDF, laid out after the KPRM form (UC6). Before submission it is marked as a draft."""
    from backend.sheet_pdf import render_sheet_pdf

    c = _cycle(st, evaluation_id, _actor(st, x_user_id))
    data = render_sheet_pdf(_sheet_pdf_data(st, c))
    name = f"ocena-okresowa-{c.employee_id.replace('.', '-')}-{c.id}.pdf"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/evaluations/{evaluation_id}/evidence", response_model=s.EvidenceOut, tags=["notatki"])
def evidence(evaluation_id: int, x_user_id: str | None = Header(default=None),
             st: DemoState = Depends(get_state)) -> s.EvidenceOut:
    """Evidence map: tagged notes per criterion and a readable suggested score (never applied automatically)."""
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    require_working_material(st, actor, c, "Mapę dowodów z notatek widzi tylko oceniający (lub jego zastępca).")
    rules = st.evaluations.rules
    ids = c.criteria_ids(rules)
    ev = evidence_by_criterion(_notes(st, c), ids)
    out = []
    for cid in ids:
        e = ev[cid]
        hint = suggest_points(len(e.positive), len(e.negative), list(rules.scale))
        tagged = sorted([*e.positive, *e.neutral, *e.negative], key=lambda n: n.on, reverse=True)
        out.append(s.EvidenceCriterion(
            criterion_kod=m.criterion_code(cid), nazwa=rules.criterion_name(cid), plus=len(e.positive),
            neutralne=len(e.neutral), minus=len(e.negative), notatki_ids=[int(n.id) for n in tagged],
            sugerowane_punkty=hint.points if hint else None, uzasadnienie_sugestii=hint.reason if hint else None,
        ))
    records = st.notes_of(evaluation_id)
    return s.EvidenceOut(kryteria=out, notatki_do_przypisania=sum(1 for r in records if not r.note.criterion_id),
                         w_toku=sum(1 for r in records if r.status == "W_TOKU"))


# ---------------------------------------------------------------- HR partner (UC7)

@router.get("/evaluations/{evaluation_id}/hr-partner", response_model=s.HrPartnerOut, tags=["asystent"])
def hr_partner(evaluation_id: int, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> s.HrPartnerOut:
    """Hints for the manager (overload, long absence, change of duties, …) – never a diagnosis of the employee."""
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    require_working_material(st, actor, c, "Podpowiedzi HR partnera są tylko dla oceniającego (lub jego zastępcy).")
    if not st.hr_partner_enabled_for(actor):
        raise ApiProblem(409, "HR_PARTNER_WYLACZONY", "Wirtualny HR partner jest wyłączony (Ustawienia).")
    notes = _notes(st, c)
    ai_on = st.ai_enabled_for(actor)
    key = (tuple(n.id for n in notes), tuple(sorted(c.scores.items())), st.clock.today(), ai_on)
    cached = st.hr_reports.get(c.id)
    if cached is None or cached[0] != key:
        report = st.assistant_for(actor).hr_partner(c, st.directory.get(c.employee_id), notes, c.absences, st.clock.today())
        st.hr_reports[c.id] = (key, report)
    out = m.to_hr_partner_out(st.hr_reports[c.id][1])
    for sig in out.sygnaly:  # stable ids per (cycle, kind), so decisions survive recomputation
        sig.id = st.signal_id(c.id, sig.typ)
        sig.status = st.hr_decisions.get(sig.id, "NOWY")
    return out


@router.post("/hr-signals/{signal_id}/decision", status_code=204, tags=["asystent"])
def hr_decision(signal_id: int, body: s.HrSignalDecision, st: DemoState = Depends(get_state)) -> Response:
    if signal_id not in st.hr_signal_ids.values():
        raise NotFound("Nie znaleziono sygnału.")
    st.hr_decisions[signal_id] = body.status
    return Response(status_code=204)


# ---------------------------------------------------------------- demo only

# ---------------------------------------------------------------- absences and deadline changes (UC8)

ABSENCE_KIND = {  # API enum -> Polish label kept on the domain Absence (merged periods, HR partner texts)
    s.TypNieobecnosci.L4: "zwolnienie lekarskie",
    s.TypNieobecnosci.URLOP_WYPOCZYNKOWY: "urlop wypoczynkowy",
    s.TypNieobecnosci.URLOP_RODZICIELSKI: "urlop rodzicielski",
    s.TypNieobecnosci.INNA_USPRAWIEDLIWIONA: "inna usprawiedliwiona nieobecność",
    s.TypNieobecnosci.NIEUSPRAWIEDLIWIONA: "nieobecność nieusprawiedliwiona",
}


def _change_out(r: DeadlineChangeRecord) -> s.DeadlineChangeOut:
    return s.DeadlineChangeOut(id=r.id, powod=s.PowodZmianyTerminu(r.reason), stary_termin=r.old,
                               nowy_termin=r.new, status=s.StatusWniosku(r.status), uzasadnienie=r.justification,
                               decyzja_at=r.decided_at)


def _absence_out(st: DemoState, r: AbsenceRecord) -> s.AbsenceOut:
    change = next((x for x in st.deadline_changes if x.id == r.change_id), None)
    return s.AbsenceOut(id=r.id, od=r.absence.start, do=r.absence.end, typ=s.TypNieobecnosci(r.typ),
                        usprawiedliwiona=r.absence.justified, dni=r.absence.days, evaluation_id=int(r.cycle_id),
                        termin_oceny=r.deadline_after, zmiana_terminu=_change_out(change) if change else None)


@router.get("/employees/{employee_id}/absences", response_model=list[s.AbsenceOut], tags=["nieobecności"])
def list_absences(employee_id: int, x_user_id: str | None = Header(default=None),
                  st: DemoState = Depends(get_state)) -> list[s.AbsenceOut]:
    actor = _actor(st, x_user_id)
    e = _employee(st, employee_id)
    if not st.policy().can_read(actor, e.id, e.evaluator_id):
        raise NotAuthorized("Nie masz dostępu do nieobecności tego pracownika.")
    mine = [r for r in st.absences if r.employee_id == e.id]
    return [_absence_out(st, r) for r in sorted(mine, key=lambda r: r.absence.start, reverse=True)]


@router.post("/employees/{employee_id}/absences", response_model=s.AbsenceOut, status_code=201,
             tags=["nieobecności"])
def add_absence(employee_id: int, body: s.AbsenceIn, x_user_id: str | None = Header(default=None),
                st: DemoState = Depends(get_state)) -> s.AbsenceOut:
    """Register an absence of the evaluated person (UC8). A justified continuous absence longer than the
    threshold in reguly.json moves the evaluation deadline automatically (DeadlineChange AUTO, art. 81 ust. 7)."""
    actor = _actor(st, x_user_id)
    e = _employee(st, employee_id)
    if actor != HR and not st.policy().can_act_as_evaluator(actor, e.id, e.evaluator_id):
        raise NotAuthorized("Nieobecność może zgłosić dział kadr albo oceniający pracownika (lub jego zastępca).")
    if body.do < body.od:
        raise ValidationError(["Koniec nieobecności nie może być wcześniejszy niż jej początek."])
    c = st.evaluations.cycles.find_open_for(e.id)
    if c is None:
        raise ApiProblem(409, "BRAK_CYKLU", f"{e.full_name} nie ma otwartego cyklu oceny.")
    absence = Absence(body.od, body.do, ABSENCE_KIND[body.typ],
                      justified=body.typ is not s.TypNieobecnosci.NIEUSPRAWIEDLIWIONA)
    before = st.evaluations.evaluation_deadline(c.id)
    after = st.evaluations.register_absence(c.id, absence)
    st.touch(c.id)
    change_id = None
    if after != before:
        change_id = len(st.deadline_changes) + 1
        months = st.evaluations.rules.absence_extends_after_months
        st.deadline_changes.append(DeadlineChangeRecord(
            id=change_id, cycle_id=c.id, reason=s.PowodZmianyTerminu.NIEOBECNOSC_OCENIANEGO_AUTO.value,
            old=before, new=after, status=s.StatusWniosku.AUTO.value,
            justification=(f"Usprawiedliwiona nieobecność dłuższa niż {months} mies. przedłuża termin oceny "
                           "o czas jej trwania (art. 81 ust. 7 ustawy o służbie cywilnej)."),
            decided_at=datetime.now(timezone.utc)))
    r = AbsenceRecord(id=len(st.absences) + 1, employee_id=e.id, cycle_id=c.id, absence=absence,
                      typ=body.typ.value, deadline_after=after, change_id=change_id)
    st.absences.append(r)
    return _absence_out(st, r)


@router.get("/evaluations/{evaluation_id}/deadline-changes", response_model=list[s.DeadlineChangeOut],
            tags=["nieobecności"])
def deadline_changes(evaluation_id: int, x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)) -> list[s.DeadlineChangeOut]:
    c = _cycle(st, evaluation_id, _actor(st, x_user_id))
    return [_change_out(r) for r in st.deadline_changes if r.cycle_id == c.id]


@router.get("/demo/clock", response_model=s.ClockOut, tags=["demo"])
def get_clock(st: DemoState = Depends(get_state)) -> s.ClockOut:
    return s.ClockOut(dzis=st.clock.today(), nowe_powiadomienia=0)


@router.post("/demo/clock", response_model=s.ClockOut, tags=["demo"])
def set_clock(body: s.ClockIn, st: DemoState = Depends(get_state)) -> s.ClockOut:
    """„Przewiń czas”: moves the server clock; the response counts the reminders (configurable schedule)
    that went out on the days skipped."""
    before = st.clock.today()
    if body.ustaw_date:
        st.clock.set(body.ustaw_date)
    if body.przesun_dni:
        st.clock.advance(days=body.przesun_dni)
    sent = st.evaluations.reminders_between(before, st.clock.today(), st.schedule_for)
    return s.ClockOut(dzis=st.clock.today(), nowe_powiadomienia=len(sent))


@router.post("/demo/reset", status_code=204, tags=["demo"])
def demo_reset(st: DemoState = Depends(get_state)) -> Response:
    """Fresh demo scenario (same AI mode)."""
    reset_state(ai_mode=st.ai_mode, scenario=True)
    return Response(status_code=204)
