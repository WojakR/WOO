"""Sheet A/B/C suggested from the position (§ 3 of the regulation), mapping in arkusze.json."""
import dataclasses
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.employee import Employee
from app.domain.errors import InvalidTransition, ValidationError
from app.domain.sheet_choice import suggest_sheet
from backend import kprm
from backend.main import app

MAPPING = kprm.sheets()["dobor_arkusza"]
client = TestClient(app)


def person(**kw) -> Employee:
    return Employee("x", "Jan", "Test", "Urząd", "Wydział", "stanowisko", "C", "szef", **kw)


@pytest.mark.parametrize("flags, sheet, why", [
    ({"is_office_head": True, "manages_people": True}, "A", "kierownikiem urzędu"),
    ({"is_office_head": False, "manages_people": True}, "B", "kierowaniu pracownikami"),
    ({"is_office_head": False, "manages_people": False}, "C", "bez kierowania"),
])
def test_three_cases(flags, sheet, why):
    s = suggest_sheet(person(**flags), MAPPING)
    assert s.sheet == sheet and why in s.reason and s.warning is None


def test_missing_data_gives_c_with_a_warning():
    s = suggest_sheet(person(), MAPPING)
    assert s.sheet == "C" and "Brak danych" in s.warning
    assert suggest_sheet(person(is_office_head=False), MAPPING).warning  # one flag still unknown


def test_start_uses_the_suggestion_and_returns_the_reason():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    c = st.evaluations.cycles.find_open_for("janina.nowak")  # naczelnik: manages people
    assert c.sheet == "B" and c.sheet_suggested == "B" and "kierowaniu" in c.sheet_reason


def test_hr_changes_the_sheet_with_a_reason_only_before_criteria_are_approved():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for("grzegorz.wzor").id
    url = f"/api/evaluations/{cid}/sheet"
    assert client.put(url, headers={"X-User-Id": "henryk.pryncypal"},
                      json={"arkusz": "B", "uzasadnienie": "x"}).status_code == 403
    assert client.put(url, headers={"X-User-Id": "kadry"}, json={"arkusz": "B", "uzasadnienie": " "}).status_code == 422
    r = client.put(url, headers={"X-User-Id": "kadry"},
                   json={"arkusz": "B", "uzasadnienie": "Od 1.06 kieruje zespołem tłumaczy."})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["arkusz"] == "B" and ev["dobor_arkusza"]["sugerowany"] == "C"
    assert ev["dobor_arkusza"]["zmiany"][0]["uzasadnienie"].startswith("Od 1.06")
    svc.set_criteria(cid, "henryk.pryncypal", [])
    with pytest.raises(InvalidTransition, match="przed zatwierdzeniem kryteriów"):
        svc.change_sheet(cid, "C", "powrót", "kadry")
    r = client.put(url, headers={"X-User-Id": "kadry"}, json={"arkusz": "C", "uzasadnienie": "powrót"})
    assert r.status_code == 409


def test_another_sheet_at_start_needs_a_reason():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    svc.cycles.delete(svc.cycles.find_open_for("grzegorz.wzor").id)
    with pytest.raises(ValidationError, match="uzasadnienie"):
        svc.start_cycle("grzegorz.wzor", sheet="B")
    c = svc.start_cycle("grzegorz.wzor", sheet="B", sheet_reason="kieruje zespołem")
    assert c.sheet == "B" and c.sheet_changes[0][2:] == ("C", "B", "kieruje zespołem")


def test_suggestion_endpoint():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    num = st.employee_number("janina.kowalska")
    r = client.get(f"/api/employees/{num}/sheet-suggestion", headers={"X-User-Id": "kadry"})
    assert r.json()["sugerowany"] == "A"


def test_without_hr_data_the_cycle_gets_c_and_the_warning():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    emp = dataclasses.replace(st.directory.get("grzegorz.wzor"), is_office_head=None, manages_people=None)
    st.directory._by_id[emp.id] = emp
    svc.cycles.delete(svc.cycles.find_open_for(emp.id).id)
    c = svc.start_cycle(emp.id)
    assert c.sheet == "C" and c.sheet_warning
