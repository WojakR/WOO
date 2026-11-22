"""Invitation to a meeting (KPRM use case "(opcjonalnie) zaproszenie na rozmowę"): notice in the app, e-mail with
an .ics the calendar understands, moving the meeting updates the same event, cancelling sends METHOD:CANCEL."""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application import invitations as inv
from app.application import notify_job
from app.domain.calendar import WorkingCalendar
from app.domain.cycle import EvaluationCycle
from app.domain.errors import InvalidTransition, ValidationError
from app.infrastructure.kprm_adapter import kprm_rulebook
from app.infrastructure.notifier import OutboxNotifier
from backend.main import app

EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
client = TestClient(app)
AS_BOSS = {"X-User-Id": BOSS}


@pytest.fixture
def st():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    st.cid = st.evaluations.cycles.find_open_for(EMP).id
    return st


def invite(st, **body):
    payload = {"rodzaj": "ROZMOWA_KRYTERIA", "termin": "2026-06-03T10:00:00", "czas_min": 45,
               "miejsce": "Pokój 214, Al. Ujazdowskie 1/3", "uwagi": "Proszę przygotować opis zadań."} | body
    return client.post(f"/api/evaluations/{st.cid}/zaproszenia", headers=AS_BOSS, json=payload)


# ---------------------------------------------------------------- the .ics itself

def _inv(**kw):
    base = dict(id=1, cycle_id="7", kind="ROZMOWA_OCENIAJACA", start=datetime(2026, 6, 3, 10, 0), minutes=60,
                place="Sala 2; piętro 1, skrzydło B", note="", organizer_id="b", attendee_id="e",
                sent_at=datetime(2026, 6, 1, 9, 30))
    return inv.Invitation(**(base | kw))


def test_ics_is_a_valid_calendar_request():
    text = inv.to_ics(_inv(), ("Henryk Pryncypał", "h@urzad.example"), ("Grzegorz Wzór", None), "Opis, z przecinkiem")
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and text.endswith("\r\n")
    assert "METHOD:REQUEST" in lines and "UID:ocena-7-rozmowa_oceniajaca@ocena-okresowa.local" in lines
    assert "DTSTART;TZID=Europe/Warsaw:20260603T100000" in lines and "DTEND;TZID=Europe/Warsaw:20260603T110000" in lines
    assert "DTSTAMP:20260601T093000Z" in lines and "TZID:Europe/Warsaw" in lines
    assert "LOCATION:Sala 2\\; piętro 1\\, skrzydło B" in lines and "DESCRIPTION:Opis\\, z przecinkiem" in lines
    assert 'ORGANIZER;CN="Henryk Pryncypał":mailto:h@urzad.example' in lines
    assert all(len(x.encode("utf-8")) <= 75 for x in lines)  # folded


def test_long_lines_are_folded_without_breaking_characters():
    text = inv.to_ics(_inv(note="x"), ("Ż" * 60, "a@b.pl"), ("Ą" * 60, "c@d.pl"), "ł" * 100)
    unfolded = text.replace("\r\n ", "")
    assert "DESCRIPTION:" + "ł" * 100 in unfolded


def test_cancel_and_rules():
    text = inv.to_ics(_inv(cancelled=True, sequence=2), ("A", None), ("B", None))
    assert "METHOD:CANCEL" in text and "STATUS:CANCELLED" in text and "SEQUENCE:2" in text
    c = EvaluationCycle.start("1", "e", "b", "C", date(2026, 1, 1), date(2026, 1, 1), kprm_rulebook(),
                              WorkingCalendar())
    now = datetime(2026, 6, 1, 9, 0)
    with pytest.raises(InvalidTransition):
        inv.check(c, "ROZMOWA_OCENIAJACA", datetime(2026, 6, 3, 10), 60, "Sala", now)  # criteria not confirmed
    with pytest.raises(ValidationError) as e:
        inv.check(c, "ROZMOWA_KRYTERIA", datetime(2026, 5, 3, 10), 5, " ", now)
    assert len(e.value.problems) == 3


# ---------------------------------------------------------------- API + notice + e-mail

def test_invite_notifies_the_evaluated_person_with_the_calendar_file(st):
    r = invite(st)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["wersja"] == 0 and out["zaproszony"]["nazwisko"] == "Wzór" and not out["odwolane"]
    ics = client.get(out["ics_url"], headers={"X-User-Id": EMP})
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert "DTSTART;TZID=Europe/Warsaw:20260603T100000" in ics.text
    mine = client.get("/api/notifications", headers={"X-User-Id": EMP}).json()
    assert any(n["typ"] == "ZAPROSZENIE" and "Pokój 214" in n["tresc"] for n in mine)
    outbox = OutboxNotifier()
    notify_job.run(st, outbox, datetime(2026, 6, 1, 15, 0), st.settings.working_hours,
                   {EMP: "grzegorz@urzad.example"}.get)
    (to, att), = [a for a in outbox.attachments if a[0] == "grzegorz@urzad.example"]
    assert att.content_type == "text/calendar; method=REQUEST" and att.filename.endswith(".ics")


def test_moving_the_meeting_updates_the_same_event_and_cancelling_it(st):
    first = invite(st).json()
    moved = invite(st, termin="2026-06-04T12:30:00").json()
    assert moved["id"] == first["id"] and moved["wersja"] == 1
    assert len(client.get(f"/api/evaluations/{st.cid}/zaproszenia", headers=AS_BOSS).json()) == 1
    assert "SEQUENCE:1" in client.get(moved["ics_url"], headers=AS_BOSS).text
    r = client.post(f"/api/evaluations/{st.cid}/zaproszenia/{first['id']}/odwolaj", headers=AS_BOSS)
    assert r.status_code == 200 and r.json()["odwolane"] and r.json()["wersja"] == 2
    kinds = [n.kind for n in st.notices if n.recipient_id == EMP]
    assert kinds == ["ZAPROSZENIE", "ZAPROSZENIE", "ZAPROSZENIE_ODWOLANE"]
    assert "METHOD:CANCEL" in st.notices[-1].attachment.content


def test_only_the_evaluator_invites_and_only_at_the_right_stage(st):
    r = client.post(f"/api/evaluations/{st.cid}/zaproszenia", headers={"X-User-Id": EMP},
                    json={"rodzaj": "ROZMOWA_KRYTERIA", "termin": "2026-06-03T10:00:00", "miejsce": "x"})
    assert r.status_code == 403
    assert invite(st, rodzaj="ROZMOWA_OCENIAJACA").status_code == 409
    assert invite(st, termin="2026-05-01T10:00:00").status_code == 422
