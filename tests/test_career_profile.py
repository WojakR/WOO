"""Personalised hints from the person's history (spec points 3 and 9): tenure + trend of the evaluations ->
conversation topics (HR partner, conversation prep) and development ideas (IPRZ). Also the more careful score hint
(it counts notes, not their weight) and the history from the HR data."""
from dataclasses import replace
from datetime import date

import pytest

from app.application.assistant import AiSuggestionService
from app.application.use_cases import EvaluationService
from app.domain.career_profile import ProfileSettings, ResultPoint, employee_profile, tenure_months
from app.domain.consequences import FinishedEvaluation
from app.domain.cycle import PreviousEvaluation
from app.domain.evidence_hint import suggest_points
from app.infrastructure.ai_models import OffModel
from app.infrastructure.assistant_factory import kprm_catalog
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, _employee, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository
from app.infrastructure.settings import load_office_settings

R = kprm_rulebook()
TODAY = date(2026, 6, 15)
TOP = len(R.level_bands) - 1  # 4 = "znacznie powyżej oczekiwań"
LOW, EXP, ABOVE = "poniżej oczekiwań", "na poziomie oczekiwań", "powyżej oczekiwań"


def pts(*ranks, current_last=False):
    out = [ResultPoint(date(2018 + 2 * i, 6, 1), f"poziom {r}", r) for i, r in enumerate(ranks)]
    if current_last and out:
        out[-1] = replace(out[-1], on=None, current=True)
    return out


def kinds(points, start=None, today=TODAY, settings=ProfileSettings()):
    return [f.kind for f in employee_profile(points, TOP, start, today, settings)]


# ---------------------------------------------------------------- domain

def test_tenure_counts_full_months():
    assert tenure_months(date(2015, 3, 2), date(2026, 6, 15)) == 135
    assert tenure_months(date(2026, 1, 20), date(2026, 6, 15)) == 4
    assert tenure_months(None, TODAY) is None and tenure_months(date(2027, 1, 1), TODAY) is None


def test_long_tenure_and_a_drop_is_the_personal_decline_signal():
    found = employee_profile(pts(3, 2, 1, current_last=True), TOP, date(2015, 3, 2), TODAY)
    assert [f.kind for f in found] == ["SPADEK_PRZY_STAZU"]
    assert found[0].evidence[0] == "staż w urzędzie: 11 lat 3 mies."
    assert "teraz (z wpisanych ocen cząstkowych): poziom 1" in found[0].evidence[1]


def test_falling_trend_without_long_tenure_and_a_single_drop_is_not_a_trend():
    assert kinds(pts(3, 2, 1), start=date(2023, 1, 1)) == ["SPADEK_TRENDU"]
    assert kinds(pts(3, 2, 1)) == ["SPADEK_TRENDU"]  # tenure unknown
    assert kinds(pts(3, 2), start=date(2023, 1, 1)) == []  # one drop: SPADEK_OCEN of the HR partner covers it
    assert kinds(pts(3, 3, 2), start=date(2023, 1, 1)) == []


def test_plateau_needs_experience_and_is_not_reported_on_the_top_levels():
    assert kinds(pts(2, 2), start=date(2017, 2, 1)) == ["STAGNACJA"]
    assert kinds(pts(2, 2), start=date(2024, 1, 1)) == []  # 2 years – not "more experience" yet
    assert kinds(pts(2, 2, 2)) == ["STAGNACJA"]  # tenure unknown, but a long history
    assert kinds(pts(2, 2)) == []
    assert kinds(pts(3, 3), start=date(2010, 1, 1)) == ["STABILNIE_WYSOKO"]
    assert kinds(pts(4, 4)) == ["STABILNIE_WYSOKO"]


def test_rise_and_new_employee():
    assert kinds(pts(1, 2)) == ["WZROST"]
    assert kinds([], start=date(2026, 1, 5)) == ["NOWY_PRACOWNIK"]
    assert kinds([], start=date(2025, 1, 5)) == []


