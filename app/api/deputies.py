"""Zastępstwa: a deputy stands in for an evaluator for a period – may hold the conversations and draw up the
evaluation (the cycle records who really acted). HR assigns anyone; an evaluator assigns their own deputy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response

from app.domain.employee import Employee
from app.domain.errors import NotAuthorized, NotFound, ValidationError

from . import schemas as s
from .access import actor as _actor
from .state import HR, DemoState, DeputyRecord, get_state

router = APIRouter(prefix="/api", tags=["zastępstwa"])


def _person(st: DemoState, number: int) -> Employee:
    e = st.employee_by_number(number)
    if e is None:
        raise NotFound(f"Nie ma pracownika o identyfikatorze {number}.")
    return e


def _osoba(st: DemoState, e: Employee) -> s.OsobaRef:
    return s.OsobaRef(id=st.employee_number(e.id), imie=e.first_name, nazwisko=e.last_name, stanowisko=e.position)


def _out(st: DemoState, r: DeputyRecord) -> s.ZastepstwoOut:
    return s.ZastepstwoOut(id=r.id, oceniajacy=_osoba(st, st.directory.get(r.evaluator_id)),
                           zastepca=_osoba(st, st.directory.get(r.deputy_id)), od=r.od, do=r.do,
                           aktywne=r.active_on(st.clock.today()))


@router.get("/zastepstwa", response_model=list[s.ZastepstwoOut])
def list_deputies(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    """HR: all; others: where they are the evaluator or the deputy."""
    who = _actor(st, x_user_id)
    rows = [r for r in st.deputy_records if who == HR or who in (r.evaluator_id, r.deputy_id)]
    return [_out(st, r) for r in sorted(rows, key=lambda r: r.od)]


@router.post("/zastepstwa", response_model=s.ZastepstwoOut, status_code=201)
def add_deputy(body: s.ZastepstwoIn, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> s.ZastepstwoOut:
    who = _actor(st, x_user_id)
    evaluator, deputy = _person(st, body.oceniajacy_id), _person(st, body.zastepca_id)
    if who not in (HR, evaluator.id):
        raise NotAuthorized("Zastępstwo ustala dział kadr albo sam oceniający.")
    problems = []
    if not any(e.evaluator_id == evaluator.id for e in st.directory.all()):
        problems.append(f"{evaluator.full_name} nikogo nie ocenia – nie ma kogo zastępować.")
    if deputy.id == evaluator.id:
        problems.append("Oceniający nie może zastępować samego siebie.")
    if body.do < body.od:
        problems.append("Koniec zastępstwa nie może być wcześniejszy niż jego początek.")
    if problems:
        raise ValidationError(problems)
    new_id = max((x.id for x in st.deputy_records), default=0) + 1
    r = DeputyRecord(new_id, evaluator.id, deputy.id, body.od, body.do)
    st.deputy_records.append(r)
    return _out(st, r)


@router.delete("/zastepstwa/{deputy_id}", status_code=204)
def delete_deputy(deputy_id: int, x_user_id: str | None = Header(default=None),
                  st: DemoState = Depends(get_state)) -> Response:
    who = _actor(st, x_user_id)
    r = next((x for x in st.deputy_records if x.id == deputy_id), None)
    if r is None:
        raise NotFound(f"Nie ma zastępstwa o identyfikatorze {deputy_id}.")
    if who not in (HR, r.evaluator_id):
        raise NotAuthorized("Zastępstwo odwołuje dział kadr albo sam oceniający.")
    st.deputy_records.remove(r)
    return Response(status_code=204)
