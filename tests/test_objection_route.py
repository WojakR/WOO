"""Office setting sprzeciw.tryb: objections go to the director general (art. 83 ust. 1, default) or to the
evaluator's supervisor (PRZELOZONY_PRZELOZONEGO); without one, the objection falls back to the ordinary route."""
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import restore, reset_state, snapshot
from app.domain.access import VisibilityScope
from app.domain.errors import ValidationError
from app.domain.objection import HeadMode, ObjectionPolicy, Route, objection_reviewer
from app.infrastructure.settings import OfficeSettings
from backend.main import app

client = TestClient(app)
SKIP = ObjectionPolicy(director_general="dg", route=Route.SKIP_LEVEL)


# ---------------------------------------------------------------- domain

def test_default_route_is_the_director_general():
    r = objection_reviewer(ObjectionPolicy(director_general="dg"), "emp", "boss", False, None, "grand")
    assert r.id == "dg" and "art. 83" in r.basis


def test_skip_level_goes_to_the_evaluators_supervisor():
    r = objection_reviewer(SKIP, "emp", "boss", False, None, "grand")
    assert r.id == "grand" and "przełożony oceniającego" in r.basis


def test_skip_level_without_a_supervisor_falls_back_to_the_director_general():
    r = objection_reviewer(SKIP, "emp", "boss", False, None, None)
    assert r.id == "dg" and r.basis.startswith("Oceniający nie ma przełożonego")


def test_skip_level_without_dg_falls_back_to_the_head_of_the_office():
    r = objection_reviewer(replace(SKIP, office_has_director_general=False), "emp", "boss", False, "head", None)
    assert r.id == "head" and "kierownik urzędu" in r.basis


def test_skip_level_never_lets_someone_decide_their_own_objection():
    assert objection_reviewer(SKIP, "emp", "boss", False, None, "emp").id == "dg"


def test_the_head_of_the_office_case_still_wins():
    p = replace(SKIP, when_office_head=HeadMode.RE_EXAMINATION)
    assert objection_reviewer(p, "emp", "boss", True, None, "grand").id == "boss"


def test_settings_parse_the_route_and_reject_unknown_values():
    assert OfficeSettings.from_dict({"sprzeciw": {"tryb": "PRZELOZONY_PRZELOZONEGO"}}).objection.route is Route.SKIP_LEVEL
    assert OfficeSettings.from_dict({}).objection.route is Route.DIRECTOR_GENERAL
    with pytest.raises(ValidationError):
        OfficeSettings.from_dict({"sprzeciw": {"tryb": "KTOKOLWIEK"}})


# ---------------------------------------------------------------- API

EMP, BOSS, GRAND = "tomasz.probny", "barbara.przelozona", "zofia.dyrektorska"


def _objection(st, emp, boss):
    svc = st.evaluations
    cid = svc.cycles.find_open_for(emp).id
    svc.set_criteria(cid, boss, [])
    svc.confirm_criteria(cid, emp)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, boss)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, boss, scores={i: (1 if i == ids[0] else 5) for i in ids},
                          justification="Uzasadnienie.", iprz_conclusions="Szkolenie.")
    st.clock.set(date(2026, 6, 10))
    svc.acknowledge(cid, emp)
    r = client.post(f"/api/evaluations/{cid}/actions/ZLOZ_SPRZECIW", headers={"X-User-Id": emp},
                    json={"komentarz": "Sprzeciw."})
    assert r.status_code == 200, r.text
    return cid


@pytest.fixture
def st():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    r = client.put("/api/ustawienia/urzad", headers={"X-User-Id": "kadry"},
                   json={"tryb_sprzeciwu": "PRZELOZONY_PRZELOZONEGO", "zakres_widocznosci": "BEZPOSREDNI"})
    assert r.status_code == 200 and r.json()["tryb_sprzeciwu"] == "PRZELOZONY_PRZELOZONEGO"
    assert st.settings.visibility_scope is VisibilityScope.DIRECT
    return st


def test_api_the_evaluators_supervisor_reads_and_decides_the_objection(st):
    cid = _objection(st, EMP, BOSS)
    ev = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": GRAND})
    assert ev.status_code == 200, ev.text  # readable although the scope is BEZPOSREDNI
    assert ev.json()["rozpatrujacy_sprzeciw"]["id"] == GRAND and "ROZPATRZ_SPRZECIW" in ev.json()["dozwolone_akcje"]
    assert client.post(f"/api/evaluations/{cid}/actions/ROZPATRZ_SPRZECIW", headers={"X-User-Id": "kadry"},
                       json={"uwzglednij": False, "komentarz": "Nie."}).status_code == 403
    r = client.post(f"/api/evaluations/{cid}/actions/ROZPATRZ_SPRZECIW", headers={"X-User-Id": GRAND},
                    json={"uwzglednij": False, "komentarz": "Ocena zasadna."})
    assert r.status_code == 200, r.text
    # once decided, the supervisor no longer reads it (scope BEZPOSREDNI)
    assert client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": GRAND}).status_code == 403


def test_api_an_evaluator_at_the_top_sends_the_objection_to_the_director_general(st):
    cid = _objection(st, "grzegorz.wzor", "henryk.pryncypal")  # henryk has no supervisor
    out = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": "kadry"}).json()["rozpatrujacy_sprzeciw"]
    assert out["id"] == "kadry" and out["podstawa"].startswith("Oceniający nie ma przełożonego")


def test_the_route_survives_a_restart(st):
    assert restore(snapshot(st), ai_mode="off").settings.objection.route is Route.SKIP_LEVEL
