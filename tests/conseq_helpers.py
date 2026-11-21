"""Shared helpers for the tests of consequences of consecutive evaluations (T10–T12)."""
from dataclasses import replace
from datetime import date, timedelta

from app.api.state import reset_state

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"


def state(civil_servant=True, grade=3, grade_since=None, previous=None):
    """Grzegorz with the given HR data; `previous` = (outcome, level, date) of the evaluation before the system."""
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    g = st.directory.get(EMP)
    prev = g.previous_evaluation
    if previous is not None:
        from app.domain.cycle import PreviousEvaluation

        prev = PreviousEvaluation(*previous)
    st.directory._by_id[EMP] = replace(g, civil_servant=civil_servant, grade=grade, grade_since=grade_since,
                                       previous_evaluation=prev)
    return st


def finish(st, score, acknowledge=True, low=None):
    """Draw up (and acknowledge) Grzegorz's open evaluation with every score = `score` (one = `low`)."""
    svc = st.evaluations
    c = svc.cycles.find_open_for(EMP)
    if c.status.name == "CYCLE_STARTED":
        svc.set_criteria(c.id, BOSS, [])
        svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, BOSS)
    ids = svc.cycles.get(c.id).criteria_ids(svc.rules)
    scores = {i: score for i in ids}
    if low is not None:
        scores[ids[0]] = low
    svc.submit_evaluation(c.id, BOSS, scores=scores, justification="Uzasadnienie oceny.", iprz_conclusions="Szkolenie.")
    if acknowledge:
        svc.acknowledge(c.id, EMP)
        st.clock.set(st.clock.today() + timedelta(days=200))
    return c.id


def prepare_meeting(st):
    """Grzegorz's open evaluation at the review meeting (scores still empty)."""
    svc = st.evaluations
    c = svc.cycles.find_open_for(EMP)
    if c.status.name == "CYCLE_STARTED":
        svc.set_criteria(c.id, BOSS, [])
        svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, BOSS)
    return c.id
