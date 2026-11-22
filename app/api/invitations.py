"""Invitations to the meetings of the evaluation (KPRM use cases: "(opcjonalnie) zaproszenie na rozmowę").

POST /api/evaluations/{id}/zaproszenia                    evaluator / deputy: invite (again = the meeting is moved)
GET  /api/evaluations/{id}/zaproszenia                    the invitations of the evaluation
GET  /api/evaluations/{id}/zaproszenia/{n}.ics            the calendar file (opens in Outlook / Thunderbird / Google)
POST /api/evaluations/{id}/zaproszenia/{n}/odwolaj        evaluator / deputy: cancel the meeting

The invited person gets a notice in the app and an e-mail with the .ics (app/application/notify_job.py).
Rules, the .ics text and the messages: app/application/invitations.py.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field

from app.application import invitations as inv
from app.application.notices import Attachment, Notice
from app.domain.errors import InvalidTransition, NotFound

from . import schemas as s
from .access import actor as _actor
from .access import require_evaluator, require_read
from .evaluations import _cycle, _osoba
from .state import DemoState, get_state

router = APIRouter(prefix="/api/evaluations", tags=["ocena"])


class InvitationIn(BaseModel):
    rodzaj: str = Field(description="ROZMOWA_KRYTERIA | ROZMOWA_OCENIAJACA")
    termin: datetime  # local time of the office (Europe/Warsaw)
    czas_min: int = 60
    miejsce: str
    uwagi: str = ""


class InvitationOut(BaseModel):
    id: int
    rodzaj: str
    nazwa: str
    termin: datetime
    koniec: datetime
    czas_min: int
    miejsce: str
    uwagi: str
    zapraszajacy: s.OsobaRef
    zaproszony: s.OsobaRef
    wyslano: datetime
    wersja: int  # 0 = first invitation, +1 for every change of the date
    odwolane: bool
    ics_url: str


def _now(st: DemoState) -> datetime:
    """The office's local time on the server's (demo) day."""
    from app.infrastructure.clock import OFFICE_TZ

    return datetime.combine(st.clock.today(), datetime.now(OFFICE_TZ).time().replace(microsecond=0))


def _out(st: DemoState, i: inv.Invitation) -> InvitationOut:
    return InvitationOut(id=i.id, rodzaj=i.kind, nazwa=i.title, termin=i.start, koniec=i.end, czas_min=i.minutes,
                         miejsce=i.place, uwagi=i.note, zapraszajacy=_osoba(st, st.directory.get(i.organizer_id)),
                         zaproszony=_osoba(st, st.directory.get(i.attendee_id)), wyslano=i.sent_at, wersja=i.sequence,
                         odwolane=i.cancelled, ics_url=f"/api/evaluations/{i.cycle_id}/zaproszenia/{i.id}.ics")


def _ics(st: DemoState, i: inv.Invitation) -> str:
    org, att = st.directory.get(i.organizer_id), st.directory.get(i.attendee_id)
    _, text = inv.message(i, st.person_name(i.organizer_id), st.person_name(i.attendee_id))
    return inv.to_ics(i, (st.person_name(i.organizer_id), org.email if org else None),
                      (st.person_name(i.attendee_id), att.email if att else None), text)


def _notify(st: DemoState, i: inv.Invitation, now: datetime) -> None:
    subject, text = inv.message(i, st.person_name(i.organizer_id), st.person_name(i.attendee_id))
    method = "CANCEL" if i.cancelled else "REQUEST"
    st.add_notice(Notice(
        f"zaproszenie-{i.id}-{i.sequence}-{method.lower()}", i.attendee_id,
        "ZAPROSZENIE_ODWOLANE" if i.cancelled else "ZAPROSZENIE", subject, text, i.cycle_id, now,
        Attachment(f"zaproszenie-{i.kind.lower()}.ics", f"text/calendar; method={method}", _ics(st, i))))


def _find(st: DemoState, evaluation_id: int, invitation_id: int) -> inv.Invitation:
    i = next((x for x in st.invitations if x.id == invitation_id and x.cycle_id == str(evaluation_id)), None)
    if i is None:
        raise NotFound(f"Nie ma zaproszenia o identyfikatorze {invitation_id}.")
    return i


@router.post("/{evaluation_id}/zaproszenia", response_model=InvitationOut, status_code=201)
def invite(evaluation_id: int, body: InvitationIn, x_user_id: str | None = Header(default=None),
           st: DemoState = Depends(get_state)) -> InvitationOut:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, who)
    require_evaluator(st, who, c, "Zaproszenie na rozmowę wysyła oceniający albo jego zastępca.")
    now = _now(st)
    start = body.termin.replace(tzinfo=None, second=0, microsecond=0)
    inv.check(c, body.rodzaj, start, body.czas_min, body.miejsce, now)
    previous = next((x for x in reversed(st.invitations) if x.cycle_id == c.id and x.kind == body.rodzaj), None)
    new = inv.Invitation(max((x.id for x in st.invitations), default=0) + 1, c.id, body.rodzaj, start,
                         body.czas_min, body.miejsce.strip(), body.uwagi.strip(), who, c.employee_id,
                         datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    new = inv.next_version(previous, new)
    if previous is not None and not previous.cancelled:  # moved: the old one is replaced (same UID in calendars)
        st.invitations.remove(previous)
        new = dataclasses.replace(new, id=previous.id)
    st.invitations.append(new)
    _notify(st, new, now)
    return _out(st, new)


@router.get("/{evaluation_id}/zaproszenia", response_model=list[InvitationOut])
def list_invitations(evaluation_id: int, x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)) -> list[InvitationOut]:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, who)
    require_read(st, who, c)
    return [_out(st, i) for i in sorted(st.invitations, key=lambda x: x.start) if i.cycle_id == c.id]


@router.get("/{evaluation_id}/zaproszenia/{invitation_id}.ics", response_class=Response,
            responses={200: {"content": {"text/calendar": {}}}})
def invitation_ics(evaluation_id: int, invitation_id: int, x_user_id: str | None = Header(default=None),
                   st: DemoState = Depends(get_state)) -> Response:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, who)
    require_read(st, who, c)
    i = _find(st, evaluation_id, invitation_id)
    return Response(_ics(st, i), media_type="text/calendar; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="zaproszenie-{i.kind.lower()}-{c.id}.ics"'})


@router.post("/{evaluation_id}/zaproszenia/{invitation_id}/odwolaj", response_model=InvitationOut)
def cancel(evaluation_id: int, invitation_id: int, x_user_id: str | None = Header(default=None),
           st: DemoState = Depends(get_state)) -> InvitationOut:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, who)
    require_evaluator(st, who, c, "Spotkanie odwołuje oceniający albo jego zastępca.")
    i = _find(st, evaluation_id, invitation_id)
    if i.cancelled:
        raise InvalidTransition("To spotkanie zostało już odwołane.")
    done = dataclasses.replace(i, cancelled=True, sequence=i.sequence + 1)
    st.invitations[st.invitations.index(i)] = done
    _notify(st, done, _now(st))
    return _out(st, done)
