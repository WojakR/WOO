import ast
from datetime import date
from pathlib import Path

import pytest

from app.application.use_cases import EvaluationService
from app.domain.cycle import EDITABLE_IN, TRANSITIONS, Status
from app.domain.deadlines import Absence
from app.domain.errors import FieldLocked, InvalidTransition, NotAuthorized, NotFound, ValidationError
from app.domain.scoring import Outcome
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository

R = kprm_rulebook()
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
ADDITIONAL = ["kreatywnosc", "myslenie_analityczne"]


@pytest.fixture
def clock():
    return FixedClock(date(2026, 6, 15))


@pytest.fixture
def svc(clock):
    return EvaluationService(R, InMemoryCycleRepository(), KprmEmployeeDirectory(), clock)


def _scores(svc, cycle_id, values):
    ids = svc.cycles.get(cycle_id).criteria_ids(R)
    return dict(zip(ids, values, strict=True))


def test_statuses_match_kprm_data():
    assert {s.value for s in Status} <= set(R.statuses)
    assert set(TRANSITIONS) == {"set_criteria", "confirm_criteria", "record_review_meeting",
                                "submit_evaluation", "acknowledge", "file_objection", "decide_objection"}


def test_full_cycle_happy_path(svc, clock):
    c = svc.start_cycle(EMP)
    assert c.status is Status.CYCLE_STARTED
    assert c.sheet == "C" and c.evaluator_id == BOSS
    assert c.start_date == date(2024, 6, 12)  # previous evaluation from pracownicy.json
    assert c.criteria_deadline == date(2024, 7, 12)
    assert svc.evaluation_deadline(c.id) == date(2026, 6, 12)

    c = svc.set_criteria(c.id, BOSS, ADDITIONAL, goals=["Skrócić czas przekładów o 10%"])
    assert c.status is Status.CRITERIA_SET
    assert c.criteria_ids(R) == list(R.mandatory("C")) + ADDITIONAL

    c = svc.confirm_criteria(c.id, EMP)
    assert c.status is Status.CRITERIA_CONFIRMED

    clock.advance(days=1)
    c = svc.record_review_meeting(c.id, BOSS)
    assert c.status is Status.MEETING_HELD and c.meeting_date == date(2026, 6, 16)
    assert c.period_from == date(2026, 6, 15)  # criteria set date

    svc.edit(c.id, BOSS, scores=_scores(svc, c.id, [3, 3, 5, 5, 3, 3, 5]))  # draft during the meeting
    result = svc.submit_evaluation(
        c.id, BOSS, justification="Liczne błędy w przekładach.", iprz_conclusions="Szkolenie z redakcji tekstu."
    )
    assert result.outcome is Outcome.NEGATIVE and result.level == "poniżej oczekiwań"
    assert svc.cycles.get(c.id).status is Status.EVALUATION_DONE

    c = svc.acknowledge(c.id, EMP)
    assert c.status is Status.ACKNOWLEDGED
    assert [s for _, s in c.history] == [s for s in Status if s is not Status.OBJECTION]  # no objection here


def test_disallowed_transitions_rejected(svc):
    c = svc.start_cycle(EMP)
    with pytest.raises(InvalidTransition, match="ocena jest w statusie „cykl rozpoczęty”"):
        svc.submit_evaluation(c.id, BOSS, scores={}, iprz_conclusions="x")
    with pytest.raises(InvalidTransition):
        svc.confirm_criteria(c.id, EMP)  # nothing to confirm yet
    with pytest.raises(InvalidTransition):
        svc.acknowledge(c.id, EMP)
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    svc.confirm_criteria(c.id, EMP)
    with pytest.raises(InvalidTransition):
        svc.set_criteria(c.id, BOSS, ["negocjowanie"])  # criteria already confirmed
    assert svc.cycles.get(c.id).status is Status.CRITERIA_CONFIRMED


def test_locked_fields_cannot_be_edited(svc):
    c = svc.start_cycle(EMP)
    with pytest.raises(FieldLocked, match="oceny cząstkowe"):
        svc.edit(c.id, BOSS, scores={"rzetelnosc": 5})  # too early
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    svc.edit(c.id, BOSS, additional_criteria=["negocjowanie"])  # still open before confirmation
    svc.confirm_criteria(c.id, EMP)
    with pytest.raises(FieldLocked, match="kryteria dodatkowe"):
        svc.edit(c.id, BOSS, additional_criteria=["kreatywnosc"])
    with pytest.raises(FieldLocked):
        svc.edit(c.id, BOSS, deadline_override=date(2026, 12, 1))
    svc.record_review_meeting(c.id, BOSS)
    with pytest.raises(FieldLocked, match="data rozmowy"):
        svc.edit(c.id, BOSS, meeting_date=date(2026, 6, 1))
    svc.submit_evaluation(c.id, BOSS, _scores(svc, c.id, [5, 5, 5, 7, 7, 7]), iprz_conclusions="Kurs.")
    for f in EDITABLE_IN:
        with pytest.raises(FieldLocked):
            svc.edit(c.id, BOSS, **{f: None})


