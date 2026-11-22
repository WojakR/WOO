"""Evaluation sheet, dashboard, HR partner and demo endpoints (app/api/evaluations.py) on the demo scenario."""
import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
AS_BOSS, AS_EMP, AS_HR = {"X-User-Id": BOSS}, {"X-User-Id": EMP}, {"X-User-Id": "kadry"}


@pytest.fixture(autouse=True)
def st():
    return reset_state(ai_mode="off", scenario=True)


def grzegorz_eval_id() -> int:
    [item] = client.get("/api/dashboard", headers=AS_BOSS).json()["pozycje"]
    assert item["oceniany"]["imie"] == "Grzegorz"
    return item["evaluation_id"]


def test_web_ui_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "Asystent Ocen Okresowych" in r.text
    assert client.get("/js/main.js").status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_me_users_and_meta():
    me = client.get("/api/me", headers=AS_BOSS).json()
    assert me["czy_oceniajacy"] and me["urzad"] == "Generalna Dyrekcja Przekładów i Przykładów"
    assert client.get("/api/me", headers=AS_HR).json()["rola"] == "KADRY"
    assert client.get("/api/me", headers={"X-User-Id": "nikt"}).status_code == 403
    assert {u["id"] for u in client.get("/api/users").json()} >= {"kadry", BOSS, EMP}
    meta = client.get("/api/meta").json()
    assert meta["dzis"] == "2026-05-25" and meta["funkcje_ai"]["hr_partner"] is True
    assert meta["funkcje_ai"]["model_dostepny"] is False  # AI off


def test_dashboard_scope_and_seed():
    item = client.get("/api/dashboard", headers=AS_BOSS).json()["pozycje"][0]
    assert (item["status"], item["termin"], item["dni_do_terminu"], item["pilnosc"], item["kto_dziala"]) == (
        "ROZMOWA_OCENIAJACA", "2026-06-12", 18, "WKROTCE", "OCENIAJACY")
    everyone = client.get("/api/dashboard", headers=AS_HR).json()["pozycje"]
    statuses = {i["oceniany"]["nazwisko"]: i["status"] for i in everyone}
    assert statuses["Kowal"] is None  # one cycle not started
    # one row per evaluation: whoever acknowledged a finished evaluation already has the next cycle running
    finished = {i["oceniany"]["id"] for i in everyone if i["status"] == "ZAKONCZONA"}
    assert finished and all(any(j["oceniany"]["id"] == p and j["status"] == "KRYTERIA_DO_WYZNACZENIA" for j in everyone)
                            for p in finished)
    assert len(everyone) == 12 + len(finished)  # 8 KPRM sample people + Barbara Przełożona's team of 4
    assert {i["pilnosc"] for i in everyone} >= {"PO_TERMINIE", "WKROTCE"}
    assert {i["wynik"] for i in everyone} >= {"POZYTYWNA", "NEGATYWNA"}


def test_evaluation_sheet_matches_demo_scenario():
    eid = grzegorz_eval_id()
    ev = client.get(f"/api/evaluations/{eid}", headers=AS_BOSS).json()
    assert ev["arkusz"] == "C" and ev["status"] == "ROZMOWA_OCENIAJACA"
    assert [k["typ"] for k in ev["kryteria"]] == ["OBOWIAZKOWE"] * 5 + ["DODATKOWE"] * 2
    assert ev["czesc_ii"]["srednia"] == 3.86 and ev["czesc_ii"]["poziom"] == "PONIZEJ"
    assert ev["czesc_ii"]["wynik"] == "NEGATYWNA"
    assert ev["dozwolone_akcje"] == ["ZATWIERDZ_OCENE"]
    assert {"punkty", "uzasadnienie", "wnioski_iprz"} <= set(ev["edytowalne_pola"])
    assert {w["kod"] for w in ev["walidacje"]} == {"UZASADNIENIE_WYMAGANE", "IPRZ_WYMAGANE"}
    as_emp = client.get(f"/api/evaluations/{eid}", headers=AS_EMP).json()
    assert as_emp["dozwolone_akcje"] == [] and as_emp["edytowalne_pola"] == []
    assert client.get(f"/api/evaluations/{eid}", headers={"X-User-Id": "adam.wzor"}).status_code == 403


