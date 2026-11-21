"""T7: change of the deadline (art. 81 ust. 8, § 8) – request, decision, letter, evaluator's planned absence."""
import dataclasses
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.api.state import DeputyRecord, reset_state
from app.domain.calendar import WorkingCalendar
from app.domain.deadline_change import check_deadline_change
from app.domain.errors import ValidationError
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend.main import app

client = TestClient(app)
EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
OLD = "2026-06-12"  # Grzegorz: previous evaluation 12.06.2024 -> 24 months


def as_(who):
    return {"X-User-Id": who}


@pytest.fixture
def st():
    st = reset_state(today=date(2026, 5, 4), ai_mode="off")
    st.eid = int(st.evaluations.cycles.find_open_for(EMP).id)
    return st


@pytest.fixture
def hr_approves(st):
    st.settings = dataclasses.replace(st.settings, deadline_change_approver="KADRY")
    return st


def request(st, new="2026-09-15", who=BOSS, reason="PRZEWIDYWANA_NIEOBECNOSC_OCENIANEGO",
            text="Planowany urlop rodzicielski ocenianego od 1.06 do 31.08.2026."):
    return client.post(f"/api/evaluations/{st.eid}/deadline-changes", headers=as_(who),
                       json={"powod": reason, "nowy_termin": new, "uzasadnienie": text})


def deadline(st):
    return client.get(f"/api/evaluations/{st.eid}", headers=as_(BOSS)).json()["czesc_i"]["termin_oceny"]


def test_request_then_acceptance_sets_the_new_deadline(hr_approves):
    st = hr_approves
    r = request(st)
    assert r.status_code == 201 and r.json()["status"] == "ZLOZONY" and r.json()["stary_termin"] == OLD
    assert deadline(st) == OLD  # nothing changes until HR decides
    assert request(st).status_code == 409  # one pending request at a time
    assert client.post(f"/api/deadline-changes/{r.json()['id']}/decision", headers=as_(BOSS),
                       json={"status": "ZAAKCEPTOWANY"}).status_code == 403
    d = client.post(f"/api/deadline-changes/{r.json()['id']}/decision", headers=as_(HR),
                    json={"status": "ZAAKCEPTOWANY", "komentarz": "OK"}).json()
    assert d["status"] == "ZAAKCEPTOWANY" and d["nowy_termin"] == "2026-09-15" and d["pismo_pdf"]
    assert deadline(st) == "2026-09-15"
    notes = client.get("/api/notifications", headers=as_(EMP)).json()
    assert any(n["typ"] == "ZMIANA_TERMINU" and "15.09.2026" in n["tresc"] for n in notes)


def test_rejection_keeps_the_old_deadline(hr_approves):
    st = hr_approves
    rid = request(st).json()["id"]
    d = client.post(f"/api/deadline-changes/{rid}/decision", headers=as_(HR),
                    json={"status": "ODRZUCONY", "komentarz": "Brak podstaw."}).json()
    assert d["status"] == "ODRZUCONY" and d["komentarz_decyzji"] == "Brak podstaw." and not d["pismo_pdf"]
    assert deadline(st) == OLD
    assert client.get(f"/api/deadline-changes/{rid}/pdf", headers=as_(BOSS)).status_code == 409
    assert client.post(f"/api/deadline-changes/{rid}/decision", headers=as_(HR),
                       json={"status": "ZAAKCEPTOWANY"}).status_code == 409


def test_by_default_the_evaluators_decision_applies_at_once(st):
    r = request(st, new="2026-09-13")  # a Sunday -> the next working day
    assert r.json()["status"] == "ZAAKCEPTOWANY" and r.json()["nowy_termin"] == "2026-09-14"
    assert deadline(st) == "2026-09-14"
    listed = client.get("/api/deadline-changes", headers=as_(HR)).json()
    assert listed[0]["id"] == r.json()["id"] and listed[0]["zlozyl"]["imie"] == "Henryk"


def test_letter_pdf_has_the_people_and_the_new_deadline(st):
    rid = request(st).json()["id"]
    r = client.get(f"/api/deadline-changes/{rid}/pdf", headers=as_(EMP))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    import io

    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    for part in ("ZMIANIE TERMINU", "Grzegorz", "Henryk", "12.06.2026", "15.09.2026", "art. 81 ust. 8 pkt 2"):
        assert part in text


def test_only_the_evaluator_changes_and_only_in_the_cases_of_the_act(st):
    assert request(st, who=EMP).status_code == 403
    r = request(st, reason="INNY")
    assert r.status_code == 422 and "art. 81 ust. 8" in r.json()["walidacje"][0]["komunikat"]
    assert request(st, text=" ").status_code == 422


def test_not_before_six_months_since_the_last_evaluation():
    rules, cal = kprm_rulebook(), WorkingCalendar()
    with pytest.raises(ValidationError, match="więcej niż 6 mies"):
        check_deadline_change("WNIOSEK_OCENIANEGO", date(2026, 1, 10), date(2028, 1, 10), date(2028, 3, 1),
                              date(2026, 7, 10), rules, cal, "wniosek")
    assert check_deadline_change("WNIOSEK_OCENIANEGO", date(2026, 1, 10), date(2028, 1, 10), date(2028, 3, 1),
                                 date(2026, 7, 11), rules, cal, "wniosek") == date(2028, 3, 1)


def test_evaluators_planned_absence_points_at_the_right_subordinates(st):
    boss = st.employee_number(BOSS)
    r = client.post("/api/evaluator-absences", headers=as_(BOSS), json={"oceniajacy_id": boss, "od": "2026-06-01",
                                                                         "do": "2026-07-15"})
    out = r.json()
    assert r.status_code == 201
    assert [h["oceniany"]["imie"] for h in out["podpowiedzi"]] == ["Grzegorz"]
    hint = out["podpowiedzi"][0]
    assert hint["termin"] == OLD and hint["rodzaj_terminu"] == "OCENA" and hint["zastepca"] is None
    assert hint["proponowany_termin"] == "2026-07-29" and hint["mozna_zmienic_termin"]  # 15.07 + 14 days
    other = client.post("/api/evaluator-absences", headers=as_(BOSS), json={"oceniajacy_id": boss,
                                                                             "od": "2026-08-01", "do": "2026-08-20"})
    assert other.json()["podpowiedzi"] == []
    assert client.post("/api/evaluator-absences", headers=as_(EMP), json={"oceniajacy_id": boss, "od": "2026-06-01",
                                                                           "do": "2026-07-15"}).status_code == 403


def test_a_deputy_covering_the_absence_is_suggested_instead(st):
    st.deputy_records.append(DeputyRecord(1, BOSS, "celina.przykladowa", date(2026, 5, 30), date(2026, 7, 31)))
    out = client.post("/api/evaluator-absences", headers=as_(HR), json={
        "oceniajacy_id": st.employee_number(BOSS), "od": "2026-06-01", "do": "2026-07-15"}).json()
    hint = out["podpowiedzi"][0]
    assert hint["zastepca"]["imie"] == "Celina" and hint["proponowany_termin"] is None
    assert "zastępca" in out["komunikat"]
