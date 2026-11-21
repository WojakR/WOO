"""T9: change of the evaluator – < 6 months no early evaluation, ≥ 6 months with one -> new cycle, without one the
new evaluator continues on the old criteria, the predecessor loses write access, notes are not passed on."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.evaluator_change import check_evaluator_change
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend.main import app

client = TestClient(app)
EMP, OLD, NEW, HR = "grzegorz.wzor", "henryk.pryncypal", "bartlomiej.przelozony", "kadry"


def as_(who):
    return {"X-User-Id": who}


@pytest.fixture
def st():
    """Grzegorz: previous evaluation 12.06.2024, criteria set and confirmed with Henryk."""
    st = reset_state(today=date(2026, 3, 2), ai_mode="off")
    svc = st.evaluations
    st.cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(st.cid, OLD, ["kreatywnosc"])
    svc.confirm_criteria(st.cid, EMP)
    return st


def change(st, on, early=False, who=HR):
    return client.post(f"/api/employees/{st.employee_number(EMP)}/evaluator-change", headers=as_(who),
                       json={"nowy_oceniajacy_id": st.employee_number(NEW), "data_zmiany": on,
                             "ocena_przed_zmiana": early})


def test_rule_under_six_months_no_early_evaluation():
    rules = kprm_rulebook()
    chk = check_evaluator_change(date(2026, 1, 10), date(2026, 1, 10), date(2026, 7, 10), rules)
    assert not chk.may_evaluate_early and chk.possible_from == date(2026, 7, 11)
    assert check_evaluator_change(date(2026, 1, 10), date(2026, 1, 10), date(2026, 7, 11), rules).may_evaluate_early
    assert chk.days_under_leaving == 181


def test_check_endpoint(st):
    r = client.get(f"/api/employees/{st.employee_number(EMP)}/evaluator-change", headers=as_(OLD),
                   params={"data_zmiany": "2026-03-02"})
    assert r.status_code == 200 and r.json()["mozliwa_wczesniejsza_ocena"] and "art. 81 ust. 8 pkt 1" in r.json()["wyjasnienie"]
    assert client.get(f"/api/employees/{st.employee_number(EMP)}/evaluator-change", headers=as_(EMP),
                      params={"data_zmiany": "2026-03-02"}).status_code == 403


def test_without_early_evaluation_the_new_evaluator_continues(st):
    deadline = st.evaluations.evaluation_deadline(st.cid)
    note = client.post(f"/api/evaluations/{st.cid}/notes", headers=as_(OLD),
                       json={"data": "2026-02-10", "tresc": "Notatka poprzednika."}).json()
    r = change(st, "2026-03-02")
    out = r.json()
    assert r.status_code == 201 and out["wariant"] == "PRZEJECIE" and out["notatki_wstrzymane"] == 1
    c = st.evaluations.cycles.get(st.cid)
    assert c.evaluator_id == NEW and c.additional_criteria == ["kreatywnosc"]  # § 9 ust. 3: same criteria
    assert st.evaluations.evaluation_deadline(st.cid) == deadline  # … and the same deadline
    assert st.directory.get(EMP).evaluator_id == NEW
    # the predecessor lost write access; the new one can act
    assert client.post(f"/api/evaluations/{st.cid}/notes", headers=as_(OLD),
                       json={"data": "2026-03-02", "tresc": "x"}).status_code == 403
    assert client.post(f"/api/evaluations/{st.cid}/notes", headers=as_(NEW),
                       json={"data": "2026-03-02", "tresc": "Pierwsza obserwacja."}).status_code == 201
    # the predecessor's note is not passed on automatically
    seen = [n["tresc"] for n in client.get(f"/api/evaluations/{st.cid}/notes", headers=as_(NEW)).json()]
    assert "Notatka poprzednika." not in seen
    mine = client.get("/api/me/notatki-poprzednie", headers=as_(OLD)).json()
    assert [n["id"] for n in mine] == [note["id"]]
    assert client.post(f"/api/notes/{note['id']}/przekaz", headers=as_(NEW)).status_code == 403
    assert client.post(f"/api/notes/{note['id']}/przekaz", headers=as_(OLD)).status_code == 200
    seen = [n["tresc"] for n in client.get(f"/api/evaluations/{st.cid}/notes", headers=as_(NEW)).json()]
    assert "Notatka poprzednika." in seen


def test_with_early_evaluation_a_new_cycle_with_the_new_evaluator(st):
    svc = st.evaluations
    svc.record_review_meeting(st.cid, OLD)
    ids = svc.cycles.get(st.cid).criteria_ids(svc.rules)
    svc.submit_evaluation(st.cid, OLD, scores={i: 7 for i in ids}, justification="", iprz_conclusions="Szkolenie.")
    svc.acknowledge(st.cid, EMP)
    nxt = svc.cycles.find_open_for(EMP)
    assert nxt.evaluator_id == OLD  # started at acknowledgement, before the change
    out = change(st, "2026-03-02", early=True).json()
    assert out["wariant"] == "NOWY_CYKL" and out["evaluation_id"] == int(nxt.id)
    nxt = svc.cycles.get(nxt.id)
    assert nxt.evaluator_id == NEW and nxt.status.name == "CYCLE_STARTED"  # new criteria by the new evaluator
    assert nxt.start_date == date(2026, 3, 2)  # next evaluation 24 months from the one drawn up now
    assert svc.cycles.get(st.cid).evaluator_id == OLD  # the evaluation drawn up stays the predecessor's


def test_early_evaluation_claimed_but_not_drawn_up_is_refused(st):
    r = change(st, "2026-03-02", early=True)
    assert r.status_code == 409 and "nie sporządził oceny" in r.json()["komunikat"]


def test_under_six_months_early_evaluation_is_refused(st):
    st.clock.set(date(2026, 3, 2))
    svc = st.evaluations
    svc.cycles.delete(st.cid)
    c = svc.start_cycle(EMP, start_date=date(2026, 1, 10))
    svc.set_criteria(c.id, OLD, [])
    r = change(st, "2026-03-02", early=True)
    assert r.status_code == 422 and "nie minęło więcej niż 6" in r.json()["walidacje"][0]["komunikat"]


def test_planned_change_reminds_the_leaving_evaluator_and_is_applied_later(st):
    r = change(st, "2026-04-01")
    assert r.json()["status"] == "PLANOWANA" and st.evaluations.cycles.get(st.cid).evaluator_id == OLD
    notes = client.get("/api/notifications", headers=as_(OLD)).json()
    assert any(n["typ"] == "ZMIANA_OCENIAJACEGO" and "Możesz sporządzić ocenę" in n["tresc"] for n in notes)
    rid = r.json()["id"]
    assert client.post(f"/api/evaluator-changes/{rid}/apply", headers=as_(HR)).status_code == 409  # too early
    st.clock.set(date(2026, 4, 1))
    done = client.post(f"/api/evaluator-changes/{rid}/apply", headers=as_(HR)).json()
    assert done["status"] == "WYKONANA" and st.evaluations.cycles.get(st.cid).evaluator_id == NEW


def test_only_hr_changes_the_evaluator(st):
    assert change(st, "2026-03-02", who=OLD).status_code == 403