def test_live_scores_evidence_and_suggestions():
    eid = grzegorz_eval_id()
    out = client.put(f"/api/evaluations/{eid}/scores", headers=AS_BOSS, json={"punkty": {"RZETELNOSC": 1}}).json()
    assert out["wynik"] == "NEGATYWNA"
    out = client.put(f"/api/evaluations/{eid}/scores", headers=AS_BOSS, json={"punkty": {
        "WYKORZYSTYWANIE_WIEDZY": 7, "RZETELNOSC": 7, "ORGANIZACJA_PRACY": 7, "WSPOLPRACA": 7,
        "KOMUNIKACJA": 7, "ORIENTACJA_NA_KLIENTA": 7, "KREATYWNOSC": 5}}).json()
    assert out["wynik"] == "POZYTYWNA" and out["poziom"] == "POWYZEJ"
    assert {w["kod"] for w in out["walidacje"]} == {"IPRZ_WYMAGANE"}
    assert client.put(f"/api/evaluations/{eid}/scores", headers=AS_BOSS,
                      json={"punkty": {"RZETELNOSC": 4}}).status_code == 422
    evidence = client.get(f"/api/evaluations/{eid}/evidence", headers=AS_BOSS).json()
    assert any(k["sugerowane_punkty"] for k in evidence["kryteria"]) and evidence["notatki_do_przypisania"] == 4
    assert client.get(f"/api/evaluations/{eid}/evidence", headers=AS_EMP).status_code == 403
    notes = client.get(f"/api/evaluations/{eid}/notes", headers=AS_BOSS).json()
    assert len(notes) == 34 and notes[0]["status_klasyfikacji"] in ("RECZNA", "BRAK")


def test_full_flow_through_actions_and_locks():
    eid = grzegorz_eval_id()
    ev = client.get(f"/api/evaluations/{eid}", headers=AS_BOSS).json()
    blocked = client.post(f"/api/evaluations/{eid}/actions/ZATWIERDZ_OCENE", headers=AS_BOSS, json={})
    assert blocked.status_code == 422 and blocked.json()["walidacje"]

    stale = client.patch(f"/api/evaluations/{eid}", headers=AS_BOSS,
                         json={"updated_at": "2020-01-01T00:00:00Z", "uzasadnienie": "x"})
    assert stale.status_code == 409 and stale.json()["kod"] == "KONFLIKT_WERSJI"
    ev = client.patch(f"/api/evaluations/{eid}", headers=AS_BOSS, json={
        "updated_at": ev["updated_at"], "uzasadnienie": "Liczne błędy w przekładach.",
        "wnioski_iprz": "Szkolenie z redakcji tekstu."}).json()
    assert ev["walidacje"] == []

    ev = client.post(f"/api/evaluations/{eid}/actions/ZATWIERDZ_OCENE", headers=AS_BOSS, json={}).json()
    assert ev["status"] == "OCENA_DO_ZAPOZNANIA" and ev["edytowalne_pola"] == []
    locked = client.put(f"/api/evaluations/{eid}/scores", headers=AS_BOSS, json={"punkty": {"RZETELNOSC": 9}})
    assert locked.status_code == 409 and locked.json()["kod"] == "POLE_ZABLOKOWANE"
    assert client.post(f"/api/evaluations/{eid}/actions/POTWIERDZ_ZAPOZNANIE", headers=AS_BOSS,
                       json={}).status_code == 403
    ev = client.post(f"/api/evaluations/{eid}/actions/POTWIERDZ_ZAPOZNANIE", headers=AS_EMP, json={}).json()
    assert ev["status"] == "ZAKONCZONA" and ev["czesc_ii"]["zapoznanie"]["at"]
    assert ev["czesc_ii"]["termin_sprzeciwu"]  # art. 83: objection window starts at acknowledgement


