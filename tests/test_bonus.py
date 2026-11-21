"""T12: two consecutive evaluations on one of the two top levels since the last grade -> the next grade
(art. 89 ust. 2 – with it the higher allowance); a different evaluation in between breaks it; employees excluded."""
from datetime import date

from fastapi.testclient import TestClient

from app.domain.consequences import FinishedEvaluation, mandatory_grade
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend.main import app
from conseq_helpers import HR, finish, state

client = TestClient(app)
R = kprm_rulebook()
TOP = lambda d, lvl="powyżej oczekiwań": FinishedEvaluation(d, "pozytywna", lvl, acknowledged=d, evaluation_id="1")  # noqa: E731


def tasks():
    return [t for t in client.get("/api/kadry/zadania", headers={"X-User-Id": HR}).json()
            if t["rodzaj"] == "STOPIEN_OBLIGATORYJNY"]


def test_rule_levels_and_counting_from_the_last_grade():
    two = [TOP(date(2024, 1, 10)), TOP(date(2026, 1, 10), "znacznie powyżej oczekiwań")]
    sig = mandatory_grade(two, True, 3, None, R)
    assert sig and sig.due == date(2026, 2, 9) and "art. 89 ust. 2" in sig.basis  # 30 days from acknowledgement
    assert mandatory_grade(two, True, 3, date(2025, 1, 1), R) is None  # only one since the last grade
    assert mandatory_grade(two, True, 9, None, R) is None  # the highest grade already
    assert mandatory_grade(two, False, None, None, R) is None  # not a civil servant
    mid = [two[0], FinishedEvaluation(date(2025, 1, 1), "pozytywna", "na poziomie oczekiwań"), two[1]]
    assert mandatory_grade(mid, True, 3, None, R) is None


def test_after_two_top_evaluations_hr_gets_the_task():
    st = state(previous=("pozytywna", "znacznie powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 7)
    [task] = tasks()
    assert task["termin"] and "kolejny stopień" in task["tresc"]


def test_another_evaluation_in_between_breaks_it():
    st = state(previous=("pozytywna", "powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 5)  # na poziomie oczekiwań
    finish(st, 7)
    assert tasks() == []


def test_not_for_civil_service_employees():
    st = state(civil_servant=False, grade=None, previous=("pozytywna", "powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 9)
    assert tasks() == []