def test_thresholds_come_from_the_office_settings():
    raw = load_office_settings().employee_profile
    s = ProfileSettings.from_dict(raw)
    assert (s.long_tenure_years, s.trend_evaluations) == (raw["staz_dlugi_lat"], raw["trend_ocen"])
    assert kinds(pts(3, 2, 1), start=date(2023, 1, 1), settings=ProfileSettings(long_tenure_years=3)) == \
        ["SPADEK_PRZY_STAZU"]
    with pytest.raises(ValueError):
        ProfileSettings.from_dict({"trend_ocen": 1})
    texts = raw["sygnaly"]
    assert {"SPADEK_PRZY_STAZU", "SPADEK_TRENDU", "STAGNACJA", "STABILNIE_WYSOKO", "WZROST", "NOWY_PRACOWNIK"} <= set(texts)
    assert all(t["opis"] and t["rekomendacje"] and t["rozwoj"] for t in texts.values())


def test_the_catalog_never_diagnoses():
    from app.application.assistant import _BANNED_IN_HR

    text = str(load_office_settings().employee_profile["sygnaly"]).casefold()  # the texts shown to the evaluator
    assert not any(b in text for b in _BANNED_IN_HR)


# ---------------------------------------------------------------- assistant

DIR = KprmEmployeeDirectory()
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
VETERAN = replace(DIR.get(EMP), employment_start=date(2015, 3, 2),
                  earlier_evaluations=(PreviousEvaluation("pozytywna", ABOVE, date(2022, 6, 10)),))


@pytest.fixture
def cycle():
    svc = EvaluationService(R, InMemoryCycleRepository(), DIR, FixedClock(TODAY))
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS, ["orientacja_na_klienta", "kreatywnosc"])
    svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, BOSS)
    c = svc.cycles.get(c.id)
    c.scores = dict(zip(c.criteria_ids(R), [3, 3, 3, 5, 3, 3, 5], strict=True))  # "poniżej oczekiwań"
    return c


def service():
    return AiSuggestionService(R, OffModel(), kprm_catalog())


def test_assistant_reads_the_history_from_the_hr_data(cycle):
    signals = service().profile_signals(cycle, VETERAN, TODAY)
    assert [s.kind for s in signals] == ["SPADEK_PRZY_STAZU"]
    s = signals[0]
    assert any("urlop" in r for r in s.recommendations) and s.development
    assert "10.06.2022: powyżej oczekiwań → 12.06.2024: na poziomie oczekiwań → teraz" in s.evidence[1]


def test_without_tenure_or_catalog_there_is_nothing_personal(cycle):
    assert service().profile_signals(cycle, DIR.get(EMP), TODAY) == []  # one drop, tenure unknown
    bare = AiSuggestionService(R, OffModel(), replace(kprm_catalog(), profile={}))
    assert bare.profile_signals(cycle, VETERAN, TODAY) == []


def test_hr_partner_replaces_the_simple_drop_with_the_personal_signal(cycle):
    plain = [s.kind for s in service().hr_partner(cycle, DIR.get(EMP), [], [], TODAY).signals]
    assert "SPADEK_OCEN" in plain
    vet = [s.kind for s in service().hr_partner(cycle, VETERAN, [], [], TODAY).signals]
    assert "SPADEK_PRZY_STAZU" in vet and "SPADEK_OCEN" not in vet


def test_explicit_history_wins_over_the_hr_data(cycle):
    history = [FinishedEvaluation(date(2020, 6, 1), "pozytywna", LOW), FinishedEvaluation(date(2022, 6, 1), "pozytywna", LOW),
               FinishedEvaluation(date(2024, 6, 12), "pozytywna", LOW)]
    kinds_ = [s.kind for s in service().profile_signals(cycle, VETERAN, TODAY, history)]
    assert kinds_ == ["STAGNACJA"]  # the current one is "poniżej" too


def test_conversation_prep_puts_the_personal_hints_first(cycle):
    prep = service().conversation_prep(cycle, VETERAN, DIR.get(BOSS), [], TODAY)
    personal = next(s for s in prep.hr_signals if s.kind == "SPADEK_PRZY_STAZU")
    assert prep.development[0] == personal.development[0]
    assert any(t.startswith(personal.description) for t in prep.difficult_topics)