def test_criteria_stage_and_disallowed_transition():
    everyone = client.get("/api/dashboard", headers=AS_HR).json()["pozycje"]
    celina = next(i for i in everyone if i["oceniany"]["imie"] == "Celina")
    boss = {"X-User-Id": "dorota.oceniajaca"}
    eid = celina["evaluation_id"]
    r = client.put(f"/api/evaluations/{eid}/criteria/additional", headers=boss, json={"kody": ["RZETELNOSC"]})
    assert r.status_code == 422  # mandatory in sheet C
    ev = client.put(f"/api/evaluations/{eid}/criteria/additional", headers=boss,
                    json={"kody": ["KREATYWNOSC", "NEGOCJOWANIE"]}).json()
    assert [k["criterion_kod"] for k in ev["kryteria"] if k["typ"] == "DODATKOWE"] == ["KREATYWNOSC", "NEGOCJOWANIE"]
    r = client.post(f"/api/evaluations/{eid}/actions/ROZPOCZNIJ_ROZMOWE", headers=boss, json={})
    assert r.status_code == 409 and r.json()["kod"] == "PRZEJSCIE_NIEDOZWOLONE"
    ev = client.post(f"/api/evaluations/{eid}/actions/ZATWIERDZ_KRYTERIA", headers=boss, json={}).json()
    assert ev["status"] == "KRYTERIA_DO_POTWIERDZENIA"


def test_draft_and_hr_partner_work_without_ai():
    eid = grzegorz_eval_id()
    d = client.post(f"/api/evaluations/{eid}/ai/draft", headers=AS_BOSS, json={"rodzaj": "UZASADNIENIE"})
    assert d.status_code == 200 and d.json()["tekst"] and d.json()["zrodlo"] == "SZABLON"
    hr = client.get(f"/api/evaluations/{eid}/hr-partner", headers=AS_BOSS).json()
    assert {"PRZECIAZENIE", "ZMIANA_OBOWIAZKOW"} <= {sg["typ"] for sg in hr["sygnaly"]}
    sid = hr["sygnaly"][0]["id"]
    assert client.post(f"/api/hr-signals/{sid}/decision", json={"status": "ODRZUCONY"}).status_code == 204
    again = client.get(f"/api/evaluations/{eid}/hr-partner", headers=AS_BOSS).json()
    assert again["sygnaly"][0]["status"] == "ODRZUCONY"
    assert client.get(f"/api/evaluations/{eid}/hr-partner", headers=AS_EMP).status_code == 403


def test_demo_clock_and_reset():
    client.post("/api/demo/clock", json={"przesun_dni": 30})
    item = client.get("/api/dashboard", headers=AS_BOSS).json()["pozycje"][0]
    assert item["dni_do_terminu"] == -12 and item["pilnosc"] == "PO_TERMINIE"
    assert client.post("/api/demo/reset").status_code == 204
    assert client.get("/api/meta").json()["dzis"] == "2026-05-25"


def test_demo_team_at_the_start_of_the_process():
    """Barbara Przełożona evaluates four people whose cycles have just started (criteria still to be set)."""
    boss = {"X-User-Id": "barbara.przelozona"}
    me = client.get("/api/me", headers=boss).json()
    assert me["czy_oceniajacy"]
    team = client.get("/api/dashboard", headers=boss).json()["pozycje"]
    assert {i["oceniany"]["nazwisko"] for i in team} == {"Próbny", "Wzorcowa", "Przykładny", "Testowa"}
    assert {i["status"] for i in team} == {"KRYTERIA_DO_WYZNACZENIA"}
    assert all(i["kto_dziala"] == "OCENIAJACY" for i in team)


def test_dashboard_lists_the_users_own_evaluation_apart_from_the_people_they_evaluate():
    mine = client.get("/api/dashboard", headers=AS_EMP).json()
    assert mine["pozycje"] == []  # Grzegorz evaluates nobody
    [own] = mine["moje"]
    assert own["oceniany"]["nazwisko"] == "Wzór" and own["status"] == "ROZMOWA_OCENIAJACA"
    boss = client.get("/api/dashboard", headers=AS_BOSS).json()
    assert boss["moje"] == []  # Henryk has no evaluation of his own in the scenario
    assert all(i["oceniany"]["nazwisko"] != "Pryncypał" for i in boss["pozycje"])
    assert client.get("/api/dashboard", headers=AS_HR).json()["moje"] == []  # HR account is not an employee
