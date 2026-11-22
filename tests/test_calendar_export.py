"""Deadlines as a calendar file: app/application/calendar_export.py and GET /api/me/terminy.ics."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application.calendar_export import DeadlineEvent, deadlines_ics
from backend.main import app

client = TestClient(app)
NOW = datetime(2026, 5, 25, 8, 0, tzinfo=timezone.utc)


def _unfold(text: str) -> str:
    return text.replace("\r\n ", "")


def test_all_day_event_with_two_reminders_and_stable_uid():
    ev = DeadlineEvent("12", date(2026, 6, 19), "Wyznacz kryteria – Monika Testowa", "Arkusz B; termin, uwaga")
    text = deadlines_ics([ev], NOW)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "METHOD:PUBLISH" in text and text.count("BEGIN:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20260619" in text and "DTEND;VALUE=DATE:20260620" in text
    assert "UID:termin-12@" in text
    assert "TRIGGER:-P7D" in text and "TRIGGER:-P1D" in text
    assert "DESCRIPTION:Arkusz B\\; termin\\, uwaga" in _unfold(text)  # RFC 5545 escaping
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_newer_export_has_higher_sequence_so_calendars_update_the_event():
    ev = DeadlineEvent("1", date(2026, 6, 12), "Sporządź ocenę – Grzegorz Wzór")
    seq = lambda t: int(next(x for x in t.split("\r\n") if x.startswith("SEQUENCE:")).split(":")[1])  # noqa: E731
    later = NOW.replace(hour=9)
    assert seq(deadlines_ics([ev], later)) > seq(deadlines_ics([ev], NOW))
    assert "UID:termin-1@" in deadlines_ics([ev], later)


@pytest.fixture
def scenario():
    return reset_state(ai_mode="off", scenario=True)


def test_endpoint_matches_the_users_deadlines_and_has_no_scores(scenario):
    r = client.get("/api/me/terminy.ics", headers={"X-User-Id": "henryk.pryncypal"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "terminy-ocen.ics" in r.headers["content-disposition"]
    text = _unfold(r.text)
    assert text.count("BEGIN:VEVENT") == 1  # Henryk evaluates Grzegorz only
    assert "SUMMARY:Sporządź ocenę – Grzegorz Wzór" in text and "DTSTART;VALUE=DATE:20260612" in text
    assert not any(w in text.lower() for w in ("średnia", "punkt", "negatywn", "pozytywn"))


def test_scope_follows_the_dashboard(scenario):
    count = lambda uid: client.get("/api/me/terminy.ics", headers={"X-User-Id": uid}).text.count("BEGIN:VEVENT")  # noqa: E731
    assert count("barbara.przelozona") == 5  # her four people at the criteria stage + her own evaluation
    assert count("kadry") > count("barbara.przelozona")
    own = _unfold(client.get("/api/me/terminy.ics", headers={"X-User-Id": "adam.kowalik"}).text)
    assert "SUMMARY:Moja ocena okresowa: Potwierdzenie kryteriów" in own  # the evaluated person's own step
