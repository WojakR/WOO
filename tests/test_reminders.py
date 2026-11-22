"""Configurable reminders: rules per stage, any number, working days and working hours only, own settings."""
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

import app.api.state as state_mod
from app.api.state import get_state, reset_state
from app.domain.calendar import WorkingCalendar
from app.domain.errors import ValidationError
from app.domain.reminder_schedule import (ReminderRule, ReminderSchedule, RuleKind, Stage, WorkingHours,
                                          reminder_dates)
from app.infrastructure.settings import DEFAULT_SCHEDULE
from backend.main import app

CAL = WorkingCalendar()
HOURS = WorkingHours(time(8), time(16))
client = TestClient(app)
EVAL, NEW = "bartlomiej.przelozony", "adam.wzor"  # Adam Wzór has no previous evaluation: his cycle starts today


# ---------------------------------------------------------------- domain

def test_evaluation_period_defaults_50_75_percent_2_months_2_weeks_off_days_moved_earlier():
    days = reminder_dates(DEFAULT_SCHEDULE.rules[Stage.PERIOD], date(2024, 6, 17), date(2026, 6, 12), CAL)
    assert days == [date(2025, 6, 13),  # 50 % = Sat 14.06.2025 -> Fri
                    date(2025, 12, 12),  # 75 % = Sat 13.12.2025 -> Fri
                    date(2026, 4, 10),  # 2 months before = Sun 12.04.2026 -> Fri
                    date(2026, 5, 29)]  # 2 weeks before


def test_percentages_adapt_to_a_shorter_period_after_a_negative_evaluation():
    days = reminder_dates(DEFAULT_SCHEDULE.rules[Stage.PERIOD], date(2026, 6, 10), date(2026, 12, 11), CAL)
    assert days[0] == date(2026, 9, 10)  # half of 6 months, not of 24


def test_criteria_stage_repeats_every_week_until_the_deadline():
    days = reminder_dates((ReminderRule(RuleKind.EVERY_DAYS, 7),), date(2026, 6, 15), date(2026, 7, 15), CAL)
    assert days == [date(2026, 6, 22), date(2026, 6, 29), date(2026, 7, 6), date(2026, 7, 13)]
    every_2_weeks = reminder_dates((ReminderRule(RuleKind.EVERY_DAYS, 14),), date(2026, 6, 15), date(2026, 7, 15), CAL)
    assert every_2_weeks == [date(2026, 6, 29), date(2026, 7, 13)]


def test_never_on_a_weekend_or_holiday_and_never_outside_the_stage():
    rules = tuple(ReminderRule(RuleKind.DAYS_BEFORE, n) for n in range(0, 40)) + (ReminderRule(RuleKind.EVERY_DAYS, 1),)
    start, end = date(2026, 10, 20), date(2026, 11, 16)  # includes 1.11 and 11.11
    days = reminder_dates(rules, start, end, CAL)
    assert days and all(not CAL.is_day_off(d) and start <= d <= end for d in days)
    assert date(2026, 11, 11) not in days


def test_one_or_twenty_reminders_but_not_unlimited():
    twenty = ReminderSchedule({Stage.PERIOD: tuple(ReminderRule(RuleKind.DAYS_BEFORE, n) for n in range(1, 21))})
    assert twenty.validated(HOURS) is twenty
    with pytest.raises(ValidationError, match="najwyżej"):
        ReminderSchedule({Stage.PERIOD: tuple(ReminderRule(RuleKind.DAYS_BEFORE, n) for n in range(31))}).validated(HOURS)
    with pytest.raises(ValidationError, match="spoza zakresu"):
        ReminderSchedule({Stage.PERIOD: (ReminderRule(RuleKind.PERCENT, 120),)}).validated(HOURS)


@pytest.mark.parametrize("at, ok", [(time(8, 0), True), (time(11, 0), True), (time(15, 59), True),
                                    (time(7, 59), False), (time(16, 0), False), (time(20, 0), False)])
def test_reminders_only_inside_working_hours(at, ok):
    schedule = ReminderSchedule({}, at=at)
    if ok:
        schedule.validated(HOURS)
    else:
        with pytest.raises(ValidationError, match="godzinach pracy"):
            schedule.validated(HOURS)


# ---------------------------------------------------------------- API

@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


def as_(who):
    return {"X-User-Id": who}


def _eid(st, who=NEW):
    return st.evaluations.cycles.find_open_for(who).id


