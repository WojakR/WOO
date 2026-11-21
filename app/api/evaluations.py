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
from app.domain.employee import Employee
from app.domain.errors import NotAuthorized, NotFound
from app.domain.evidence_hint import suggest_points
from app.domain.notes import Note, evidence_by_criterion
from app.domain.scoring import EvaluationResult, Outcome, compute_result

from . import assistant_mapping as m
from . import schemas as s
from .errors import ApiProblem
from .state import DemoState, get_state, reset_state

router = APIRouter(prefix="/api")

HR = "kadry"

STATUS_MAP = {
    Status.CYCLE_STARTED: s.StatusOceny.KRYTERIA_DO_WYZNACZENIA,
    Status.CRITERIA_SET: s.StatusOceny.KRYTERIA_DO_POTWIERDZENIA,
    Status.CRITERIA_CONFIRMED: s.StatusOceny.OKRES_OCENY,
    Status.MEETING_HELD: s.StatusOceny.ROZMOWA_OCENIAJACA,
    Status.EVALUATION_DONE: s.StatusOceny.OCENA_DO_ZAPOZNANIA,
    Status.ACKNOWLEDGED: s.StatusOceny.ZAKONCZONA,
}

# API action -> (domain step, who performs it)
ACTIONS = {
    s.Akcja.ZATWIERDZ_KRYTERIA: ("set_criteria", "evaluator"),
    s.Akcja.POTWIERDZ_KRYTERIA: ("confirm_criteria", "employee"),
    s.Akcja.ROZPOCZNIJ_ROZMOWE: ("record_review_meeting", "evaluator"),
    s.Akcja.ZATWIERDZ_OCENE: ("submit_evaluation", "evaluator"),
    s.Akcja.POTWIERDZ_ZAPOZNANIE: ("acknowledge", "employee"),
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
}


# ---------------------------------------------------------------- helpers

def _dt(d: date | None) -> datetime | None:
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc) if d else None


def _actor(st: DemoState, x_user_id: str | None) -> str:
    if x_user_id is None or x_user_id == HR:
        return HR
    if st.directory.get(x_user_id) is None:
        raise ApiProblem(403, "NIEZNANY_UZYTKOWNIK", "Nieznany użytkownik (nagłówek X-User-Id).")
    return x_user_id


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
    if actor not in (HR, c.evaluator_id, c.employee_id):
        raise NotAuthorized("Nie masz dostępu do tej oceny.")
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


def _allowed_actions(c: EvaluationCycle, actor: str) -> list[s.Akcja]:
    out = []
    for akcja, (step, who) in ACTIONS.items():
        person = c.evaluator_id if who == "evaluator" else c.employee_id
        # set_criteria may repeat while not confirmed, but "approve criteria" is offered only once
        repeat = step == "set_criteria" and c.status is Status.CRITERIA_SET
        if actor == person and c.status in TRANSITIONS[step][0] and not repeat:
            out.append(akcja)
    return out


def _editable(c: EvaluationCycle, actor: str) -> list[str]:
    if actor != c.evaluator_id:
        return []
    return [FIELDS_BACK[f] for f, statuses in EDITABLE_IN.items() if c.status in statuses and f in FIELDS_BACK]


def _podpis(st: DemoState, day: date | None, who: Employee | None) -> s.Podpis:
    return s.Podpis(at=_dt(day), osoba=_osoba(st, who) if (day and who) else None)


