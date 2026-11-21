"""Access policy (app/domain/access.py), office settings, and a deputy acting on the evaluator's behalf."""
from datetime import date

import pytest

from app.application.use_cases import EvaluationService
from app.domain.access import AccessPolicy, VisibilityScope
from app.domain.errors import NotAuthorized, ValidationError
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from app.infrastructure.settings import OfficeSettings, load_office_settings

# dyrektor -> naczelnik_a -> anna, bartek;  dyrektor -> naczelnik_b -> celina
TREE = {"dyrektor": None, "naczelnik_a": "dyrektor", "naczelnik_b": "dyrektor",
        "anna": "naczelnik_a", "bartek": "naczelnik_a", "celina": "naczelnik_b"}


def policy(scope=VisibilityScope.SUBTREE, deputies=None):
    return AccessPolicy(TREE, scope, deputies or {}, admins=frozenset({"kadry"}))


def test_subtree_by_default_direct_when_the_office_says_so():
    assert policy().visible_employees("dyrektor") == {"naczelnik_a", "naczelnik_b", "anna", "bartek", "celina"}
    assert policy(VisibilityScope.DIRECT).visible_employees("dyrektor") == {"naczelnik_a", "naczelnik_b"}
    assert policy().can_read("dyrektor", "anna", "naczelnik_a")
    assert not policy(VisibilityScope.DIRECT).can_read("dyrektor", "anna", "naczelnik_a")


def test_managers_above_read_but_only_the_direct_evaluator_writes():
    p = policy()
    assert p.can_act_as_evaluator("naczelnik_a", "anna", "naczelnik_a")
    assert not p.can_act_as_evaluator("dyrektor", "anna", "naczelnik_a")  # art. 81 ust. 1: direct superior
    assert not p.can_see_working_material("dyrektor", "anna", "naczelnik_a")  # reads the sheet, not the notes


def test_a_manager_being_evaluated_sees_only_their_own_evaluation_not_the_working_notes():
    p = policy()
    assert p.can_read("naczelnik_a", "naczelnik_a", "dyrektor")  # own evaluation
    assert not p.can_see_working_material("naczelnik_a", "naczelnik_a", "dyrektor")  # boss's notes about them
    assert not p.can_act_as_evaluator("naczelnik_a", "naczelnik_a", "dyrektor")
    assert not p.can_read("naczelnik_a", "naczelnik_b", "dyrektor")  # a peer's evaluation
    assert not p.can_read("naczelnik_a", "celina", "naczelnik_b")  # someone else's team


def test_deputy_stands_in_for_the_evaluator():
    p = policy(deputies={"naczelnik_a": frozenset({"naczelnik_b"})})
    assert p.can_act_as_evaluator("naczelnik_b", "anna", "naczelnik_a")
    assert p.can_see_working_material("naczelnik_b", "anna", "naczelnik_a")
    assert {"anna", "bartek", "celina"} <= p.visible_employees("naczelnik_b")


def test_deputy_never_evaluates_themselves():
    p = policy(deputies={"naczelnik_a": frozenset({"anna"})})  # anna stands in for her own boss
    assert p.can_act_as_evaluator("anna", "bartek", "naczelnik_a")
    assert not p.can_act_as_evaluator("anna", "anna", "naczelnik_a")
    assert not p.can_see_working_material("anna", "anna", "naczelnik_a")


def test_hr_reads_everything_and_unknown_people_nothing():
    assert policy().visible_employees("kadry") == set(TREE)
    assert not policy().can_read("obcy", "anna", "naczelnik_a")


def test_a_cycle_in_the_data_does_not_loop():
    p = AccessPolicy({"a": "b", "b": "a"})
    assert p.subtree("a") == {"b"}


# ---------------------------------------------------------------- office settings

def test_office_settings_file_defaults_to_subtree():
    assert load_office_settings().visibility_scope is VisibilityScope.SUBTREE


def test_office_settings_reject_unknown_scope():
    assert OfficeSettings.from_dict({"zakres_widocznosci": "BEZPOSREDNI"}).visibility_scope is VisibilityScope.DIRECT
    with pytest.raises(ValidationError, match="zakres_widocznosci"):
        OfficeSettings.from_dict({"zakres_widocznosci": "WSZYSCY"})


# ---------------------------------------------------------------- deputy in the use cases

EMP, BOSS, DEPUTY = "grzegorz.wzor", "henryk.pryncypal", "celina.przykladowa"


def _service(deputies):
    return EvaluationService(kprm_rulebook(), InMemoryCycleRepository(), KprmEmployeeDirectory(),
                             FixedClock(date(2026, 6, 15)), deputies=deputies)


def test_deputy_runs_the_evaluation_and_the_cycle_records_who_acted():
    svc = _service(lambda evaluator, day: {DEPUTY} if evaluator == BOSS else set())
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, DEPUTY, [])
    svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, DEPUTY)
    ids = svc.cycles.get(c.id).criteria_ids(svc.rules)
    svc.submit_evaluation(c.id, DEPUTY, scores={i: 5 for i in ids}, iprz_conclusions="Szkolenie z komunikacji.")
    done = svc.cycles.get(c.id)
    assert done.drawn_up_by == DEPUTY and done.evaluator_id == BOSS
    assert [(who, step) for _, who, step in done.deputy_actions] == [
        (DEPUTY, "set_criteria"), (DEPUTY, "record_review_meeting"), (DEPUTY, "submit_evaluation")]


def test_without_an_active_deputy_only_the_evaluator_acts():
    svc = _service(lambda evaluator, day: set())
    c = svc.start_cycle(EMP)
    with pytest.raises(NotAuthorized):
        svc.set_criteria(c.id, DEPUTY, [])


def test_deputy_cannot_act_on_their_own_evaluation():
    svc = _service(lambda evaluator, day: {EMP})  # the evaluated person is (wrongly) the boss's deputy
    c = svc.start_cycle(EMP)
    with pytest.raises(NotAuthorized):
        svc.set_criteria(c.id, EMP, [])
