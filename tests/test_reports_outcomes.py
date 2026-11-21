"""T18: outcomes – level distribution, averages per criterion, units, trend, the people behind a bar;
groups smaller than the office minimum are hidden."""
from datetime import date

from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application.reports import Scope, outcomes
from backend.main import app

from report_fixtures import build

client = TestClient(app)


def run(min_group=5, **kw):
    svc, clock, people, ids = build()
    scope = Scope(people, svc.cycles.list_all(), lambda c: svc.rules, svc.calendar, clock.today(),
                  **{k: v for k, v in kw.items() if k in ("year", "unit")})
    return outcomes(scope, svc.rules, min_group, kw.get("level"), kw.get("outcome")), ids


def test_aggregates():
    o, _ = run()
    assert o.total == 5 and not o.hidden
    assert dict(o.levels) == {"znacznie poniżej oczekiwań": 0, "poniżej oczekiwań": 0, "na poziomie oczekiwań": 1,
                              "powyżej oczekiwań": 4, "znacznie powyżej oczekiwań": 0}
    kom = next(g for g in o.criteria if g.key == "Komunikacja")
    assert kom.people == 5 and kom.average == 4.6
    rz = next(g for g in o.criteria if g.key == "Rzetelność")
    assert rz.average == 5.8  # (1 + 7*4) / 5
    (unit,) = o.units
    assert (unit.key, unit.people, unit.average, unit.positive_percent) == ("Wydział A", 5, 6.28, 80.0)
    assert [(g.key, g.people, g.hidden) for g in o.trend] == [("2026", 5, False)]


def test_filter_lists_the_people_behind_a_bar():
    o, ids = run(level="na poziomie oczekiwań")
    assert [(p.employee_id, p.average, p.outcome) for p in o.people] == [("a.1", 5.0, "negatywna")]
    o, _ = run(outcome="pozytywna")
    assert {p.employee_id for p in o.people} == {"a.2", "a.3", "a.4", "a.5"}


def test_small_groups_are_hidden():
    o, _ = run(min_group=6)
    assert o.hidden and o.levels == []
    assert all(g.hidden and g.average is None for g in o.units + o.criteria + o.trend)
    o, _ = run(unit="Wydział B")
    assert o.total == 0 and o.hidden


def test_api_hides_small_groups_and_checks_access():
    reset_state(today=date(2026, 6, 1), ai_mode="off")
    r = client.get("/api/reports/outcomes", headers={"X-User-Id": "kadry"}).json()
    assert r["minimalna_grupa"] == 5 and r["ukryte"] is True and r["poziomy"] == [] and r["pracownicy"] == []
    assert client.get("/api/reports/outcomes", headers={"X-User-Id": "grzegorz.wzor"}).status_code == 403