def test_only_the_right_person_may_act(svc):
    c = svc.start_cycle(EMP)
    with pytest.raises(NotAuthorized, match="oceniający"):
        svc.set_criteria(c.id, EMP, ADDITIONAL)
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    with pytest.raises(NotAuthorized, match="oceniany"):
        svc.confirm_criteria(c.id, BOSS)


def test_invalid_additional_criteria_rejected_and_state_unchanged(svc):
    c = svc.start_cycle(EMP)
    with pytest.raises(ValidationError) as e:
        svc.set_criteria(c.id, BOSS, ["kreatywnosc", "kreatywnosc", "rzetelnosc", "negocjowanie"])
    assert len(e.value.problems) == 3
    stored = svc.cycles.get(c.id)
    assert stored.status is Status.CYCLE_STARTED and stored.additional_criteria == []


def test_submission_blocked_without_justification_when_negative(svc):
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS)
    svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, BOSS)
    scores = _scores(svc, c.id, [9, 9, 9, 9, 1])
    with pytest.raises(ValidationError, match="uzasadnienie"):
        svc.submit_evaluation(c.id, BOSS, scores, iprz_conclusions="Kurs.")
    stored = svc.cycles.get(c.id)
    assert stored.status is Status.MEETING_HELD and stored.scores == {}  # failed submit changes nothing
    r = svc.submit_evaluation(c.id, BOSS, scores, justification="Rażące uchybienie.", iprz_conclusions="Kurs.")
    assert r.outcome is Outcome.NEGATIVE


def test_cannot_open_second_cycle_or_unknown_employee(svc):
    svc.start_cycle(EMP)
    with pytest.raises(InvalidTransition):
        svc.start_cycle(EMP)
    with pytest.raises(NotFound):
        svc.start_cycle("nikt")
    with pytest.raises(ValidationError):
        svc.start_cycle(BOSS)  # evaluator without own evaluator in sample data


def test_new_cycle_after_negative_has_7_day_criteria_deadline(svc):
    c = svc.start_cycle(EMP, start_date=date(2026, 6, 15), after_negative=True)
    assert c.criteria_deadline == date(2026, 6, 22)


def test_reminders_follow_the_cycle_and_absence_extends_deadline(svc, clock):
    c = svc.start_cycle(EMP, start_date=date(2026, 6, 1))  # clock: 15.06.2026
    [r] = svc.reminders()
    assert (r.kind, r.recipient_id, r.due, r.days_left) == ("criteria", BOSS, date(2026, 7, 1), 16)
    assert "wyznaczenie kryteriów" in r.message and "Grzegorz Wzór" in r.message

    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    [r] = svc.reminders()
    assert r.recipient_id == EMP and "potwierdzenie kryteriów" in r.message

    svc.confirm_criteria(c.id, EMP)
    assert svc.reminders() == []  # evaluation deadline 01.06.2028 is far away
    clock.set(date(2028, 5, 10))  # "przewiń czas"
    [r] = svc.reminders()
    assert (r.kind, r.due, r.days_left) == ("evaluation", date(2028, 6, 1), 22)

    # justified absence 05.10–06.11.2026 (33 days, continuous across the weekend) extends the deadline
    sick, leave = (Absence(date(2026, 10, 5), date(2026, 10, 16), "zwolnienie lekarskie"),
                   Absence(date(2026, 10, 19), date(2026, 11, 6), "urlop wypoczynkowy"))
    svc.register_absence(c.id, sick)
    assert svc.register_absence(c.id, leave) == date(2028, 7, 4)
    assert svc.reminders() == []
    clock.set(date(2028, 7, 5))
    [r] = svc.reminders()
    assert r.days_left == -1 and "minął" in r.message


def test_meeting_prep_data_for_uc4(svc):
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS, ADDITIONAL, goals=["Skrócić czas przekładów", " "])
    prep = svc.meeting_prep(c.id)
    assert prep.employee_name == "Grzegorz Wzór" and prep.evaluator_name == "Henryk Pryncypał"
    assert prep.sheet == "C" and prep.status == "kryteria wyznaczone"
    assert [k.id for k in prep.criteria] == list(R.mandatory("C")) + ADDITIONAL
    assert [k.mandatory for k in prep.criteria] == [True] * 5 + [False] * 2
    assert all(k.indicators for k in prep.criteria)
    assert prep.criteria[1].name == "Rzetelność"
    assert prep.goals == ("Skrócić czas przekładów",)
    assert prep.evaluation_deadline == date(2026, 6, 12) and prep.days_to_deadline == -3
    assert prep.previous_evaluation.outcome == "pozytywna"
    assert prep.previous_evaluation.level == "na poziomie oczekiwań"


FORBIDDEN = {"fastapi", "sqlite3", "litellm", "openai", "anthropic", "streamlit", "backend", "requests", "pandas"}


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_inner_layers_have_no_framework_or_io_imports(layer):
    root = Path(__file__).resolve().parent.parent / "app" / layer
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for n in names:
                assert n.split(".")[0] not in FORBIDDEN, f"{path.name} imports {n}"
                if layer == "domain":
                    assert not n.startswith("app."), f"domain must use relative imports only: {path.name}"
