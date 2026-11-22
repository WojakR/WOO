"""After the employee acknowledges an evaluation, the next cycle and its deadline start on their own."""
from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application.use_cases import EvaluationService
from app.domain.calendar import WorkingCalendar, add_months
from app.domain.cycle import Status
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from backend.main import app

EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
CAL = WorkingCalendar()


def _finished(scores, rules=None, drawn_up=date(2026, 6, 10), acknowledged=date(2026, 6, 22)):
    clock = FixedClock(date(2024, 6, 12))
    svc = EvaluationService(rules or kprm_rulebook(), InMemoryCycleRepository(), KprmEmployeeDirectory(), clock)
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS, [])
    svc.confirm_criteria(c.id, EMP)
    clock.set(drawn_up)
    svc.record_review_meeting(c.id, BOSS)
    ids = svc.cycles.get(c.id).criteria_ids(svc.rules)
    svc.submit_evaluation(c.id, BOSS, scores=dict(zip(ids, scores)), justification="Uzasadnienie oceny negatywnej.",
                          iprz_conclusions="Szkolenie.")
    clock.set(acknowledged)
    done = svc.acknowledge(c.id, EMP)
    return svc, done, svc.cycles.find_open_for(EMP)


def test_after_a_positive_evaluation_the_next_24_months_start_from_drawing_it_up():
    svc, done, nxt = _finished([5, 5, 5, 5, 5])
    assert done.status is Status.ACKNOWLEDGED and nxt is not None and nxt.id != done.id
    assert nxt.status is Status.CYCLE_STARTED and nxt.start_date == date(2026, 6, 10) and not nxt.after_negative
    assert nxt.criteria_deadline == date(2026, 7, 10)  # § 7 pkt 1: 30 days from drawing up
    assert svc.evaluation_deadline(nxt.id) == CAL.next_working_day(add_months(date(2026, 6, 10), 24))
    assert nxt.previous_evaluation.outcome == "pozytywna" and nxt.previous_evaluation.acknowledged == date(2026, 6, 22)


def test_after_a_negative_evaluation_the_re_evaluation_runs_from_acknowledging_it():
    svc, _, nxt = _finished([3, 3, 3, 1, 3])
    assert nxt.after_negative and nxt.negative_acknowledged_on == date(2026, 6, 22)
    assert nxt.criteria_deadline == date(2026, 6, 17)  # § 7 pkt 2: 7 days from drawing up
    assert svc.evaluation_deadline(nxt.id) == date(2026, 12, 23)  # art. 81 ust. 9: day after 22.12.2026


def test_the_period_comes_from_the_rules_so_a_change_to_12_months_is_one_value():
    _, _, nxt = _finished([5, 5, 5, 5, 5], rules=replace(kprm_rulebook(), cycle_months=12))
    assert nxt.evaluation_deadline(replace(kprm_rulebook(), cycle_months=12), CAL) == date(2027, 6, 10)


def test_no_second_cycle_when_one_is_already_open():
    svc, done, nxt = _finished([5, 5, 5, 5, 5])
    assert svc.start_next_cycle(done) is None
    assert [c.id for c in svc.cycles.list_all() if c.status is not Status.ACKNOWLEDGED] == [nxt.id]


def test_through_the_api_the_next_cycle_appears_next_to_the_finished_one():
    st = reset_state(today=date(2026, 6, 15), ai_mode="off")
    client = TestClient(app)
    cid = st.evaluations.cycles.find_open_for(EMP).id
    st.evaluations.set_criteria(cid, BOSS, [])
    st.evaluations.confirm_criteria(cid, EMP)
    st.evaluations.record_review_meeting(cid, BOSS)
    ids = st.evaluations.cycles.get(cid).criteria_ids(st.evaluations.rules)
    st.evaluations.submit_evaluation(cid, BOSS, scores={i: 7 for i in ids}, iprz_conclusions="Mentoring.")
    r = client.post(f"/api/evaluations/{cid}/actions/POTWIERDZ_ZAPOZNANIE", headers={"X-User-Id": EMP})
    assert r.status_code == 200, r.text
    rows = [i for i in client.get("/api/dashboard", headers={"X-User-Id": BOSS}).json()["pozycje"]
            if i["oceniany"]["imie"] == "Grzegorz"]
    assert [(i["status"], i["wynik"]) for i in rows] == [("ZAKONCZONA", "POZYTYWNA"), ("KRYTERIA_DO_WYZNACZENIA", None)]
    # 24 months from drawing up (15.06.2026) = 15.06.2028, which is Corpus Christi -> next working day
    assert rows[1]["termin_oceny"] == "2028-06-16"


def test_a_second_negative_in_a_row_starts_the_ordinary_24_month_cycle():
    svc, _, nxt = _finished([3, 3, 3, 1, 3])
    assert nxt.after_negative
    clock = svc.clock
    svc.set_criteria(nxt.id, BOSS, [])
    svc.confirm_criteria(nxt.id, EMP)
    clock.set(date(2026, 12, 28))
    svc.record_review_meeting(nxt.id, BOSS)
    ids = svc.cycles.get(nxt.id).criteria_ids(svc.rules)
    svc.submit_evaluation(nxt.id, BOSS, scores=dict(zip(ids, [3, 3, 3, 1, 3])),
                          justification="Uzasadnienie oceny negatywnej.", iprz_conclusions="Szkolenie.")
    clock.set(date(2027, 1, 4))
    done = svc.acknowledge(nxt.id, EMP)
    third = svc.cycles.find_open_for(EMP)
    assert done.result.outcome.value == "negatywna" and third is not None
    assert not third.after_negative and third.start_date == date(2026, 12, 28)
    assert third.criteria_deadline == CAL.next_working_day(date(2027, 1, 27))  # 30 days, not 7
    assert svc.evaluation_deadline(third.id) == CAL.next_working_day(add_months(date(2026, 12, 28), 24))