def _evaluation_out(st: DemoState, c: EvaluationCycle, actor: str) -> s.EvaluationOut:
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
        dozwolone_akcje=_allowed_actions(c, actor), edytowalne_pola=_editable(c, actor),
        walidacje=_validations(st, c), updated_at=ver.updated_at,
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
    subs = [st.employee_number(x.id) for x in st.directory.all() if x.evaluator_id == actor]
    return s.UserContext(pracownik=_osoba(st, e), rola=s.Rola.PRACOWNIK, czy_oceniajacy=bool(subs),
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
    people = [e for e in st.directory.all() if e.evaluator_id and (actor == HR or e.evaluator_id == actor)]
    items = []
    for e in people:
        c = svc.cycles.find_open_for(e.id) or next(
            (x for x in svc.cycles.list_all() if x.employee_id == e.id), None)
        if c is None:
            items.append(s.DashboardItem(evaluation_id=None, oceniany=_osoba(st, e), arkusz=s.Arkusz(e.sheet),
                                         status=None, nastepny_krok="Rozpocznij cykl oceny", kto_dziala="KADRY",
                                         termin=None, dni_do_terminu=None, komorka=e.unit))
            continue
        step, who = NEXT_STEP[c.status]
        deadline = c.evaluation_deadline(svc.rules, svc.calendar)
        if c.status in (Status.CYCLE_STARTED, Status.CRITERIA_SET):
            due = c.criteria_deadline
        elif c.status in (Status.CRITERIA_CONFIRMED, Status.MEETING_HELD):
            due = deadline
        else:
            due = None
        days = (due - today).days if due else None
        done = c.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED)
        items.append(s.DashboardItem(
            evaluation_id=int(c.id), oceniany=_osoba(st, e), arkusz=s.Arkusz(c.sheet), status=STATUS_MAP[c.status],
            nastepny_krok=step, kto_dziala=who, termin=due or deadline, dni_do_terminu=days, pilnosc=_urgency(days),
            wynik=_wynik(_live_result(st, c)) if done else None, komorka=e.unit, termin_oceny=deadline,
        ))
    return s.DashboardOut(pozycje=items, nieprzeczytane_powiadomienia=0)


# ---------------------------------------------------------------- the evaluation sheet

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
    st.touch(c.id)
    return _evaluation_out(st, svc.cycles.get(c.id), actor)


@router.get("/evaluations/{evaluation_id}/pdf", tags=["ocena"])
def pdf(evaluation_id: int, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    _cycle(st, evaluation_id, _actor(st, x_user_id))
    raise ApiProblem(501, "NIEDOSTEPNE", "Wydruk arkusza (PDF) nie jest jeszcze dostępny.")


@router.get("/evaluations/{evaluation_id}/evidence", response_model=s.EvidenceOut, tags=["notatki"])
def evidence(evaluation_id: int, x_user_id: str | None = Header(default=None),
             st: DemoState = Depends(get_state)) -> s.EvidenceOut:
    """Evidence map: tagged notes per criterion and a readable suggested score (never applied automatically)."""
    actor = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, actor)
    if actor == c.employee_id:
        raise NotAuthorized("Mapę dowodów z notatek widzi tylko oceniający.")
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
    if actor == c.employee_id:
        raise NotAuthorized("Podpowiedzi HR partnera są tylko dla przełożonego.")
    notes = _notes(st, c)
    key = (tuple(n.id for n in notes), tuple(sorted(c.scores.items())), st.clock.today())
    cached = st.hr_reports.get(c.id)
    if cached is None or cached[0] != key:
        report = st.assistant.hr_partner(c, st.directory.get(c.employee_id), notes, c.absences, st.clock.today())
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

@router.get("/demo/clock", response_model=s.ClockOut, tags=["demo"])
def get_clock(st: DemoState = Depends(get_state)) -> s.ClockOut:
    return s.ClockOut(dzis=st.clock.today(), nowe_powiadomienia=0)


@router.post("/demo/clock", response_model=s.ClockOut, tags=["demo"])
def set_clock(body: s.ClockIn, st: DemoState = Depends(get_state)) -> s.ClockOut:
    """„Przewiń czas”: moves the server clock; the response counts reminders due on the new date."""
    if body.ustaw_date:
        st.clock.set(body.ustaw_date)
    if body.przesun_dni:
        st.clock.advance(days=body.przesun_dni)
    return s.ClockOut(dzis=st.clock.today(), nowe_powiadomienia=len(st.evaluations.reminders()))


@router.post("/demo/reset", status_code=204, tags=["demo"])
def demo_reset(st: DemoState = Depends(get_state)) -> Response:
    """Fresh demo scenario (same AI mode)."""
    reset_state(ai_mode=st.ai_mode, scenario=True)
    return Response(status_code=204)
