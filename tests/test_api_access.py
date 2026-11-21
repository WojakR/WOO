"""Visibility through the API: the supervisor tree, the office setting, deputies – and the traps."""
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.domain.access import VisibilityScope
from app.infrastructure.settings import OfficeSettings
from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS, TOP = "grzegorz.wzor", "henryk.pryncypal", "bartlomiej.przelozony"
PEER_BOSS = "romuald.gut"  # evaluates janina.nowak – another branch of the tree
OUTSIDER = "celina.przykladowa"


def as_(who):
    return {"X-User-Id": who}


@pytest.fixture
def st():
    """Two-level tree: Bartłomiej -> Henryk -> Grzegorz (the demo data is one level deep)."""
    st = reset_state(today=date(2026, 6, 15), ai_mode="off")
    henryk = st.directory.get(BOSS)
    st.directory._by_id[BOSS] = replace(henryk, evaluator_id=TOP)
    st.evaluations.start_cycle(BOSS)  # Henryk is now evaluated by Bartłomiej
    return st


def eid(st, employee=EMP) -> int:
    return int(st.evaluations.cycles.find_open_for(employee).id)


# ---------------------------------------------------------------- the manager above reads, does not write

def test_manager_above_reads_the_evaluation_in_their_subtree_without_actions(st):
    r = client.get(f"/api/evaluations/{eid(st)}", headers=as_(TOP))
    assert r.status_code == 200
    assert r.json()["dozwolone_akcje"] == [] and r.json()["edytowalne_pola"] == []
    own = client.get(f"/api/evaluations/{eid(st)}", headers=as_(BOSS)).json()
    assert own["dozwolone_akcje"]  # the direct evaluator has steps to take


def test_manager_above_does_not_get_the_evaluators_working_material(st):
    e = eid(st)
    assert client.get(f"/api/evaluations/{e}/notes", headers=as_(TOP)).status_code == 403
    assert client.post(f"/api/evaluations/{e}/notes", json={"data": "2026-06-10", "tresc": "x"},
                       headers=as_(TOP)).status_code == 403
    assert client.post(f"/api/evaluations/{e}/ai/conversation-prep", headers=as_(TOP)).status_code == 403
    assert client.get(f"/api/evaluations/{e}/evidence", headers=as_(TOP)).status_code == 403


def test_dashboard_shows_the_subtree(st):
    items = client.get("/api/dashboard", headers=as_(TOP)).json()["pozycje"]
    names = {(i["oceniany"]["imie"], i["oceniany"]["nazwisko"]) for i in items}
    assert ("Grzegorz", "Wzór") in names and ("Henryk", "Pryncypał") in names


def test_office_setting_direct_reports_only(st):
    st.settings = OfficeSettings(VisibilityScope.DIRECT)
    assert client.get(f"/api/evaluations/{eid(st)}", headers=as_(TOP)).status_code == 403
    items = client.get("/api/dashboard", headers=as_(TOP)).json()["pozycje"]
    assert {i["oceniany"]["imie"] for i in items} == {"Henryk", "Adam"}  # his direct reports only, no Grzegorz


# ---------------------------------------------------------------- traps

def test_a_manager_never_sees_their_own_bosss_notes(st):
    henryk_eval = eid(st, BOSS)
    client.post(f"/api/evaluations/{henryk_eval}/notes", headers=as_(TOP),
                json={"data": "2026-06-10", "tresc": "Robocza notatka dyrektora o Henryku."})
    assert client.get(f"/api/evaluations/{henryk_eval}/notes", headers=as_(BOSS)).json() == []
    assert client.post(f"/api/evaluations/{henryk_eval}/ai/conversation-prep", headers=as_(BOSS)).status_code == 403
    assert client.get(f"/api/evaluations/{henryk_eval}", headers=as_(BOSS)).status_code == 200  # own sheet: yes


def test_a_manager_does_not_see_another_branch(st):
    other = eid(st, "janina.nowak")  # evaluated by Romuald Gut
    assert client.get(f"/api/evaluations/{other}", headers=as_(BOSS)).status_code == 403
    assert client.get(f"/api/evaluations/{eid(st)}", headers=as_(PEER_BOSS)).status_code == 403


# ---------------------------------------------------------------- deputies

def _deputy(st, evaluator, deputy, od="2026-06-01", do="2026-06-30", who="kadry"):
    return client.post("/api/zastepstwa", headers=as_(who), json={
        "oceniajacy_id": st.employee_number(evaluator), "zastepca_id": st.employee_number(deputy), "od": od, "do": do})


def test_deputy_writes_notes_and_runs_steps_while_active(st):
    assert client.post(f"/api/evaluations/{eid(st)}/notes", json={"data": "2026-06-10", "tresc": "x"},
                       headers=as_(OUTSIDER)).status_code == 403
    r = _deputy(st, BOSS, OUTSIDER)
    assert r.status_code == 201 and r.json()["aktywne"] is True
    note = client.post(f"/api/evaluations/{eid(st)}/notes", headers=as_(OUTSIDER),
                       json={"data": "2026-06-10", "tresc": "Notatka zastępcy."})
    assert note.status_code == 201 and note.json()["autor"]["imie"] == "Celina"
    sheet = client.get(f"/api/evaluations/{eid(st)}", headers=as_(OUTSIDER)).json()
    assert sheet["dozwolone_akcje"]  # may take the evaluator's steps
    client.delete(f"/api/zastepstwa/{r.json()['id']}", headers=as_("kadry"))
    assert client.get(f"/api/evaluations/{eid(st)}/notes", headers=as_(OUTSIDER)).status_code == 403


def test_sheet_tells_the_ui_who_acts_as_evaluator(st):
    e = eid(st)
    flag = lambda who: client.get(f"/api/evaluations/{e}", headers=as_(who)).json()["jako_oceniajacy"]  # noqa: E731
    assert flag(BOSS) is True and flag(TOP) is False and flag(EMP) is False
    _deputy(st, BOSS, OUTSIDER)
    assert flag(OUTSIDER) is True  # the UI shows the deputy the evaluator's tools (notes, drafts, HR partner)


def test_expired_deputy_has_no_access(st):
    _deputy(st, BOSS, OUTSIDER, od="2026-05-01", do="2026-05-31")
    assert client.get(f"/api/evaluations/{eid(st)}", headers=as_(OUTSIDER)).status_code == 403


def test_deputy_cannot_act_on_their_own_evaluation(st):
    _deputy(st, BOSS, EMP)  # Grzegorz stands in for his own boss
    r = client.post(f"/api/evaluations/{eid(st)}/notes", json={"data": "2026-06-10", "tresc": "x"}, headers=as_(EMP))
    assert r.status_code == 403
    assert client.get(f"/api/evaluations/{eid(st)}", headers=as_(EMP)).json()["edytowalne_pola"] == []


def test_deputy_validation_and_who_may_assign(st):
    assert _deputy(st, EMP, OUTSIDER).status_code == 422  # Grzegorz evaluates nobody
    assert _deputy(st, BOSS, BOSS).status_code == 422
    assert _deputy(st, BOSS, OUTSIDER, od="2026-06-30", do="2026-06-01").status_code == 422
    assert _deputy(st, BOSS, OUTSIDER, who=EMP).status_code == 403
    assert _deputy(st, BOSS, OUTSIDER, who=BOSS).status_code == 201  # the evaluator assigns their own deputy
    assert [z["zastepca"]["imie"] for z in client.get("/api/zastepstwa", headers=as_(BOSS)).json()] == ["Celina"]
