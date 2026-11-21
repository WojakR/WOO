"""Administrator settings: requirements of the regulation, visibility scope, AI switches; automatic deadlines."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.api.state as state_mod
from app.api.state import get_state, reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
ADMIN = {"X-User-Id": "kadry"}
AS_BOSS = {"X-User-Id": BOSS}


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


def _eid(st) -> int:
    return int(st.evaluations.cycles.find_open_for(EMP).id)


def restart():
    state_mod.save_state()
    state_mod._state = None
    return get_state()


# ---------------------------------------------------------------- requirements of the regulation

def test_everyone_reads_the_requirements_only_admin_edits(st):
    r = client.get("/api/ustawienia/reguly", headers=AS_BOSS).json()
    keys = {p["klucz"]: p for p in r["parametry"]}
    assert keys["sprzeciw_dni_od_zapoznania"]["wartosc"] == 7 and keys["ocena_co_miesiecy"]["wartosc"] == 24
    assert r["moze_edytowac"] is False and not r["zmienione"]
    assert any(w["tytul"] == "Skala ocen cząstkowych" for w in r["wymagania"])
    body = {"wartosci": {"sprzeciw_dni_od_zapoznania": 10}, "podstawa_zmiany": "nowelizacja"}
    assert client.put("/api/ustawienia/reguly", json=body, headers=AS_BOSS).status_code == 403


def test_amendment_changes_deadlines_everywhere_and_survives_restart(st):
    eid = _eid(st)
    before = client.get(f"/api/evaluations/{eid}", headers=AS_BOSS).json()["czesc_i"]["termin_wyznaczenia_kryteriow"]
    r = client.put("/api/ustawienia/reguly", headers=ADMIN, json={
        "wartosci": {"wyznaczenie_kryteriow_dni_od_poprzedniej_oceny_lub_zatrudnienia": 45},
        "podstawa_zmiany": "nowelizacja rozporządzenia, Dz. U. 2027 poz. 1"})
    assert r.status_code == 200 and r.json()["zmienione"] and r.json()["zmiany"][0]["nowa"] == 45
    # an existing cycle keeps its stored criteria deadline; a new cycle uses the amended term
    st2 = get_state()
    st2.evaluations.cycles._items.clear()
    ev = client.post("/api/evaluations", headers=AS_BOSS,
                     json={"oceniany_id": st2.employee_number(EMP), "data_poczatku_cyklu": "2026-06-15"}).json()
    assert ev["czesc_i"]["termin_wyznaczenia_kryteriow"] == "2026-07-30"  # 15.06 + 45 days
    assert before != ev["czesc_i"]["termin_wyznaczenia_kryteriow"]
    st3 = restart()
    assert st3.evaluations.rules.criteria_days == 45 and len(st3.rule_changes) == 1


def test_values_are_validated_and_reset_restores_the_regulation(st):
    bad = client.put("/api/ustawienia/reguly", headers=ADMIN,
                     json={"wartosci": {"sprzeciw_dni_od_zapoznania": 0}, "podstawa_zmiany": "test"})
    assert bad.status_code == 422
    client.put("/api/ustawienia/reguly", headers=ADMIN,
               json={"wartosci": {"max_kryteriow_dodatkowych": 2}, "podstawa_zmiany": "nowelizacja"})
    assert client.get("/api/meta").json()["maks_kryteriow_dodatkowych"] == 2
    r = client.delete("/api/ustawienia/reguly", headers=ADMIN).json()
    assert not r["zmienione"] and client.get("/api/meta").json()["maks_kryteriow_dodatkowych"] == 3
    assert len(r["zmiany"]) == 2  # change + restore, both logged


# ---------------------------------------------------------------- visibility (supervisor tree)

def test_admin_switches_visibility_scope(st):
    assert client.get("/api/ustawienia/urzad").json()["zakres_widocznosci"] == "PODDRZEWO"
    assert client.put("/api/ustawienia/urzad", json={"zakres_widocznosci": "BEZPOSREDNI"},
                      headers=AS_BOSS).status_code == 403
    r = client.put("/api/ustawienia/urzad", json={"zakres_widocznosci": "BEZPOSREDNI"}, headers=ADMIN).json()
    assert r["zakres_widocznosci"] == "BEZPOSREDNI"
    assert restart().settings.visibility_scope.value == "BEZPOSREDNI"


# ---------------------------------------------------------------- AI switches

def test_my_switch_turns_off_ai_and_hr_partner_for_me_only():
    reset_state(today=date(2026, 6, 15), ai_mode="local")
    assert client.get("/api/meta", headers=AS_BOSS).json()["tryb_ai"] == "LOCAL"
    r = client.put("/api/me/asystent", json={"asystent_ai": False, "hr_partner": False}, headers=AS_BOSS).json()
    assert r == {"asystent_ai": False, "hr_partner": False, "asystent_ai_w_urzedzie": True,
                 "hr_partner_w_urzedzie": True}
    meta = client.get("/api/meta", headers=AS_BOSS).json()
    assert meta["tryb_ai"] == "OFF" and meta["funkcje_ai"]["hr_partner"] is False
    assert client.get("/api/meta", headers={"X-User-Id": "bartlomiej.przelozony"}).json()["tryb_ai"] == "LOCAL"
    eid = int(get_state().evaluations.cycles.find_open_for(EMP).id)
    r = client.get(f"/api/evaluations/{eid}/hr-partner", headers=AS_BOSS)
    assert r.status_code == 409 and r.json()["kod"] == "HR_PARTNER_WYLACZONY"
    # the assistant still works – without the model (templates), so no request goes to Ollama
    prep = client.post(f"/api/evaluations/{eid}/ai/conversation-prep", headers=AS_BOSS).json()
    assert prep["zrodlo_tekstow"] == "SZABLON"


def test_office_switch_wins_over_personal_setting():
    reset_state(today=date(2026, 6, 15), ai_mode="local")
    client.put("/api/ustawienia/urzad", json={"asystent_ai": False}, headers=ADMIN)
    assert client.get("/api/meta", headers=AS_BOSS).json()["tryb_ai"] == "OFF"
    assert client.get("/api/me/asystent", headers=AS_BOSS).json()["asystent_ai_w_urzedzie"] is False
    assert restart().ai_office is False


# ---------------------------------------------------------------- automatic deadlines

def _kinds(ev):
    return {t["rodzaj"]: t for t in ev["terminy"]}


def test_deadlines_follow_the_process(st):
    st.evaluations.cycles._items.clear()
    cid = st.evaluations.start_cycle(EMP, start_date=date(2026, 6, 15)).id
    eid = int(cid)
    t = _kinds(client.get(f"/api/evaluations/{eid}", headers=AS_BOSS).json())
    assert set(t) == {"KRYTERIA", "OCENA"} and t["KRYTERIA"]["stan"] == "AKTUALNY"
    assert t["OCENA"]["podstawa"].startswith("art. 81 ust. 4")
    svc = st.evaluations
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.edit(cid, BOSS, scores={c: 5 for c in ids}, iprz_conclusions="Szkolenie.")
    svc.submit_evaluation(cid, BOSS)  # entering the evaluation -> acknowledgement "niezwłocznie"
    t = _kinds(client.get(f"/api/evaluations/{eid}", headers=AS_BOSS).json())
    assert t["OCENA"]["stan"] == "SPELNIONY" and t["ZAPOZNANIE"]["data"] is None
    st.clock.set(date(2026, 6, 17))
    svc.acknowledge(cid, EMP)  # the employee's signature starts the objection period and the next cycle
    t = _kinds(client.get(f"/api/evaluations/{eid}", headers=AS_BOSS).json())
    assert t["SPRZECIW"]["data"] == "2026-06-24"  # 7 days from 17.06
    # 24 months from drawing up (15.06.2026) = 15.06.2028, Corpus Christi -> next working day
    assert t["KOLEJNA_OCENA"]["data"] == "2028-06-16"
    assert t["KRYTERIA_NASTEPNE"]["data"] == "2026-07-15"  # 30 days from drawing up
    assert t["KOLEJNA_OCENA"]["stan"] == "NASTEPNY_OKRES"


def test_objection_deadlines_appear_after_filing_and_rejection(st):
    st.evaluations.cycles._items.clear()
    svc = st.evaluations
    cid = svc.start_cycle(EMP, start_date=date(2026, 6, 15)).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.edit(cid, BOSS, scores={c: 5 for c in ids}, iprz_conclusions="Szkolenie.")
    svc.submit_evaluation(cid, BOSS)
    svc.acknowledge(cid, EMP)
    svc.file_objection(cid, EMP, "Nie zgadzam się z oceną komunikacji.")  # 15.06.2026
    t = _kinds(client.get(f"/api/evaluations/{cid}", headers=AS_BOSS).json())
    assert t["SPRZECIW"]["stan"] == "SPELNIONY"
    assert t["ROZPATRZENIE_SPRZECIWU"]["data"] == "2026-06-29" and t["ROZPATRZENIE_SPRZECIWU"]["stan"] == "AKTUALNY"
    assert "KOLEJNA_OCENA" not in t  # the evaluation is not final while the objection is pending
    svc.decide_objection(cid, "kadry", False, "Ocena zgodna z notatkami z okresu.")
    t = _kinds(client.get(f"/api/evaluations/{cid}", headers=AS_BOSS).json())
    assert t["ROZPATRZENIE_SPRZECIWU"]["stan"] == "SPELNIONY" and t["SAD_PRACY"]["data"] == "2026-06-29"
    assert t["KOLEJNA_OCENA"]["stan"] == "NASTEPNY_OKRES"
