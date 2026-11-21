"""T8: change of position through the API – both variants, the 6-month boundary, the sheet and the rights."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS, HR, OTHER = "grzegorz.wzor", "henryk.pryncypal", "kadry", "romuald.gut"


def as_(who):
    return {"X-User-Id": who}


@pytest.fixture
def st():
    return reset_state(today=date(2026, 3, 2), ai_mode="off")


def post(st, change, who=BOSS, **extra):
    return client.post(f"/api/employees/{st.employee_number(EMP)}/position-changes", headers=as_(who),
                       json={"data_zmiany": change, "nowe_stanowisko": "Kierownik zespołu", **extra})


def fresh_cycle(st, start: date):
    """Grzegorz: previous evaluation drawn up on `start`, criteria set and confirmed."""
    svc = st.evaluations
    old = svc.cycles.find_open_for(EMP)
    svc.cycles.delete(old.id)
    c = svc.start_cycle(EMP, start_date=start)
    svc.set_criteria(c.id, BOSS, [])
    svc.confirm_criteria(c.id, EMP)
    return c


def test_within_six_months_new_criteria_and_the_new_sheet(st):
    c = fresh_cycle(st, date(2026, 1, 15))
    before = st.evaluations.evaluation_deadline(c.id)
    r = post(st, "2026-03-02", nowy_arkusz="B")
    out = r.json()
    assert r.status_code == 201 and out["rodzaj"] == "NOWE_KRYTERIA" and out["termin"] == "2026-04-01"
    assert out["arkusz_zmieniony"] and out["ocena"]["arkusz"] == "B"
    assert out["ocena"]["status"] == "KRYTERIA_DO_WYZNACZENIA"
    assert out["ocena"]["czesc_i"]["termin_oceny"] == before.isoformat()  # § 9 ust. 1: unchanged
    assert "§ 9 ust. 1" in out["wyjasnienie"]
    assert st.directory.get(EMP).position == "Kierownik zespołu" and st.directory.get(EMP).sheet == "B"
    changes = client.get(f"/api/evaluations/{c.id}/deadline-changes", headers=as_(BOSS)).json()
    assert changes == []  # no DeadlineChange for new criteria (docs/model-danych.md)


def test_after_six_months_an_evaluation_in_the_window(st):
    c = fresh_cycle(st, date(2025, 6, 2))
    out = post(st, "2026-03-02", nowy_arkusz="B").json()
    assert out["rodzaj"] == "OCENA" and out["najwczesniej"] == "2026-02-23" and out["termin"] == "2026-04-01"
    assert out["ocena"]["czesc_i"]["termin_oceny"] == "2026-04-01"
    assert out["ocena"]["arkusz"] == "C" and not out["arkusz_zmieniony"]  # the evaluation covers the old post
    [change] = client.get(f"/api/evaluations/{c.id}/deadline-changes", headers=as_(BOSS)).json()
    assert change["powod"] == "ZMIANA_STANOWISKA" and change["nowy_termin"] == "2026-04-01"


@pytest.mark.parametrize("change,kind", [("2026-03-15", "NOWE_KRYTERIA"), ("2026-03-16", "OCENA")])
def test_the_six_month_boundary(st, change, kind):
    fresh_cycle(st, date(2025, 9, 15))  # 6 months end on 15.03.2026 – only a later change is "more than 6"
    assert post(st, change).json()["rodzaj"] == kind


def test_rights(st):
    fresh_cycle(st, date(2026, 1, 15))
    assert post(st, "2026-03-02", who=EMP).status_code == 403
    assert post(st, "2026-03-02", who=OTHER).status_code == 403
    assert post(st, "2026-03-02", who=HR).status_code == 201


def test_before_the_reference_date_is_rejected(st):
    fresh_cycle(st, date(2026, 1, 15))
    assert post(st, "2025-12-01").status_code == 422
