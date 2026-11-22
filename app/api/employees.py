"""Widok „Pracownicy": the list of people the user may see (AccessPolicy) and each person's evaluation history.

GET /api/employees                       filters: komorka, arkusz, status (current evaluation), wynik (last result);
                                         paging: strona (from 1), na_strone
GET /api/employees/{id}                  one person (card)
GET /api/employees/{id}/evaluations      every cycle, oldest first (+ the evaluation known from the HR data)

Who sees whom: HR / administrators everyone, a manager their subtree or direct reports (office setting) and the
people they stand in for, everyone themselves. `id` = the contract's int id (position in the directory).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel

from app.domain.cycle import EvaluationCycle, Status
from app.domain.employee import Employee
from app.domain.errors import NotAuthorized, NotFound
from app.domain.scoring import Outcome

from . import assistant_mapping as m
from . import schemas as s
from .access import actor as _actor
from .evaluations import STATUS_MAP, _employee_out, _osoba, _wynik
from .state import DemoState, get_state

router = APIRouter(prefix="/api", tags=["pracownicy"])


class BiezacaOcena(BaseModel):
    evaluation_id: int
    status: s.StatusOceny
    termin_oceny: date | None = None


class OstatniaOcena(BaseModel):
    evaluation_id: int | None = None  # None = known only from the HR data (before the system)
    wynik: s.Wynik | None = None
    poziom: s.Poziom | None = None
    data: date | None = None


class EmployeeListItem(BaseModel):
    pracownik: s.EmployeeOut
    biezaca_ocena: BiezacaOcena | None = None
    ostatnia_ocena: OstatniaOcena | None = None


class EmployeeListOut(BaseModel):
    pozycje: list[EmployeeListItem]
    razem: int
    strona: int
    na_strone: int
    komorki: list[str]  # filter options (only units the user can see)


class HistoryItem(BaseModel):
    evaluation_id: int | None = None
    zrodlo: str  # SYSTEM | IMPORT (old evaluation imported from a PDF) | DANE_KADROWE
    status: s.StatusOceny | None = None
    arkusz: s.Arkusz | None = None
    oceniajacy: s.OsobaRef | None = None
    okres_od: date | None = None
    okres_do: date | None = None
    data_sporzadzenia: date | None = None
    data_zapoznania: date | None = None
    srednia: float | None = None
    poziom: s.Poziom | None = None
    wynik: s.Wynik | None = None
    sprzeciw: str | None = None  # None | ZLOZONY | UWZGLEDNIONY | NIEUWZGLEDNIONY


# ---------------------------------------------------------------- who and what

def visible_people(st: DemoState, who: str) -> list[Employee]:
    policy = st.policy()
    ids = policy.visible_employees(who) | {who}
    return [e for e in st.directory.all() if e.id in ids and e.removed_on is None]


def _cycles_of(st: DemoState, employee_id: str) -> list[EvaluationCycle]:
    cs = [c for c in st.evaluations.cycles.list_all() if c.employee_id == employee_id]
    return sorted(cs, key=lambda c: (c.start_date, int(c.id) if c.id.isdigit() else 0))


def _current(st: DemoState, e: Employee) -> BiezacaOcena | None:
    c = st.evaluations.cycles.find_open_for(e.id)
    if c is None:
        return None
    svc = st.evaluations
    return BiezacaOcena(evaluation_id=int(c.id), status=STATUS_MAP[c.status],
                        termin_oceny=c.evaluation_deadline(svc.rules, svc.calendar))


def _last(st: DemoState, e: Employee, cycles: list[EvaluationCycle]) -> OstatniaOcena | None:
    done = [c for c in cycles if c.result is not None and c.status in (Status.ACKNOWLEDGED, Status.OBJECTION,
                                                                        Status.EVALUATION_DONE)]
    if done:
        c = max(done, key=lambda c: c.evaluated_on or date.min)
        return OstatniaOcena(evaluation_id=int(c.id), wynik=_wynik(c.result), poziom=m.level(c.result.level),
                             data=c.evaluated_on)
    p = e.previous_evaluation
    if p and (p.outcome or p.date):
        prev = m.previous(p)
        return OstatniaOcena(wynik=prev.wynik if prev.wynik != "BRAK" else None, poziom=prev.poziom, data=p.date)
    return None


def _person(st: DemoState, number: int, who: str) -> Employee:
    e = st.employee_by_number(number)
    if e is None:
        raise NotFound(f"Nie ma pracownika o identyfikatorze {number}.")
    if e.id not in {x.id for x in visible_people(st, who)}:
        raise NotAuthorized("Nie masz wglądu w dane tego pracownika.")
    return e


# ---------------------------------------------------------------- endpoints

@router.get("/employees", response_model=EmployeeListOut)
def list_employees(komorka: str | None = None, arkusz: s.Arkusz | None = None, status: s.StatusOceny | None = None,
                   wynik: s.Wynik | None = None, szukaj: str | None = None,
                   strona: int = Query(1, ge=1), na_strone: int = Query(50, ge=1, le=200),
                   x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> EmployeeListOut:
    who = _actor(st, x_user_id)
    people = visible_people(st, who)
    units = sorted({e.unit for e in people if e.unit})
    rows: list[EmployeeListItem] = []
    needle = (szukaj or "").strip().casefold()
    for e in people:
        if komorka and e.unit != komorka:
            continue
        if arkusz and e.sheet != arkusz.value:
            continue
        if needle and needle not in f"{e.full_name} {e.position}".casefold():
            continue
        cur = _current(st, e)
        if status and (cur is None or cur.status != status):
            continue
        last = _last(st, e, _cycles_of(st, e.id))
        if wynik and (last is None or last.wynik != wynik):
            continue
        rows.append(EmployeeListItem(pracownik=_employee_out(st, e), biezaca_ocena=cur, ostatnia_ocena=last))
    rows.sort(key=lambda r: (r.pracownik.nazwisko, r.pracownik.imie))
    start = (strona - 1) * na_strone
    return EmployeeListOut(pozycje=rows[start:start + na_strone], razem=len(rows), strona=strona,
                           na_strone=na_strone, komorki=units)


@router.get("/employees/{employee_id}", response_model=EmployeeListItem)
def get_employee(employee_id: int, x_user_id: str | None = Header(default=None),
                 st: DemoState = Depends(get_state)) -> EmployeeListItem:
    e = _person(st, employee_id, _actor(st, x_user_id))
    return EmployeeListItem(pracownik=_employee_out(st, e), biezaca_ocena=_current(st, e),
                            ostatnia_ocena=_last(st, e, _cycles_of(st, e.id)))


def _objection(c: EvaluationCycle) -> str | None:
    if c.objection_decision:
        return c.objection_decision
    return "ZLOZONY" if c.objection_filed_on else None


@router.get("/employees/{employee_id}/evaluations", response_model=list[HistoryItem])
def employee_history(employee_id: int, x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)) -> list[HistoryItem]:
    """All the person's evaluations, oldest first; the first one may come from the HR data (before the system)."""
    who = _actor(st, x_user_id)
    e = _person(st, employee_id, who)
    policy = st.policy()
    cycles = [c for c in _cycles_of(st, e.id) if policy.can_read(who, c.employee_id, c.evaluator_id)
              or e.id in policy.visible_employees(who)]
    out: list[HistoryItem] = []
    p = e.previous_evaluation
    first_start = cycles[0].start_date if cycles else None
    if p and p.date and (first_start is None or p.date <= first_start) and not any(
            c.evaluated_on == p.date for c in cycles):
        prev = m.previous(p)
        out.append(HistoryItem(zrodlo="DANE_KADROWE", data_sporzadzenia=p.date, data_zapoznania=p.acknowledged,
                               poziom=prev.poziom, wynik=prev.wynik if prev.wynik != "BRAK" else None))
    for c in cycles:
        r = c.result
        out.append(HistoryItem(
            evaluation_id=int(c.id), zrodlo="IMPORT" if c.imported else "SYSTEM", status=STATUS_MAP[c.status], arkusz=s.Arkusz(c.sheet),
            oceniajacy=_osoba(st, st.directory.get(c.evaluator_id)), okres_od=c.period_from, okres_do=c.period_to,
            data_sporzadzenia=c.evaluated_on, data_zapoznania=c.acknowledged_on,
            srednia=r.average_display if r else None, poziom=m.level(r.level) if r else None,
            wynik=(s.Wynik.POZYTYWNA if r.outcome is Outcome.POSITIVE else s.Wynik.NEGATYWNA) if r else None,
            sprzeciw=_objection(c)))
    return out
