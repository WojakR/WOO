"""Change of the evaluator (HR): the supervisor leaves or the team gets a new one (art. 81 ust. 8 pkt 1, § 9 ust. 3).

GET  /api/employees/{id}/evaluator-change?data_zmiany=   may the leaving evaluator draw up the evaluation now?
POST /api/employees/{id}/evaluator-change                 HR: a date in the future = planned (the leaving evaluator
                                                          is reminded they may evaluate first); today or past = done
POST /api/evaluator-changes/{id}/apply                    HR: carry out a planned change
GET  /api/me/notatki-poprzednie                            my notes withheld from the new evaluator
POST /api/notes/{id}/przekaz                               hand one of them over (author only)

Rights after the change come from AccessPolicy (the directory's `evaluator_id` and the cycle's evaluator), so the
previous evaluator loses write access the moment the change is done.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.domain.errors import NotAuthorized, NotFound, ValidationError

from . import schemas as s
from .access import actor as _actor
from .errors import ApiProblem
from .evaluations import _employee, _osoba
from .state import DemoState, EvaluatorChangeRecord, get_state

router = APIRouter(prefix="/api", tags=["ocena"])


class EvaluatorChangeIn(BaseModel):
    nowy_oceniajacy_id: int
    data_zmiany: date
    ocena_przed_zmiana: bool = False  # the leaving evaluator has drawn up the evaluation (art. 81 ust. 8 pkt 1)


class EvaluatorChangeOut(BaseModel):
    id: int | None = None
    status: str  # SPRAWDZENIE | PLANOWANA | WYKONANA
    wariant: str | None = None  # NOWY_CYKL | PRZEJECIE
    data_zmiany: date
    oceniany: s.OsobaRef
    dotychczasowy: s.OsobaRef
    nowy: s.OsobaRef | None = None
    mozliwa_wczesniejsza_ocena: bool
    mozliwa_od: date
    liczone_od: date
    dni_pod_odchodzacym: int
    wyjasnienie: str
    evaluation_id: int | None = None  # the cycle now with the new evaluator (if any)
    notatki_wstrzymane: int = 0  # the predecessor's notes not passed on automatically


def _require_hr(st: DemoState, who: str) -> None:
    if not st.policy().is_admin(who):
        raise NotAuthorized("Zmianę oceniającego wprowadza dział kadr.")


def _out(st: DemoState, emp_id: str, old: str, new: str | None, on: date, status: str, chk=None,
         **extra) -> EvaluatorChangeOut:
    if chk is None:
        _, chk = st.evaluations.evaluator_change_check(emp_id, on)
    return EvaluatorChangeOut(
        status=status, data_zmiany=on, oceniany=_osoba(st, st.directory.get(emp_id)),
        dotychczasowy=_osoba(st, st.directory.get(old)), nowy=_osoba(st, st.directory.get(new)) if new else None,
        mozliwa_wczesniejsza_ocena=chk.may_evaluate_early, mozliwa_od=chk.possible_from, liczone_od=chk.counted_from,
        dni_pod_odchodzacym=chk.days_under_leaving, wyjasnienie=chk.explanation, **extra)


@router.get("/employees/{employee_id}/evaluator-change", response_model=EvaluatorChangeOut)
def check(employee_id: int, data_zmiany: date, x_user_id: str | None = Header(default=None),
          st: DemoState = Depends(get_state)) -> EvaluatorChangeOut:
    who = _actor(st, x_user_id)
    e = _employee(st, employee_id)
    if not (st.policy().is_admin(who) or who == e.evaluator_id):
        raise NotAuthorized("Sprawdzenie zmiany oceniającego: dział kadr albo oceniający.")
    return _out(st, e.id, e.evaluator_id, None, data_zmiany, "SPRAWDZENIE")


def _apply(st: DemoState, rec: EvaluatorChangeRecord, early: bool) -> EvaluatorChangeOut:
    from app.domain.cycle import Status
    from app.domain.evaluator_change import check_evaluator_change

    e = st.directory.get(rec.employee_id)
    svc = st.evaluations
    done = [c for c in svc.cycles.list_all() if c.employee_id == e.id and c.evaluated_on
            and c.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION)]
    last_done = max(done, key=lambda c: c.evaluated_on, default=None)
    if early and last_done is not None:
        # art. 81 ust. 8 pkt 1 – judged on the day the early evaluation was drawn up
        chk = check_evaluator_change(last_done.start_date, last_done.evaluator_since(), last_done.evaluated_on,
                                     svc.rules)
        if not chk.may_evaluate_early:
            raise ValidationError([chk.explanation])
    elif svc.cycles.find_open_for(e.id) is not None:
        _, chk = svc.evaluator_change_check(e.id, rec.on)
        if early and not chk.may_evaluate_early:
            raise ValidationError([chk.explanation])
    else:
        chk = None
    variant, cycle = svc.change_evaluator(e.id, rec.new_evaluator_id, rec.on, early)
    st.import_employees([dataclasses.replace(e, evaluator_id=rec.new_evaluator_id)])
    withheld = 0
    if cycle is not None:
        st.touch(cycle.id)
        if variant == "PRZEJECIE":  # the predecessor's working notes stay theirs until handed over
            for r in st.notes_of(int(cycle.id)):
                if r.note.author_id != rec.new_evaluator_id:
                    r.withheld = True
                    withheld += 1
    rec.status, rec.variant = "WYKONANA", variant
    if chk is None:  # no open cycle (the early evaluation is waiting for acknowledgement)
        last = max((c for c in svc.cycles.list_all() if c.employee_id == e.id), key=lambda c: c.start_date)
        chk = check_evaluator_change(last.start_date, last.evaluator_since(), rec.on, svc.rules)
    return _out(st, e.id, rec.old_evaluator_id, rec.new_evaluator_id, rec.on, "WYKONANA", chk=chk, id=rec.id,
                wariant=variant, evaluation_id=int(cycle.id) if cycle else None, notatki_wstrzymane=withheld)


@router.post("/employees/{employee_id}/evaluator-change", response_model=EvaluatorChangeOut, status_code=201)
def change(employee_id: int, body: EvaluatorChangeIn, x_user_id: str | None = Header(default=None),
           st: DemoState = Depends(get_state)) -> EvaluatorChangeOut:
    who = _actor(st, x_user_id)
    _require_hr(st, who)
    e = _employee(st, employee_id)
    new = _employee(st, body.nowy_oceniajacy_id)
    if not e.evaluator_id:
        raise ApiProblem(409, "BRAK_OCENIAJACEGO", f"{e.full_name} nie ma oceniającego.")
    if new.id == e.evaluator_id:
        raise ValidationError(["To jest już oceniający tego pracownika."])
    rec = EvaluatorChangeRecord(id=max((x.id for x in st.evaluator_changes), default=0) + 1, employee_id=e.id,
                                old_evaluator_id=e.evaluator_id, new_evaluator_id=new.id, on=body.data_zmiany,
                                status="PLANOWANA", registered_by=who)
    if body.data_zmiany > st.clock.today():
        if st.evaluations.cycles.find_open_for(e.id) is None:
            raise ApiProblem(409, "BRAK_CYKLU", f"{e.full_name} nie ma otwartego cyklu oceny.")
        st.evaluator_changes.append(rec)
        return _out(st, e.id, rec.old_evaluator_id, new.id, rec.on, "PLANOWANA", id=rec.id)
    out = _apply(st, rec, body.ocena_przed_zmiana)
    st.evaluator_changes.append(rec)
    return out


@router.post("/evaluator-changes/{change_id}/apply", response_model=EvaluatorChangeOut)
def apply_planned(change_id: int, body: dict | None = None, x_user_id: str | None = Header(default=None),
                  st: DemoState = Depends(get_state)) -> EvaluatorChangeOut:
    who = _actor(st, x_user_id)
    _require_hr(st, who)
    rec = next((x for x in st.evaluator_changes if x.id == change_id), None)
    if rec is None:
        raise NotFound(f"Nie ma zmiany oceniającego o identyfikatorze {change_id}.")
    if rec.status != "PLANOWANA":
        raise ApiProblem(409, "ZMIANA_WYKONANA", "Ta zmiana została już wykonana.")
    if rec.on > st.clock.today():
        raise ApiProblem(409, "ZA_WCZESNIE", f"Zmianę można wykonać od {rec.on:%d.%m.%Y}.")
    early = bool((body or {}).get("ocena_przed_zmiana", False))
    return _apply(st, rec, early)


# ---------------------------------------------------------------- the predecessor's notes

@router.get("/me/notatki-poprzednie", response_model=list[s.NoteOut], tags=["notatki"])
def my_withheld_notes(x_user_id: str | None = Header(default=None),
                      st: DemoState = Depends(get_state)) -> list[s.NoteOut]:
    from .notes import _out as note_out

    who = _actor(st, x_user_id)
    return [note_out(st, r) for r in st.notes.values() if r.withheld and r.note.author_id == who]


@router.post("/notes/{note_id}/przekaz", response_model=s.NoteOut, tags=["notatki"])
def hand_over(note_id: int, x_user_id: str | None = Header(default=None),
              st: DemoState = Depends(get_state)) -> s.NoteOut:
    from .notes import _out as note_out

    who = _actor(st, x_user_id)
    r = st.notes.get(note_id)
    if r is None:
        raise NotFound(f"Nie ma notatki o identyfikatorze {note_id}.")
    if r.note.author_id != who:
        raise NotAuthorized("Notatkę przekazuje nowemu oceniającemu tylko jej autor.")
    r.withheld = False
    return note_out(st, r)


def notifications_for(st: DemoState, who: str) -> list[tuple[str, str, int | None, datetime]]:
    """The leaving evaluator: a planned change and whether they may draw up the evaluation before it."""
    out = []
    for rec in st.evaluator_changes:
        if rec.status != "PLANOWANA" or rec.old_evaluator_id != who:
            continue
        c = st.evaluations.cycles.find_open_for(rec.employee_id)
        if c is None:
            continue
        _, chk = st.evaluations.evaluator_change_check(rec.employee_id, rec.on)
        e = st.directory.get(rec.employee_id)
        text = (f"Od {rec.on:%d.%m.%Y} {e.full_name} będzie oceniany(-a) przez innego przełożonego. "
                + ("Możesz sporządzić ocenę przed zmianą (art. 81 ust. 8 pkt 1) – zmień termin oceny i ją sporządź."
                   if chk.may_evaluate_early else "Wcześniejszej oceny nie sporządza się (nie minęło 6 miesięcy)."))
        out.append((f"zmiana-oceniajacego-{rec.id}", text, int(c.id),
                    datetime.combine(st.clock.today(), time(8, 0))))
    return out