def test_default_schedule_and_the_plan_of_a_new_cycle(st):
    me = client.get("/api/me/przypomnienia", headers=as_(EVAL)).json()
    assert me["wlasne"] is False and me["godzina"] == "11:00" and me["godziny_pracy"] == ["08:00", "16:00"]
    assert [r["opis"] for r in me["etapy"]["OKRES_OCENY"]] == [
        "po 50 % okresu", "po 75 % okresu", "2 mies. przed terminem", "2 tyg. przed terminem"]
    plan = client.get(f"/api/evaluations/{_eid(st)}/przypomnienia", headers=as_(EVAL)).json()
    assert [p["kiedy"] for p in plan] == ["2026-06-22T11:00:00", "2026-06-29T11:00:00", "2026-07-06T11:00:00",
                                          "2026-07-13T11:00:00"]
    assert plan[0]["etap"] == "WYZNACZENIE_KRYTERIOW" and plan[0]["do_kogo"]["imie"] == "Bartłomiej"
    assert "wyznacz kryteria" in plan[0]["tresc"] and plan[0]["minelo"] is False


def test_own_schedule_changes_the_plan_and_is_locked_to_working_hours(st):
    r = client.put("/api/me/przypomnienia", headers=as_(EVAL), json={
        "godzina": "09:30", "etapy": {"WYZNACZENIE_KRYTERIOW": [{"rodzaj": "CO_DNI", "wartosc": 14}]}})
    assert r.status_code == 200 and r.json()["wlasne"] is True
    assert len(r.json()["etapy"]["OKRES_OCENY"]) == 4  # other stages keep the defaults
    plan = client.get(f"/api/evaluations/{_eid(st)}/przypomnienia", headers=as_(EVAL)).json()
    assert [p["kiedy"] for p in plan] == ["2026-06-29T09:30:00", "2026-07-13T09:30:00"]
    late = client.put("/api/me/przypomnienia", headers=as_(EVAL), json={"godzina": "20:00"})
    assert late.status_code == 422 and "godzinach pracy" in late.json()["walidacje"][0]["komunikat"]
    assert client.delete("/api/me/przypomnienia", headers=as_(EVAL)).status_code == 204
    assert client.get("/api/me/przypomnienia", headers=as_(EVAL)).json()["wlasne"] is False


def test_unknown_rule_is_rejected(st):
    r = client.put("/api/me/przypomnienia", headers=as_(EVAL),
                   json={"etapy": {"OKRES_OCENY": [{"rodzaj": "CO_GODZINE", "wartosc": 1}]}})
    assert r.status_code == 422


def test_office_default_only_by_hr_and_survives_a_restart(st):
    body = {"etapy": {"WYZNACZENIE_KRYTERIOW": [{"rodzaj": "CO_DNI", "wartosc": 10}]}}
    assert client.put("/api/ustawienia/przypomnienia", headers=as_(EVAL), json=body).status_code == 403
    assert client.put("/api/ustawienia/przypomnienia", headers=as_("kadry"), json=body).status_code == 200
    state_mod._state = None  # restart
    get_state()
    office = client.get("/api/ustawienia/przypomnienia").json()
    assert [r["wartosc"] for r in office["etapy"]["WYZNACZENIE_KRYTERIOW"]] == [10]


def test_moving_the_clock_sends_reminders_and_they_show_as_notifications(st):
    r = client.post("/api/demo/clock", json={"przesun_dni": 14}).json()
    assert r["dzis"] == "2026-06-29" and r["nowe_powiadomienia"] >= 2  # 22.06 and 29.06 for Adam's cycle at least
    mine = client.get("/api/notifications", headers=as_(EVAL)).json()
    assert [n["zaplanowane_na"] for n in mine][:2] == ["2026-06-29T11:00:00", "2026-06-22T11:00:00"]
    assert not mine[0]["przeczytane"]
    assert client.post(f"/api/notifications/{mine[0]['id']}/read", headers=as_(EVAL)).status_code == 204
    assert client.get("/api/notifications", headers=as_(EVAL)).json()[0]["przeczytane"] is True
    assert client.get("/api/notifications", headers=as_(NEW)).json() == []  # not his task at this stage


def test_plan_follows_the_stage(st):
    cid = _eid(st)
    st.evaluations.set_criteria(cid, EVAL, [])
    plan = client.get(f"/api/evaluations/{cid}/przypomnienia", headers=as_(EVAL)).json()
    assert plan and all(p["do_kogo"]["imie"] == "Adam" and "potwierdź kryteria" in p["tresc"] for p in plan)
    st.evaluations.confirm_criteria(cid, NEW)
    plan = client.get(f"/api/evaluations/{cid}/przypomnienia", headers=as_(EVAL)).json()
    assert [p["etap"] for p in plan] == ["OKRES_OCENY"] * 4
