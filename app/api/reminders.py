"""Configurable reminders: own schedule per user, office default (HR), the plan of one evaluation, notifications.

Rules per stage (app/domain/reminder_schedule.py). Reminders arrive only on working days and inside office
working hours (config/ustawienia_urzedu.json) – a schedule with an hour outside them is rejected (422)."""
from __future__ import annotations

import dataclasses
import zlib

from fastapi import APIRouter, Depends, Header, Response

from app.application.use_cases import PlannedReminder
from app.domain.errors import NotAuthorized, NotFound
from app.domain.reminder_schedule import ReminderSchedule
from app.infrastructure.settings import parse_schedule

from . import schemas as s
from .access import actor as _actor
from .access import require_read
from .state import HR, DemoState, get_state

router = APIRouter(prefix="/api", tags=["przypomnienia"])


def _out(st: DemoState, sched: ReminderSchedule, own: bool) -> s.UstawieniaPrzypomnienOut:
    hours = st.settings.working_hours
    return s.UstawieniaPrzypomnienOut(
        godzina=f"{sched.at:%H:%M}", godziny_pracy=(f"{hours.start:%H:%M}", f"{hours.end:%H:%M}"),
        etapy={stage.value: [s.RegulaPrzypomnienia(rodzaj=r.kind.value, wartosc=r.value, opis=r.label())
                             for r in rules] for stage, rules in sched.rules.items()},
        wlasne=own)


def _parse(st: DemoState, body: s.UstawieniaPrzypomnienIn, base: ReminderSchedule) -> ReminderSchedule:
    raw = {"godzina": body.godzina,
           "etapy": {k: [{"rodzaj": r.rodzaj, "wartosc": r.wartosc} for r in v] for k, v in body.etapy.items()}}
    return parse_schedule(raw, base).validated(st.settings.working_hours)


# ---------------------------------------------------------------- my schedule

@router.get("/me/przypomnienia", response_model=s.UstawieniaPrzypomnienOut)
def my_schedule(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    who = _actor(st, x_user_id)
    return _out(st, st.schedule_for(who), who in st.reminder_prefs)


@router.put("/me/przypomnienia", response_model=s.UstawieniaPrzypomnienOut)
def set_my_schedule(body: s.UstawieniaPrzypomnienIn, x_user_id: str | None = Header(default=None),
                    st: DemoState = Depends(get_state)):
    """Own schedule: e.g. criteria every 14 days instead of 7, or 20 reminders in the evaluation period."""
    who = _actor(st, x_user_id)
    if who == HR:
        raise NotAuthorized("Dział kadr ustawia domyślny harmonogram urzędu: PUT /api/ustawienia/przypomnienia.")
    st.reminder_prefs[who] = _parse(st, body, st.schedule_for(who))
    return _out(st, st.reminder_prefs[who], True)


@router.delete("/me/przypomnienia", status_code=204)
def reset_my_schedule(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    st.reminder_prefs.pop(_actor(st, x_user_id), None)
    return Response(status_code=204)


# ---------------------------------------------------------------- office default (HR / administrator)

@router.get("/ustawienia/przypomnienia", response_model=s.UstawieniaPrzypomnienOut)
def office_schedule(st: DemoState = Depends(get_state)):
    return _out(st, st.settings.reminders, False)


@router.put("/ustawienia/przypomnienia", response_model=s.UstawieniaPrzypomnienOut)
def set_office_schedule(body: s.UstawieniaPrzypomnienIn, x_user_id: str | None = Header(default=None),
                        st: DemoState = Depends(get_state)):
    if _actor(st, x_user_id) != HR:
        raise NotAuthorized("Domyślny harmonogram przypomnień urzędu zmienia dział kadr.")
    st.settings = dataclasses.replace(st.settings, reminders=_parse(st, body, st.settings.reminders))
    return _out(st, st.settings.reminders, False)


# ---------------------------------------------------------------- plan of one evaluation, my notifications

def _person(st: DemoState, emp_id: str) -> s.OsobaRef:
    e = st.directory.get(emp_id)
    if e is None:  # e.g. "kadry" deciding objections (office setting) – not a person in the directory
        return s.OsobaRef(id=0, imie="Dział", nazwisko="kadr")
    return s.OsobaRef(id=st.employee_number(e.id), imie=e.first_name, nazwisko=e.last_name, stanowisko=e.position)


@router.get("/evaluations/{evaluation_id}/przypomnienia", response_model=list[s.PlanowanePrzypomnienie])
def evaluation_plan(evaluation_id: int, x_user_id: str | None = Header(default=None),
                    st: DemoState = Depends(get_state)):
    """Reminders of the current stage – past (sent) and future – per the recipient's schedule."""
    c = st.evaluations.cycles.get(str(evaluation_id))
    if c is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    require_read(st, _actor(st, x_user_id), c)
    today = st.clock.today()
    return [s.PlanowanePrzypomnienie(kiedy=r.when, etap=r.stage.value, do_kogo=_person(st, r.recipient_id),
                                     tresc=r.message, termin=r.deadline, minelo=r.when.date() <= today)
            for r in st.evaluations.reminder_plan(c, st.schedule_for)]


def notification_id(key: str) -> int:
    return zlib.crc32(key.encode())


def _my_sent(st: DemoState, who: str) -> list[PlannedReminder]:
    today = st.clock.today()
    return sorted((r for c in st.evaluations.cycles.list_all() for r in st.evaluations.reminder_plan(c, st.schedule_for)
                   if r.recipient_id == who and r.when.date() <= today), key=lambda r: r.when, reverse=True)


@router.get("/notifications", response_model=list[s.NotificationOut], tags=["sesja"])
def notifications(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    """My reminders that have gone out (server clock), newest first."""
    who = _actor(st, x_user_id)
    return [s.NotificationOut(id=notification_id(r.key), typ=f"PRZYPOMNIENIE_{r.stage.value}", tresc=r.message,
                              evaluation_id=int(r.cycle_id), zaplanowane_na=r.when, wyslane_at=r.when,
                              przeczytane=f"{who}:{r.key}" in st.read_notifications)
            for r in _my_sent(st, who)]


@router.post("/notifications/{notification}/read", status_code=204, tags=["sesja"])
def mark_read(notification: int, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    who = _actor(st, x_user_id)
    r = next((r for r in _my_sent(st, who) if notification_id(r.key) == notification), None)
    if r is None:
        raise NotFound(f"Nie ma powiadomienia o identyfikatorze {notification}.")
    st.read_notifications.add(f"{who}:{r.key}")
    return Response(status_code=204)
