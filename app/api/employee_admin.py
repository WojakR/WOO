"""Employees entered by hand (KPRM use cases "wprowadzenie danych pracownika", "wprowadzenie / zmiany podległości
służbowej", "edycja informacji o pracowniku", "usunięcie danych pracownika") – HR / administrator only.

GET  /api/admin/employees/{id}                 the person's data as the form shows it
POST /api/admin/employees                      add a person (`uruchom_cykl=true` also opens their evaluation cycle)
PUT  /api/admin/employees/{id}                 change the data, incl. who evaluates the person (podległość)
GET  /api/admin/employees/{id}/usuniecie       what deleting the data would do / what blocks it
POST /api/admin/employees/{id}/usuniecie       delete the data: {"data_ustania_zatrudnienia", "zatwierdzam": true}

The form is checked by exactly the rules of the HR import (app/infrastructure/hr_import.py): required fields,
unknown supervisor, a loop in the structure, grade only for civil servants, dates. Changing the supervisor of a
person whose evaluation is in progress goes through "Zmiana oceniającego" (art. 81 ust. 8 pkt 1, § 9 ust. 3) –
the law decides there what happens to the running evaluation.
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.application.archive import is_closed
from app.application.employee_removal import anonymised, plan_removal
from app.domain.employee import Employee
from app.domain.errors import NotFound, ValidationError
from app.infrastructure.hr_import import build_report

from . import schemas as s
from .access import actor as _actor
from .admin import require_admin
from .errors import ApiProblem
from .evaluations import _employee_out
from .state import DemoState, get_state

router = APIRouter(prefix="/api/admin/employees", tags=["administracja"])


class EmployeeForm(BaseModel):
    id: str | None = None  # login-like id; empty on adding = made from the name (jan.kowalski)
    imie: str
    nazwisko: str
    stanowisko: str
    urzad: str = ""
    komorka: str = ""
    opis_stanowiska: str = ""
    przelozony: int | None = None  # the contract's id of the evaluator (direct supervisor); None = nobody
    arkusz: s.Arkusz | None = None  # None = from the role (A head of office, B manages people, C otherwise)
    urzednik_mianowany: bool = False
    stopien_sluzbowy: int | None = None
    kieruje_zespolem: bool | None = None
    kierownik_urzedu: bool | None = None
    email: str | None = None
    data_zatrudnienia: date | None = None
    data_zakonczenia_zatrudnienia: date | None = None
    data_ostatniej_oceny: date | None = None
    data_przyznania_stopnia: date | None = None


class EmployeeSaved(BaseModel):
    pracownik: s.EmployeeOut
    dane: EmployeeForm
    uruchomiony_cykl: int | None = None


class RemovalIn(BaseModel):
    data_ustania_zatrudnienia: date | None = None
    zatwierdzam: bool = False


class RemovalOut(BaseModel):
    mozna_usunac: bool
    przeszkody: list[str]
    do_archiwum: list[int]  # closed evaluations frozen before the data goes
    do_usuniecia: list[int]  # cycles with no evaluation drawn up
    data_ustania_zatrudnienia: date | None
    usunieto: bool = False
    usuniete_konta: int = 0


_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _new_id(st: DemoState, first: str, last: str) -> str:
    base = ".".join(re.sub(r"[^a-z0-9]+", "", x.translate(_PL).lower()) for x in (first, last) if x.strip()) or "osoba"
    taken = {e.id for e in st.directory.all()}
    if base not in taken:
        return base
    return next(f"{base}{n}" for n in range(2, 10_000) if f"{base}{n}" not in taken)


def _yn(v: bool | None) -> str:
    return "" if v is None else ("TAK" if v else "NIE")


def _row(st: DemoState, f: EmployeeForm, eid: str) -> dict:
    boss = st.employee_by_number(f.przelozony) if f.przelozony else None
    if f.przelozony and (boss is None or boss.removed_on):
        raise ValidationError([f"Nie ma przełożonego o identyfikatorze {f.przelozony}."])
    office = f.urzad.strip() or next((e.office for e in st.directory.all() if e.office), "")
    return {
        "id": eid, "imie": f.imie.strip(), "nazwisko": f.nazwisko.strip(), "stanowisko": f.stanowisko.strip(),
        "urzad": office, "komorka": f.komorka.strip(), "opis_stanowiska": f.opis_stanowiska.strip(),
        "id_przelozonego": boss.id if boss else "", "arkusz": f.arkusz.value if f.arkusz else "",
        "urzednik_mianowany": _yn(f.urzednik_mianowany),
        "stopien_sluzbowy": "" if f.stopien_sluzbowy is None else str(f.stopien_sluzbowy),
        "kieruje_zespolem": _yn(f.kieruje_zespolem), "kierownik_urzedu": _yn(f.kierownik_urzedu),
        "email": (f.email or "").strip(), **{k: (getattr(f, k).isoformat() if getattr(f, k) else "") for k in (
            "data_zatrudnienia", "data_zakonczenia_zatrudnienia", "data_ostatniej_oceny", "data_przyznania_stopnia")},
    }


def _validated(st: DemoState, row: dict) -> Employee:
    rep = build_report([row], {e.id: e for e in st.directory.all()})
    if not rep.ok:
        raise ValidationError([p.message for p in rep.problems])
    return rep.employees[0]


def form_of(st: DemoState, e: Employee) -> EmployeeForm:
    boss = st.directory.get(e.evaluator_id) if e.evaluator_id else None
    prev = e.previous_evaluation
    return EmployeeForm(
        id=e.id, imie=e.first_name, nazwisko=e.last_name, stanowisko=e.position, urzad=e.office, komorka=e.unit,
        opis_stanowiska=e.position_description, przelozony=st.employee_number(boss.id) if boss else None,
        arkusz=s.Arkusz(e.sheet), urzednik_mianowany=e.civil_servant, stopien_sluzbowy=e.grade,
        kieruje_zespolem=e.manages_people, kierownik_urzedu=e.is_office_head, email=e.email,
        data_zatrudnienia=e.employment_start, data_zakonczenia_zatrudnienia=e.employment_end,
        data_ostatniej_oceny=prev.date if prev else None, data_przyznania_stopnia=e.grade_since)


def _person(st: DemoState, number: int) -> Employee:
    e = st.employee_by_number(number)
    if e is None or e.removed_on:
        raise NotFound(f"Nie ma pracownika o identyfikatorze {number}.")
    return e


def _saved(st: DemoState, e: Employee, cycle_id: str | None = None) -> EmployeeSaved:
    return EmployeeSaved(pracownik=_employee_out(st, e), dane=form_of(st, e),
                         uruchomiony_cykl=int(cycle_id) if cycle_id and cycle_id.isdigit() else None)


@router.get("/{employee_id}", response_model=EmployeeForm)
def get_form(employee_id: int, x_user_id: str | None = Header(default=None),
             st: DemoState = Depends(get_state)) -> EmployeeForm:
    require_admin(st, _actor(st, x_user_id))
    return form_of(st, _person(st, employee_id))


@router.post("", response_model=EmployeeSaved, status_code=201)
def add(body: EmployeeForm, uruchom_cykl: bool = False, x_user_id: str | None = Header(default=None),
        st: DemoState = Depends(get_state)) -> EmployeeSaved:
    require_admin(st, _actor(st, x_user_id))
    eid = (body.id or "").strip() or _new_id(st, body.imie, body.nazwisko)
    if st.directory.get(eid) is not None:
        raise ApiProblem(409, "ID_ZAJETE", f"Identyfikator „{eid}” jest już zajęty.")
    e = _validated(st, _row(st, body, eid))
    st.import_employees([e])
    cycle = None
    if uruchom_cykl and e.evaluator_id and not e.employment_end:
        prev = e.previous_evaluation
        cycle = st.evaluations.start_cycle(e.id, start_date=prev.date if prev and prev.date else e.employment_start)
    return _saved(st, e, cycle.id if cycle else None)


@router.put("/{employee_id}", response_model=EmployeeSaved)
def update(employee_id: int, body: EmployeeForm, x_user_id: str | None = Header(default=None),
           st: DemoState = Depends(get_state)) -> EmployeeSaved:
    require_admin(st, _actor(st, x_user_id))
    old = _person(st, employee_id)
    if body.id and body.id.strip() != old.id:
        raise ValidationError(["Identyfikatora pracownika nie można zmienić."])
    e = _validated(st, _row(st, body, old.id))
    open_cycle = st.evaluations.cycles.find_open_for(old.id)
    if e.evaluator_id != old.evaluator_id and open_cycle is not None:
        raise ApiProblem(409, "OCENA_W_TOKU",
                         f"{old.full_name} ma ocenę w toku – przełożonego (oceniającego) zmień przez „Zmiana "
                         "oceniającego”, która rozstrzyga, co dzieje się z trwającą oceną (art. 81 ust. 8 pkt 1, "
                         "§ 9 ust. 3).")
    st.import_employees([e])
    return _saved(st, e)


def _plan(st: DemoState, e: Employee, end: date | None):
    svc, today = st.evaluations, st.clock.today()
    return plan_removal(e, st.directory.all(), svc.cycles.list_all(),
                        lambda c: is_closed(c, svc.rules_for(c), svc.calendar, today,
                                            svc.employee_absences(c.employee_id)),
                        end, today, st.person_name)


def _removal_out(plan, **extra) -> RemovalOut:
    return RemovalOut(mozna_usunac=plan.ok, przeszkody=plan.blockers, data_ustania_zatrudnienia=plan.employment_end,
                      do_archiwum=[int(x) for x in plan.archive if x.isdigit()],
                      do_usuniecia=[int(x) for x in plan.discard if x.isdigit()], **extra)


@router.get("/{employee_id}/usuniecie", response_model=RemovalOut)
def removal_preview(employee_id: int, data_ustania_zatrudnienia: date | None = None,
                    x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> RemovalOut:
    require_admin(st, _actor(st, x_user_id))
    return _removal_out(_plan(st, _person(st, employee_id), data_ustania_zatrudnienia))


@router.post("/{employee_id}/usuniecie", response_model=RemovalOut)
def remove(employee_id: int, body: RemovalIn, x_user_id: str | None = Header(default=None),
           st: DemoState = Depends(get_state)) -> RemovalOut:
    from backend import db

    from .archive import service as archive_service

    require_admin(st, _actor(st, x_user_id))
    e = _person(st, employee_id)
    plan = _plan(st, e, body.data_ustania_zatrudnienia)
    if not plan.ok:
        raise ApiProblem(409, "USUNIECIE_ZABLOKOWANE", "Nie można jeszcze usunąć danych tej osoby.",
                         [s.Walidacja(kod="PRZESZKODA", waga=s.Waga.BLAD, komunikat=x) for x in plan.blockers])
    if not body.zatwierdzam:
        raise ValidationError(["Usunięcie danych pracownika wymaga potwierdzenia („zatwierdzam”: true)."])
    today = st.clock.today()
    archive = archive_service(st)
    for cid in plan.archive:  # the personnel file part first – frozen, never rewritten
        archive.freeze(st.evaluations.cycles.get(cid), today)
    removed_cycles = set(plan.archive) | set(plan.discard)
    for cid in removed_cycles:
        st.evaluations.cycles.delete(cid)
    ids = {int(c) for c in removed_cycles if c.isdigit()}
    st.notes = {k: r for k, r in st.notes.items() if r.evaluation_id not in ids and r.note.author_id != e.id}
    st.absences = [a for a in st.absences if a.employee_id != e.id]
    st.deadline_changes = [r for r in st.deadline_changes if r.cycle_id not in removed_cycles]
    st.deputy_records = [d for d in st.deputy_records if e.id not in (d.deputy_id, d.evaluator_id)]
    st.evaluator_changes = [r for r in st.evaluator_changes if r.employee_id != e.id]
    st.evaluator_absences = [a for a in st.evaluator_absences if a.evaluator_id != e.id]
    st.invitations = [i for i in st.invitations if i.cycle_id not in removed_cycles]
    st.notices = [n for n in st.notices if n.recipient_id != e.id and n.cycle_id not in removed_cycles]
    for cid in removed_cycles:
        st.wellbeing.pop(cid, None)
        st.versions.pop(cid, None)
    st.worktime = type(st.worktime)([d for d in st.worktime.all() if d.employee_id != e.id])
    st.reminder_prefs.pop(e.id, None)
    for opted in (st.email_off_for, st.ai_off_for, st.hr_partner_off_for):
        opted.discard(e.id)
    st.import_employees([anonymised(e, plan.employment_end, today)])
    accounts = db.delete_accounts_of(e.id)
    return _removal_out(plan, usunieto=True, usuniete_konta=accounts)
