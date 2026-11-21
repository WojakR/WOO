"""Start of an evaluation (UC1), absences moving the deadline (UC8) and the sheet PDF (UC6)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


def _num(st, employee_id: str) -> int:
    return st.employee_number(employee_id)


def _eid(st) -> int:
    return int(st.evaluations.cycles.find_open_for(EMP).id)


# ---------------------------------------------------------------- start (UC1)

def test_second_open_cycle_is_409(st):
    # the simple seed already opened a cycle for Grzegorz
    r = client.post("/api/evaluations", json={"oceniany_id": _num(st, EMP)}, headers={"X-User-Id": BOSS})
    assert r.status_code == 409 and r.json()["kod"] == "CYKL_OTWARTY"


def test_start_creates_cycle_with_server_deadlines(st):
    st.evaluations.cycles._items.clear()  # nobody has an open cycle
    r = client.post("/api/evaluations", json={"oceniany_id": _num(st, EMP), "data_poczatku_cyklu": "2026-06-15"},
                    headers={"X-User-Id": BOSS})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "KRYTERIA_DO_WYZNACZENIA"
    assert body["czesc_i"]["termin_wyznaczenia_kryteriow"] == "2026-07-15"  # § 7 pkt 1: 30 days


def test_person_without_evaluator_cannot_be_evaluated(st):
    r = client.post("/api/evaluations", json={"oceniany_id": _num(st, BOSS)})
    assert r.status_code == 409 and r.json()["kod"] == "BRAK_OCENIAJACEGO"


def test_only_hr_or_own_evaluator_can_start(st):
    r = client.post("/api/evaluations", json={"oceniany_id": _num(st, EMP)}, headers={"X-User-Id": EMP})
    assert r.status_code == 403
    assert client.post("/api/evaluations", json={"oceniany_id": 9999}).status_code == 404


# ---------------------------------------------------------------- absences (UC8)

def test_long_justified_absence_moves_deadline_automatically(st):
    eid, num = _eid(st), _num(st, EMP)
    before = st.evaluations.evaluation_deadline(str(eid))
    r = client.post(f"/api/employees/{num}/absences", json={"od": "2026-07-01", "do": "2026-08-31", "typ": "L4"},
                    headers={"X-User-Id": BOSS})
    assert r.status_code == 201
    a = r.json()
    assert a["dni"] == 62 and a["evaluation_id"] == eid
    assert a["zmiana_terminu"]["status"] == "AUTO" and a["zmiana_terminu"]["stary_termin"] == before.isoformat()
    assert date.fromisoformat(a["termin_oceny"]) > before
    changes = client.get(f"/api/evaluations/{eid}/deadline-changes", headers={"X-User-Id": BOSS}).json()
    assert len(changes) == 1
    listed = client.get(f"/api/employees/{num}/absences", headers={"X-User-Id": EMP}).json()
    assert [x["id"] for x in listed] == [a["id"]]  # the evaluated person may read their own absences


def test_short_or_unjustified_absence_keeps_deadline(st):
    num = _num(st, EMP)
    short = client.post(f"/api/employees/{num}/absences", json={"od": "2026-07-01", "do": "2026-07-10",
                                                               "typ": "URLOP_WYPOCZYNKOWY"}).json()
    assert short["zmiana_terminu"] is None
    unjust = client.post(f"/api/employees/{num}/absences", json={"od": "2026-09-01", "do": "2026-11-30",
                                                                "typ": "NIEUSPRAWIEDLIWIONA"}).json()
    assert unjust["zmiana_terminu"] is None and unjust["usprawiedliwiona"] is False


def test_absence_rules(st):
    num = _num(st, EMP)
    assert client.post(f"/api/employees/{num}/absences", json={"od": "2026-07-01", "do": "2026-07-10", "typ": "L4"},
                       headers={"X-User-Id": EMP}).status_code == 403  # the evaluated person cannot report
    bad = client.post(f"/api/employees/{num}/absences", json={"od": "2026-07-10", "do": "2026-07-01", "typ": "L4"})
    assert bad.status_code == 422


# ---------------------------------------------------------------- PDF (UC6)

def test_pdf_is_a_draft_before_submission(st):
    r = client.get(f"/api/evaluations/{_eid(st)}/pdf", headers={"X-User-Id": BOSS})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "ocena-okresowa-grzegorz-wzor" in r.headers["content-disposition"]


def test_pdf_only_for_people_of_the_evaluation(st):
    assert client.get(f"/api/evaluations/{_eid(st)}/pdf", headers={"X-User-Id": "adam.wzor"}).status_code == 403
