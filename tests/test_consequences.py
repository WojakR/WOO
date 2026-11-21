"""T10: two consecutive negative evaluations – one: nothing, two: a signal, a positive in between: nothing;
civil servant (art. 71 ust. 1 pkt 1) vs. civil-service employee (information only)."""
from datetime import date

from fastapi.testclient import TestClient

from app.domain.consequences import FinishedEvaluation, two_negatives, warning_before_submit
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend.main import app
from conseq_helpers import BOSS, EMP, HR, finish, prepare_meeting, state

client = TestClient(app)
R = kprm_rulebook()
NEG = lambda d: FinishedEvaluation(d, "negatywna", "poniżej oczekiwań")  # noqa: E731
POS = lambda d: FinishedEvaluation(d, "pozytywna", "na poziomie oczekiwań")  # noqa: E731


def test_rule():
    assert two_negatives([NEG(date(2026, 1, 1))], True, R) is None
    sig = two_negatives([NEG(date(2026, 1, 1)), NEG(date(2026, 8, 1))], True, R)
    assert sig.kind == "DWIE_NEGATYWNE" and sig.basis == "art. 71 ust. 1 pkt 1 ustawy o służbie cywilnej"
    assert two_negatives([NEG(date(2025, 1, 1)), POS(date(2026, 1, 1)), NEG(date(2026, 8, 1))], True, R) is None
    info = two_negatives([NEG(date(2026, 1, 1)), NEG(date(2026, 8, 1))], False, R)
    assert info.basis is None and "art. 71" not in info.message
    assert warning_before_submit([NEG(date(2026, 1, 1))], True, True, R)
    assert warning_before_submit([POS(date(2026, 1, 1))], True, True, R) is None


def tasks():
    return client.get("/api/kadry/zadania", headers={"X-User-Id": HR}).json()


def test_one_negative_no_signal():
    st = state()
    finish(st, 5, low=1)
    assert tasks() == []


def test_two_negatives_warning_while_drawing_up_then_task_after_acknowledgement():
    st = state(civil_servant=True)
    finish(st, 5, low=1)
    cid = prepare_meeting(st)
    ev = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": BOSS}).json()
    ids = [k["criterion_kod"] for k in ev["kryteria"]]
    client.put(f"/api/evaluations/{cid}/scores", headers={"X-User-Id": BOSS},
               json={"punkty": {k: (1 if i == 0 else 5) for i, k in enumerate(ids)}})
    ev = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": BOSS}).json()
    client.patch(f"/api/evaluations/{cid}", headers={"X-User-Id": BOSS},
                 json={"updated_at": ev["updated_at"], "uzasadnienie": "Błędy.", "wnioski_iprz": "Szkolenie."})
    ev = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": BOSS}).json()
    [warn] = [w for w in ev["walidacje"] if w["kod"] == "KOLEJNA_NEGATYWNA"]
    assert warn["waga"] == "OSTRZEZENIE" and "art. 71 ust. 1 pkt 1" in warn["komunikat"]
    r = client.post(f"/api/evaluations/{cid}/actions/ZATWIERDZ_OCENE", headers={"X-User-Id": BOSS}, json={})
    assert r.status_code == 200  # a warning never blocks
    assert tasks() == []  # not before the employee acknowledged it
    client.post(f"/api/evaluations/{cid}/actions/POTWIERDZ_ZAPOZNANIE", headers={"X-User-Id": EMP}, json={})
    [task] = tasks()
    assert task["rodzaj"] == "DWIE_NEGATYWNE" and task["podstawa"].startswith("art. 71") and task["evaluation_id"] == int(cid)
    notes = client.get("/api/notifications", headers={"X-User-Id": HR}).json()
    assert any(n["typ"] == "SKUTEK_DWIE_NEGATYWNE" for n in notes)
    assert client.get("/api/kadry/zadania", headers={"X-User-Id": BOSS}).status_code == 403


def test_positive_in_between_breaks_the_series():
    st = state()
    finish(st, 5, low=1)
    finish(st, 5)
    finish(st, 5, low=1)
    assert tasks() == []


def test_employee_who_is_not_a_civil_servant_gets_information_without_the_article():
    st = state(civil_servant=False, grade=None)
    finish(st, 5, low=1)
    finish(st, 5, low=1)
    [task] = tasks()
    assert task["podstawa"] is None and "art. 71" not in task["tresc"]
