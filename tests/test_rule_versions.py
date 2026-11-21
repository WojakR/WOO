"""T20: every change of the requirements is a version with a start date; a cycle follows the version in force on
the day its criteria were set (new cycles: the version on the day they start). An amendment never changes a
running evaluation, a future version does not work before its date."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import state as state_mod
from app.api.state import get_state, reset_state
from app.domain.errors import ValidationError
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
ADMIN = {"X-User-Id": HR}
client = TestClient(app)


@pytest.fixture
def st():
    """Grzegorz: criteria set on 1.06.2026 (published regulation), evaluation acknowledged on Wed 10.06.2026."""
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: 5 for i in ids}, iprz_conclusions="Szkolenie.")
    st.clock.set(date(2026, 6, 10))
    svc.acknowledge(cid, EMP)
    st.refresh_rules()
    st.cid = cid
    return st


def amend(body):
    return client.put("/api/ustawienia/reguly", headers=ADMIN, json={"podstawa_zmiany": "nowelizacja, Dz. U. 2026 poz. 9", **body})


def test_old_cycle_keeps_the_old_version_new_one_follows_the_new(st):
    svc = st.evaluations
    assert svc.objection_deadline(st.cid) == date(2026, 6, 17)  # 7 days
    r = amend({"wartosci": {"sprzeciw_dni_od_zapoznania": 14}})
    assert r.status_code == 200, r.text
    assert svc.rules.objection_days == 14  # in force today
    assert svc.objection_deadline(st.cid) == date(2026, 6, 17)  # the running evaluation: still 7 days
    ev = client.get(f"/api/evaluations/{st.cid}", headers=ADMIN).json()
    assert ev["czesc_ii"]["termin_sprzeciwu"] == "2026-06-17"
    nxt = svc.cycles.find_open_for(EMP)  # started at the acknowledgement, criteria set after the amendment
    svc.set_criteria(nxt.id, BOSS, [])
    assert svc.cycles.get(nxt.id).rules_version == 1 and svc.rules_for(svc.cycles.get(nxt.id)).objection_days == 14


def test_a_future_version_does_not_work_before_its_date(st):
    svc = st.evaluations
    r = amend({"wartosci": {"wyznaczenie_kryteriow_dni_od_poprzedniej_oceny_lub_zatrudnienia": 45},
               "obowiazuje_od": "2026-07-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["aktualna_wersja"] == 0 and body["wersje"][0]["przyszla"] is True
    assert svc.rules.criteria_days == 30
    svc.cycles.delete(svc.cycles.find_open_for(EMP).id)
    assert svc.start_cycle(EMP, start_date=date(2026, 6, 10)).criteria_deadline == date(2026, 7, 10)  # 30 days
    client.post("/api/demo/clock", json={"ustaw_date": "2026-07-01"})
    assert svc.rules.criteria_days == 45
    svc.cycles.delete(svc.cycles.find_open_for(EMP).id)
    assert svc.start_cycle(EMP, start_date=date(2026, 7, 1)).criteria_deadline == date(2026, 8, 17)  # 15.08 Sat -> Mon
    assert svc.objection_deadline(st.cid) == date(2026, 6, 17)


@pytest.mark.parametrize("body, message", [
    ({"wartosci": {"sprzeciw_dni_od_zapoznania": 0}}, "poza zakresem"),
    ({"wartosci": {"nieznany": 3}}, "Nieznany parametr"),
    ({"wartosci": {"sprzeciw_dni_od_zapoznania": 10}, "obowiazuje_od": "2026-06-01"}, "nie działa wstecz"),
    ({"kryteria": {"komunikacja": {"dostepne": False}}}, "obowiązkowe w arkuszu"),
    ({"kryteria": {"nieznane": {"nazwa": "X"}}}, "Nieznane kryterium"),
    ({"kryteria": {"negocjowanie": {"nazwa": " "}}}, "nie może być pusta"),
    ({"kryteria": {"negocjowanie": {"wskazniki": []}}}, "niepusta lista"),
])
def test_wrong_configuration_is_rejected(st, body, message):
    r = amend(body)
    assert r.status_code == 422 and message in r.text
    assert st.rule_versions.versions == []


def test_only_the_administrator(st):
    r = client.put("/api/ustawienia/reguly", headers={"X-User-Id": BOSS},
                   json={"wartosci": {"sprzeciw_dni_od_zapoznania": 10}, "podstawa_zmiany": "nowelizacja"})
    assert r.status_code == 403
    assert client.delete("/api/ustawienia/reguly", headers={"X-User-Id": BOSS}).status_code == 403


def test_criteria_edits_are_part_of_a_version(st):
    svc = st.evaluations
    r = amend({"kryteria": {"negocjowanie": {"dostepne": False},
                            "kreatywnosc": {"nazwa": "Kreatywność i innowacyjność", "wskazniki": ["Proponuje zmiany."]}}})
    assert r.status_code == 200
    crit = {c["id"]: c for c in r.json()["kryteria"]}
    assert crit["negocjowanie"]["dostepne"] is False and crit["kreatywnosc"]["nazwa"] == "Kreatywność i innowacyjność"
    diff = r.json()["wersje"][0]["zmiany_kryteriow"]
    assert {(d["kryterium"], d["pole"]) for d in diff} == {("negocjowanie", "dostepne"), ("kreatywnosc", "nazwa"),
                                                          ("kreatywnosc", "wskazniki")}
    nxt = svc.cycles.find_open_for(EMP).id
    with pytest.raises(ValidationError, match="nie jest dostępne"):
        svc.set_criteria(nxt, BOSS, ["negocjowanie"])
    svc.set_criteria(nxt, BOSS, ["kreatywnosc"])
    assert svc.rules_for(svc.cycles.get(nxt)).criterion_name("kreatywnosc") == "Kreatywność i innowacyjność"
    assert svc.rules_for(svc.cycles.get(st.cid)).criterion_name("kreatywnosc") == "Kreatywność"  # old version


def test_versions_list_diff_and_restart(st):
    amend({"wartosci": {"sprzeciw_dni_od_zapoznania": 14}})
    r = client.delete("/api/ustawienia/reguly", headers=ADMIN).json()
    assert [v["id"] for v in r["wersje"]] == [2, 1, 0] and r["wersje"][0]["aktualna"]
    assert r["wersje"][1]["zmiany"][0]["stara"] == 7 and r["wersje"][1]["zmiany"][0]["nowa"] == 14
    assert r["wersje"][0]["zmiany"][0]["nowa"] == 7
    assert r["wersje"][2]["oceny"] >= 1  # the evaluations computed by the published regulation
    state_mod.save_state()
    state_mod._state = None
    again = get_state()
    assert [v.id for v in again.rule_versions.versions] == [1, 2] and again.evaluations.rules.objection_days == 7
    assert again.evaluations.objection_deadline(st.cid) == date(2026, 6, 17)
