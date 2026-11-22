"""T17: progress of the evaluations across the organisation, scoped by the access policy."""
from datetime import date

from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application.reports import Scope, progress
from app.domain.access import AccessPolicy
from backend.main import app

from report_fixtures import BOSS_A, build

client = TestClient(app)


def scope(svc, clock, people, who=None, **kw):
    visible = AccessPolicy({e.id: e.evaluator_id for e in people}).subtree(who) if who else {e.id for e in people}
    return Scope([e for e in people if e.id in visible], svc.cycles.list_all(), lambda c: svc.rules, svc.calendar,
                 clock.today(), **kw)


def test_every_number_for_the_office():
    svc, clock, people, ids = build()
    p = progress(scope(svc, clock, people))
    assert p.people == 8 and p.cycles == 12  # 7 first cycles + 5 that started after the acknowledgement
    assert p.drawn_up == 5 and p.in_progress == 7
    assert p.waiting_for_employee == 1  # b.1: criteria waiting for confirmation
    assert p.overdue == 1 and p.overdue_cycles == [ids["a.6"]]  # criteria due 1.04.2026, never set
    assert p.on_time == 5 and p.on_time_percent == 100.0
    assert p.not_started == 1  # b.2
    assert p.statuses == {"ocena_zapoznana": 5, "cykl_rozpoczety": 6, "kryteria_wyznaczone": 1}
    assert p.stage_days == {"cykl_rozpoczety": 18.0, "kryteria_wyznaczone": 0.0,
                            "kryteria_potwierdzone_przez_ocenianego": 80.0, "rozmowa_oceniajaca_odbyta": 0.0,
                            "ocena_sporzadzona": 2.0}
    a, b = p.units
    assert (a.unit, a.people, a.cycles, a.drawn_up, a.in_progress, a.overdue, a.on_time_percent) == \
        ("Wydział A", 6, 11, 5, 6, 1, 100.0)
    assert (b.unit, b.people, b.cycles, b.drawn_up, b.on_time_percent) == ("Wydział B", 2, 1, 0, None)


def test_late_evaluation_is_not_on_time():
    svc, clock, people, ids = build()
    c = svc.cycles.get(ids["a.1"])
    c.deadline_override = date(2026, 6, 5)  # deadline before the day it was drawn up (8.06)
    svc.cycles.save(c)
    p = progress(scope(svc, clock, people))
    assert p.on_time == 4 and p.on_time_percent == 80.0


def test_year_filter_by_the_evaluation_deadline():
    svc, clock, people, _ = build()
    assert progress(scope(svc, clock, people, year=2027)).cycles == 0
    assert progress(scope(svc, clock, people, year=2028)).cycles == 11
    # a.1 was negative: the re-evaluation is due 6 months after the acknowledgement (11.12.2026)
    assert progress(scope(svc, clock, people, year=2026)).cycles == 1


def test_unit_filter_and_subtree_of_a_manager():
    svc, clock, people, _ = build()
    assert progress(scope(svc, clock, people, unit="Wydział B")).people == 2
    p = progress(scope(svc, clock, people, who=BOSS_A))
    assert p.people == 6 and [u.unit for u in p.units] == ["Wydział A"]


def test_api_scope_hr_manager_and_employee():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    hr = client.get("/api/reports/progress", headers={"X-User-Id": "kadry"}).json()
    assert hr["objeci_ocena"] == 13 and hr["zakres"] == "całego urzędu"
    boss = client.get("/api/reports/progress", headers={"X-User-Id": "henryk.pryncypal"}).json()
    assert boss["objeci_ocena"] == 1 and boss["komorki"][0]["komorka"] == "Referat Przekładów"
    assert boss["statusy"] == {"KRYTERIA_DO_WYZNACZENIA": 1}
    assert client.get("/api/reports/progress", headers={"X-User-Id": "grzegorz.wzor"}).status_code == 403
    assert st.employee_number("grzegorz.wzor")  # state used
