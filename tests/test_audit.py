"""T3: dziennik zmian – every step of a full cycle leaves an entry with the right user; HR reads, others 403."""
import inspect
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import delete

from app.api.state import reset_state
from app.infrastructure import audit_log
from backend import db
from backend.main import app

client = TestClient(app)
EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"


def as_(who):
    return {"X-User-Id": who}


@pytest.fixture
def st():
    with db.session() as s:  # the test database is shared by all tests; ids repeat after every reset
        s.exec(delete(db.AuditEntry))
        s.commit()
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    st.eid = int(st.evaluations.cycles.find_open_for(EMP).id)
    return st


def entries(eid):
    return [(e.user_id, e.action, e.field) for e in audit_log.for_evaluation(eid)]


def act(eid, akcja, who, **body):
    r = client.post(f"/api/evaluations/{eid}/actions/{akcja}", headers=as_(who), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_cycle_is_logged_step_by_step_with_the_right_user(st):
    eid = st.eid
    assert client.put(f"/api/evaluations/{eid}/criteria/additional", headers=as_(BOSS),
                      json={"kody": ["KREATYWNOSC"]}).status_code == 200
    act(eid, "ZATWIERDZ_KRYTERIA", BOSS)
    act(eid, "POTWIERDZ_KRYTERIA", EMP)
    note = client.post(f"/api/evaluations/{eid}/notes", headers=as_(BOSS),
                       json={"data": "2026-06-01", "tresc": "Tajna obserwacja przełożonego."})
    assert note.status_code == 201
    act(eid, "ROZPOCZNIJ_ROZMOWE", BOSS)
    ev = client.get(f"/api/evaluations/{eid}", headers=as_(BOSS)).json()
    punkty = {k["criterion_kod"]: 7 for k in ev["kryteria"]}
    assert client.put(f"/api/evaluations/{eid}/scores", headers=as_(BOSS), json={"punkty": punkty}).status_code == 200
    ev = client.get(f"/api/evaluations/{eid}", headers=as_(BOSS)).json()
    assert client.patch(f"/api/evaluations/{eid}", headers=as_(BOSS), json={
        "updated_at": ev["updated_at"], "wnioski_iprz": "Szkolenie z redakcji."}).status_code == 200
    act(eid, "ZATWIERDZ_OCENE", BOSS)
    assert client.get(f"/api/evaluations/{eid}/pdf", headers=as_(BOSS)).status_code == 200
    act(eid, "POTWIERDZ_ZAPOZNANIE", EMP)
    act(eid, "ZLOZ_SPRZECIW", EMP, komentarz="Nie zgadzam się.")

    log = entries(eid)
    steps = [(u, a) for u, a, f in log if a != "ZMIANA_POLA"]
    assert steps == [
        (BOSS, "KRYTERIA_DODATKOWE"), (BOSS, "AKCJA_ZATWIERDZ_KRYTERIA"), (EMP, "AKCJA_POTWIERDZ_KRYTERIA"),
        (BOSS, "NOTATKA_DODANA"), (BOSS, "AKCJA_ROZPOCZNIJ_ROZMOWE"), (BOSS, "OCENY_CZASTKOWE"),
        (BOSS, "EDYCJA_ARKUSZA"), (BOSS, "AKCJA_ZATWIERDZ_OCENE"), (BOSS, "POBRANIE_PDF"),
        (EMP, "AKCJA_POTWIERDZ_ZAPOZNANIE"), (EMP, "AKCJA_ZLOZ_SPRZECIW")]
    fields = {(u, f) for u, a, f in log if a == "ZMIANA_POLA"}
    assert {(BOSS, "additional_criteria"), (BOSS, "status"), (EMP, "criteria_confirmed_on"), (BOSS, "scores"),
            (BOSS, "iprz_conclusions"), (BOSS, "result"), (EMP, "acknowledged_on"),
            (EMP, "objection_text")} <= fields
    status_changes = [e for e in audit_log.for_evaluation(eid) if e.field == "status"]
    assert (status_changes[0].before, status_changes[0].after) == ("cykl_rozpoczety", "kryteria_wyznaczone")
    # a note is logged as a fact – its text never lands in the log
    assert all("Tajna" not in (e.before or "") + (e.after or "") for e in audit_log.for_evaluation(eid))


def test_failed_requests_leave_no_entry(st):
    r = client.post(f"/api/evaluations/{st.eid}/actions/POTWIERDZ_KRYTERIA", headers=as_(EMP), json={})
    assert r.status_code >= 400
    assert entries(st.eid) == []


def test_absence_moving_a_deadline_is_logged_on_the_evaluation(st):
    number = st.employee_number(EMP)
    r = client.post(f"/api/employees/{number}/absences", headers=as_(HR),
                    json={"od": "2026-06-02", "do": "2026-08-20", "typ": "L4"})
    assert r.status_code == 201, r.text
    assert (HR, "ZMIANA_POLA", "absences") in entries(st.eid)


def test_office_settings_change_is_logged(st):
    r = client.put("/api/ustawienia/urzad", headers=as_(HR), json={"zakres_widocznosci": "BEZPOSREDNI"})
    assert r.status_code == 200, r.text
    log = audit_log.all_entries(10)
    assert any(e.action == "ZMIANA_USTAWIEN" and e.field == "zakres_widocznosci" and e.user_id == HR for e in log)


def test_only_hr_reads_the_log(st):
    act(st.eid, "ZATWIERDZ_KRYTERIA", BOSS)
    assert client.get(f"/api/evaluations/{st.eid}/audit", headers=as_(BOSS)).status_code == 403
    assert client.get(f"/api/evaluations/{st.eid}/audit", headers=as_(EMP)).status_code == 403
    out = client.get(f"/api/evaluations/{st.eid}/audit", headers=as_(HR)).json()
    assert out[0]["akcja"] == "AKCJA_ZATWIERDZ_KRYTERIA" and out[0]["uzytkownik_nazwa"] == "Henryk Pryncypał"
    assert client.get("/api/evaluations/99999/audit", headers=as_(HR)).status_code == 404


def test_the_adapter_is_append_only():
    src = inspect.getsource(audit_log)
    assert "delete" not in src.lower().replace("deliberately no update or delete", "")
    assert "update" not in src.lower().replace("deliberately no update or delete", "")
