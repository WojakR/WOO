"""Deadlines wired into the evaluation cycle: re-evaluation after a negative evaluation (art. 81 ust. 9),
objection (art. 83 ust. 1), change of position (art. 81 ust. 6, § 9 of the regulation)."""
from datetime import date

import pytest

from app.application.use_cases import EvaluationService
from app.domain.calendar import WorkingCalendar
from app.domain.cycle import Status
from app.domain.deadlines import Absence, position_change
from app.domain.errors import InvalidTransition, ValidationError
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository

R = kprm_rulebook()
CAL = WorkingCalendar()
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
ADDITIONAL = ["orientacja_na_klienta", "kreatywnosc"]


@pytest.fixture
def clock():
    return FixedClock(date(2026, 6, 15))


@pytest.fixture
def svc(clock):
    return EvaluationService(R, InMemoryCycleRepository(), KprmEmployeeDirectory(), clock)


def _negative_evaluation_acknowledged(svc, clock, ack_day: date):
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, BOSS)
    ids = svc.cycles.get(c.id).criteria_ids(R)
    svc.submit_evaluation(c.id, BOSS, scores=dict(zip(ids, [3, 3, 5, 5, 3, 3, 5])),
                          justification="Liczne błędy w przekładach.", iprz_conclusions="Szkolenie z redakcji.")
    clock.set(ack_day)
    return svc.acknowledge(c.id, EMP)


# ---------------------------------------------------------------- re-evaluation after a negative evaluation

def test_cycle_after_negative_is_due_six_months_after_acknowledgement_not_24(svc):
    c = svc.start_cycle(EMP, start_date=date(2026, 6, 15), after_negative=True)
    assert svc.evaluation_deadline(c.id) == date(2026, 12, 16)  # day after 15.12.2026 (art. 81 ust. 9)


def test_absence_does_not_extend_re_evaluation(svc):
    c = svc.start_cycle(EMP, start_date=date(2026, 6, 15), after_negative=True)
    svc.register_absence(c.id, Absence(date(2026, 7, 1), date(2026, 8, 31), "L4"))
    assert svc.evaluation_deadline(c.id) == date(2026, 12, 16)  # art. 81 ust. 7 covers only the 24 months


def test_negative_acknowledged_tells_when_re_evaluation_is_due(svc, clock):
    c = _negative_evaluation_acknowledged(svc, clock, date(2026, 6, 22))
    assert c.next_evaluation_due(R) == date(2026, 12, 23)


# ---------------------------------------------------------------- objection

def test_objection_deadline_after_acknowledgement(svc, clock):
    c = _negative_evaluation_acknowledged(svc, clock, date(2026, 6, 22))  # Monday
    assert svc.objection_deadline(c.id) == date(2026, 6, 29)


def test_no_objection_deadline_before_acknowledgement(svc):
    c = svc.start_cycle(EMP)
    assert svc.objection_deadline(c.id) is None


def test_reminders_after_acknowledgement(svc, clock):
    c = _negative_evaluation_acknowledged(svc, clock, date(2026, 6, 22))
    objection = [r for r in svc.reminders() if r.kind == "objection"]
    assert [(r.recipient_id, r.due, r.days_left) for r in objection] == [(EMP, date(2026, 6, 29), 7)]
    clock.set(date(2026, 6, 30))  # objection window over
    assert not [r for r in svc.reminders() if r.kind == "objection"]
    clock.set(date(2026, 12, 1))  # re-evaluation within 30 days -> evaluator is reminded
    [r] = [r for r in svc.reminders() if r.kind == "reevaluation"]
    assert (r.recipient_id, r.due) == (BOSS, date(2026, 12, 23)) and "ponownej ocenie" in r.message


# ---------------------------------------------------------------- change of position (§ 9, art. 81 ust. 6)

@pytest.mark.parametrize("change, kind, earliest, deadline", [
    (date(2024, 10, 1), "NOWE_KRYTERIA", None, date(2024, 10, 31)),          # within 6 months: criteria in 30 days
    (date(2024, 12, 12), "NOWE_KRYTERIA", None, date(2025, 1, 13)),          # exactly 6 months is not "more than";
                                                                             # 11.01.2025 is a Saturday -> Monday
    (date(2024, 12, 13), "OCENA", date(2024, 12, 6), date(2025, 1, 13)),     # more than 6 months: evaluate
                                                                             # 7 days before .. 30 days after
                                                                             # (12.01.2025 Sunday -> Monday)
])
def test_position_change_rule(change, kind, earliest, deadline):
    out = position_change(change, date(2024, 6, 12), R, CAL)
    assert (out.kind, out.earliest, out.deadline) == (kind, earliest, deadline)


def test_position_change_before_reference_rejected():
    with pytest.raises(ValidationError):
        position_change(date(2024, 1, 1), date(2024, 6, 12), R, CAL)


def test_position_change_within_six_months_restarts_criteria(svc, clock):
    c = svc.start_cycle(EMP, start_date=date(2026, 3, 1))  # previous evaluation 1.03.2026
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    svc.confirm_criteria(c.id, EMP)
    deadline_before = svc.evaluation_deadline(c.id)
    out = svc.register_position_change(c.id, date(2026, 6, 15))
    c = svc.cycles.get(c.id)
    assert out.kind == "NOWE_KRYTERIA" and c.status is Status.CYCLE_STARTED
    assert c.criteria_deadline == date(2026, 7, 15) and c.criteria_confirmed_on is None
    assert svc.evaluation_deadline(c.id) == deadline_before  # § 9 ust. 1: deadline unchanged
    svc.set_criteria(c.id, BOSS, ["negocjowanie"])  # criteria can be set again
    svc.confirm_criteria(c.id, EMP)


def test_position_change_after_six_months_requires_evaluation_in_window(svc, clock):
    c = svc.start_cycle(EMP, start_date=date(2025, 6, 2))
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    out = svc.register_position_change(c.id, date(2026, 6, 15))
    assert out.kind == "OCENA" and out.earliest == date(2026, 6, 8)
    assert svc.evaluation_deadline(c.id) == out.deadline == date(2026, 7, 15)


def test_position_change_after_evaluation_rejected(svc, clock):
    c = _negative_evaluation_acknowledged(svc, clock, date(2026, 6, 22))
    with pytest.raises(InvalidTransition):
        svc.register_position_change(c.id, date(2026, 7, 1))
