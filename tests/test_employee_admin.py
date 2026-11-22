"""Employees by hand (KPRM use cases: entering a person, the reporting line, editing, deleting the person's data)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)
AS_HR = {"X-User-Id": HR}


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 1), ai_mode="off")


def num(st, eid):
    return st.employee_number(eid)


def new_person(st, **extra):
    body = {"imie": "Łucja", "nazwisko": "Żądło", "stanowisko": "Specjalista", "komorka": "Departament Kadr",
            "przelozony": num(st, BOSS), "email": "lucja@urzad.example", "data_zatrudnienia": "2026-05-01"} | extra
    return client.post("/api/admin/employees", headers=AS_HR, json=body)


def test_add_a_person_with_a_supervisor_and_open_the_cycle(st):
    r = client.post("/api/admin/employees?uruchom_cykl=true", headers=AS_HR,
                    json={"imie": "Łucja", "nazwisko": "Żądło", "stanowisko": "Specjalista",
                          "przelozony": num(st, BOSS), "data_zatrudnienia": "2026-05-01"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["dane"]["id"] == "lucja.zadlo" and out["dane"]["arkusz"] == "C"  # C: no team, not head of office
    assert out["pracownik"]["przelozony"]["nazwisko"] == "Pryncypał" and out["uruchomiony_cykl"]
    e = st.directory.get("lucja.zadlo")
    assert e.evaluator_id == BOSS and e.office  # the office taken from the directory
    assert st.evaluations.cycles.find_open_for(e.id).evaluator_id == BOSS
    # the supervisor sees the new subordinate
    names = [p["pracownik"]["nazwisko"] for p in client.get("/api/employees", headers={"X-User-Id": BOSS}).json()["pozycje"]]
    assert "Żądło" in names
    assert new_person(st).json()["dane"]["id"] == "lucja.zadlo2"  # a namesake gets another id


def test_the_form_is_checked_like_the_hr_import(st):
    r = new_person(st, stopien_sluzbowy=3, urzednik_mianowany=False, email="zly-adres")
    assert r.status_code == 422
    texts = " ".join(w["komunikat"] for w in r.json()["walidacje"])
    assert "stopień służbowy ma tylko urzędnik" in texts and "nieprawidłowy adres" in texts
    assert new_person(st, przelozony=9999).status_code == 422
    assert client.post("/api/admin/employees", headers={"X-User-Id": BOSS},
                       json={"imie": "A", "nazwisko": "B", "stanowisko": "C"}).status_code == 403


def test_edit_and_change_the_reporting_line(st):
    pid = new_person(st).json()["pracownik"]["id"]
    form = client.get(f"/api/admin/employees/{pid}", headers=AS_HR).json()
    other = next(e for e in st.directory.all() if e.id not in (BOSS, "lucja.zadlo") and e.evaluator_id)
    form |= {"stanowisko": "Starszy specjalista", "przelozony": num(st, other.id)}
    r = client.put(f"/api/admin/employees/{pid}", headers=AS_HR, json=form)
    assert r.status_code == 200, r.text
    e = st.directory.get("lucja.zadlo")
    assert e.position == "Starszy specjalista" and e.evaluator_id == other.id and e.email == "lucja@urzad.example"
    # a loop in the structure is refused
    boss_form = client.get(f"/api/admin/employees/{num(st, other.id)}", headers=AS_HR).json()
    r = client.put(f"/api/admin/employees/{num(st, other.id)}", headers=AS_HR, json=boss_form | {"przelozony": pid})
    assert r.status_code == 422 and "cykl w strukturze" in r.json()["walidacje"][0]["komunikat"]


def test_supervisor_change_with_an_evaluation_in_progress_goes_through_the_evaluator_change(st):
    form = client.get(f"/api/admin/employees/{num(st, EMP)}", headers=AS_HR).json()
    other = next(e for e in st.directory.all() if e.id not in (BOSS, EMP) and e.evaluator_id)
    r = client.put(f"/api/admin/employees/{num(st, EMP)}", headers=AS_HR, json=form | {"przelozony": num(st, other.id)})
    assert r.status_code == 409 and "Zmiana oceniającego" in r.json()["komunikat"]
    # other data of the same person can still be edited
    assert client.put(f"/api/admin/employees/{num(st, EMP)}", headers=AS_HR,
                      json=form | {"komorka": "Nowa komórka"}).status_code == 200


def test_delete_needs_the_end_of_employment_and_no_subordinates(st):
    pre = client.get(f"/api/admin/employees/{num(st, BOSS)}/usuniecie", headers=AS_HR).json()
    assert not pre["mozna_usunac"]
    text = " ".join(pre["przeszkody"])
    assert "datę ustania stosunku pracy" in text and "jest oceniającym" in text
    r = client.post(f"/api/admin/employees/{num(st, BOSS)}/usuniecie", headers=AS_HR,
                    json={"data_ustania_zatrudnienia": "2026-05-31", "zatwierdzam": True})
    assert r.status_code == 409 and r.json()["walidacje"]


def test_delete_archives_closed_evaluations_and_keeps_only_an_anonymous_record(st):
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: 5 for i in ids}, iprz_conclusions="Szkolenie.")
    st.clock.set(date(2026, 6, 10))
    svc.acknowledge(cid, EMP)  # the next cycle opens on its own
    nxt = svc.cycles.find_open_for(EMP).id
    number = num(st, EMP)
    blocked = client.get(f"/api/admin/employees/{number}/usuniecie?data_ustania_zatrudnienia=2026-06-10",
                         headers=AS_HR).json()
    assert not blocked["mozna_usunac"] and "nie jest zamknięta" in " ".join(blocked["przeszkody"])  # objection period
    st.clock.set(date(2026, 7, 1))
    plan = client.get(f"/api/admin/employees/{number}/usuniecie?data_ustania_zatrudnienia=2026-06-30",
                      headers=AS_HR).json()
    assert plan["mozna_usunac"] and plan["do_archiwum"] == [int(cid)] and plan["do_usuniecia"] == [int(nxt)]
    assert client.post(f"/api/admin/employees/{number}/usuniecie", headers=AS_HR,
                       json={"data_ustania_zatrudnienia": "2026-06-30"}).status_code == 422  # not confirmed
    r = client.post(f"/api/admin/employees/{number}/usuniecie", headers=AS_HR,
                    json={"data_ustania_zatrudnienia": "2026-06-30", "zatwierdzam": True})
    assert r.status_code == 200 and r.json()["usunieto"]
    e = st.directory.get(EMP)
    assert e.removed_on == date(2026, 7, 1) and e.first_name == "" and e.email is None and e.position == ""
    assert e.employment_end == date(2026, 6, 30)  # the archive's retention counts from it
    assert num(st, EMP) == number  # ids of everyone else stay stable
    assert not [c for c in svc.cycles.list_all() if c.employee_id == EMP]
    assert st.archive_store().get(cid) is not None  # the evaluation stays in the personnel file part
    assert client.get("/api/employees", headers=AS_HR).json()["razem"] == len(
        [x for x in st.directory.all() if x.removed_on is None])
    assert client.get("/api/me", headers={"X-User-Id": EMP}).status_code == 403
    assert client.get(f"/api/admin/employees/{number}", headers=AS_HR).status_code == 404