def test_prep_prompt_carries_tenure_and_history_without_names(cycle):
    from tests.test_assistant import FakeModel

    model = FakeModel({})  # invalid answer -> template, but the prompt is recorded
    AiSuggestionService(R, model, kprm_catalog()).conversation_prep(cycle, VETERAN, DIR.get(BOSS), [], TODAY)
    assert "Staż i historia ocen: staż w urzędzie: 11 lat 3 mies.; oceny: 10.06.2022: powyżej oczekiwań" in model.prompts[0]
    assert "Grzegorz" not in model.prompts[0] and "SPADEK_PRZY_STAZU" in model.prompts[0]


def test_iprz_draft_uses_the_history_only_when_asked(cycle):
    svc = service()
    with_history = svc.draft("IPRZ", cycle, VETERAN, [], today=TODAY)
    without = svc.draft("IPRZ", cycle, VETERAN, [])
    first_dev = svc.profile_signals(cycle, VETERAN, TODAY)[0].development[0]
    assert first_dev in with_history.text and first_dev not in without.text
    assert with_history.key != without.key


# ---------------------------------------------------------------- data + API

def test_hr_data_gives_tenure_and_earlier_evaluations():
    e = _employee({"id": "x", "imie": "A", "nazwisko": "B", "arkusz": "C", "data_zatrudnienia": "2015-03-02",
                   "poprzednia_ocena": {"ocena": "pozytywna", "poziom": EXP, "data": "2024-06-12"},
                   "wczesniejsze_oceny": [{"ocena": "pozytywna", "poziom": ABOVE, "data": "2022-06-10"}]})
    assert e.employment_start == date(2015, 3, 2)
    assert e.earlier_evaluations == (PreviousEvaluation("pozytywna", ABOVE, date(2022, 6, 10)),)


def test_history_of_includes_the_earlier_evaluations():
    from app.api.history import history_of
    from app.api.state import build_state

    st = build_state(TODAY)
    st.import_employees([VETERAN])
    assert [h.level for h in history_of(st, EMP)] == [ABOVE, EXP]


def test_demo_scenario_shows_the_personal_signals_in_the_hr_partner():
    from fastapi.testclient import TestClient

    from app.api.state import build_state, get_state
    from backend.main import app

    st = build_state(scenario=True)
    app.dependency_overrides[get_state] = lambda: st
    try:
        client = TestClient(app)
        found = {}
        for c in st.evaluations.cycles.list_all():
            if c.employee_id in ("grzegorz.wzor", "monika.testowa", "agata.wzorcowa"):
                body = client.get(f"/api/evaluations/{c.id}/hr-partner", headers={"X-User-Id": c.evaluator_id}).json()
                found[c.employee_id] = {s["typ"]: s for s in body["sygnaly"]}
    finally:
        app.dependency_overrides.pop(get_state, None)
    assert "SPADEK_PRZY_STAZU" in found["grzegorz.wzor"] and "SPADEK_OCEN" not in found["grzegorz.wzor"]
    assert found["grzegorz.wzor"]["SPADEK_PRZY_STAZU"]["dzialania_rozwojowe"]
    assert "STAGNACJA" in found["monika.testowa"] and "NOWY_PRACOWNIK" in found["agata.wzorcowa"]


# ---------------------------------------------------------------- score hint (it counts notes, not their weight)

SCALE = [1, 3, 5, 7, 9]


def test_score_hint_gives_its_range_and_says_it_counts_notes():
    h = suggest_points(3, 1, SCALE)
    assert (h.points, h.low, h.high) == (7, 5, 7) and not h.certain
    assert "od 5 do 7 pkt" in h.reason and "nie ich wagę" in h.reason and "ustala oceniający" in h.reason
    stable = suggest_points(2, 2, SCALE)
    assert stable.certain and "niepewna" not in stable.reason


def test_score_hint_still_needs_three_notes_and_avoids_the_extremes():
    assert suggest_points(1, 1, SCALE) is None  # one long praise + one remark: no number at all
    assert suggest_points(10, 0, SCALE).points == 7 and suggest_points(0, 10, SCALE).points == 3
