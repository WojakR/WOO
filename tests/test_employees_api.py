"""T6: widok „Pracownicy" – filters, paging, the order of the history and who sees whom."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS, OTHER_BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "romuald.gut", "kadry"


def as_(who):
    return {"X-User-Id": who}


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 1), ai_mode="off")


def finish(st, employee, evaluator, score):
    """Draw up and acknowledge the employee's open evaluation; the next cycle starts by itself."""
    svc = st.evaluations
    cid = svc.cycles.find_open_for(employee).id
    svc.set_criteria(cid, evaluator, [])
    svc.confirm_criteria(cid, employee)
    svc.record_review_meeting(cid, evaluator)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, evaluator, scores={i: score for i in ids}, justification="Uzasadnienie.",
                          iprz_conclusions="Szkolenie.")
    svc.acknowledge(cid, employee)
    return cid


def names(resp):
    return {p["pracownik"]["imie"] + " " + p["pracownik"]["nazwisko"] for p in resp.json()["pozycje"]}


def test_hr_sees_everyone_with_paging(st):
    r = client.get("/api/employees", headers=as_(HR), params={"na_strone": 3})
    body = r.json()
    assert r.status_code == 200 and body["razem"] == len(st.directory.all()) and len(body["pozycje"]) == 3
    page2 = client.get("/api/employees", headers=as_(HR), params={"na_strone": 3, "strona": 2}).json()
    assert {p["pracownik"]["id"] for p in body["pozycje"]}.isdisjoint({p["pracownik"]["id"] for p in page2["pozycje"]})


def test_manager_sees_only_their_subtree_and_themselves(st):
    seen = names(client.get("/api/employees", headers=as_(BOSS)))
    assert seen == {"Grzegorz Wzór", "Henryk Pryncypał"}
    other = st.employee_number("janina.nowak")
    assert client.get(f"/api/employees/{other}", headers=as_(BOSS)).status_code == 403
    assert client.get(f"/api/employees/{other}/evaluations", headers=as_(BOSS)).status_code == 403


def test_evaluated_person_sees_only_themselves(st):
    assert names(client.get("/api/employees", headers=as_(EMP))) == {"Grzegorz Wzór"}
    boss = st.employee_number(BOSS)
    assert client.get(f"/api/employees/{boss}", headers=as_(EMP)).status_code == 403
    assert client.get("/api/employees/9999", headers=as_(HR)).status_code == 404


def test_filters(st):
    finish(st, "janina.nowak", OTHER_BOSS, 1)  # negative
    by_unit = client.get("/api/employees", headers=as_(HR), params={"komorka": "Referat Przekładów"})
    assert names(by_unit) == {"Grzegorz Wzór", "Henryk Pryncypał"}
    assert "Referat Przekładów" in by_unit.json()["komorki"]
    sheet_b = client.get("/api/employees", headers=as_(HR), params={"arkusz": "B"}).json()
    assert sheet_b["pozycje"] and all(p["pracownik"]["arkusz"] == "B" for p in sheet_b["pozycje"])
    negative = client.get("/api/employees", headers=as_(HR), params={"wynik": "NEGATYWNA"})
    assert "Janina Nowak" in names(negative)
    assert all(p["ostatnia_ocena"]["wynik"] == "NEGATYWNA" for p in negative.json()["pozycje"])
    started = client.get("/api/employees", headers=as_(HR), params={"status": "KRYTERIA_DO_WYZNACZENIA"})
    assert all(p["biezaca_ocena"]["status"] == "KRYTERIA_DO_WYZNACZENIA" for p in started.json()["pozycje"])
    assert client.get("/api/employees", headers=as_(HR), params={"szukaj": "pryncyp"}).json()["razem"] == 1


def test_history_is_chronological_and_complete(st):
    number = st.employee_number(EMP)
    first = finish(st, EMP, BOSS, 7)
    st.clock.set(date(2026, 7, 1))
    second = finish(st, EMP, BOSS, 1)
    hist = client.get(f"/api/employees/{number}/evaluations", headers=as_(BOSS)).json()
    assert [h["zrodlo"] for h in hist] == ["DANE_KADROWE", "SYSTEM", "SYSTEM", "SYSTEM"]
    assert hist[0]["data_sporzadzenia"] == "2024-06-12" and hist[0]["wynik"] == "POZYTYWNA"
    assert [h["evaluation_id"] for h in hist[1:3]] == [int(first), int(second)]
    assert [h["wynik"] for h in hist[1:3]] == ["POZYTYWNA", "NEGATYWNA"]
    assert hist[3]["status"] == "KRYTERIA_DO_WYZNACZENIA" and hist[3]["wynik"] is None  # the open cycle
    me = client.get(f"/api/employees/{number}/evaluations", headers=as_(EMP))
    assert me.status_code == 200 and len(me.json()) == 4
    card = client.get(f"/api/employees/{number}", headers=as_(EMP)).json()
    assert card["ostatnia_ocena"]["wynik"] == "NEGATYWNA" and card["biezaca_ocena"]["evaluation_id"] == hist[3]["evaluation_id"]
