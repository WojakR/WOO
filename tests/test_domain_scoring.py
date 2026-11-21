from fractions import Fraction

import pytest

from app.domain.errors import ValidationError
from app.domain.scoring import (
    Outcome,
    compute_result,
    validate_additional_criteria,
    validate_evaluation,
)
from app.infrastructure.kprm_adapter import kprm_rulebook

R = kprm_rulebook()
C_MANDATORY = list(R.mandatory("C"))


def test_rulebook_comes_from_kprm_data():
    assert sorted(R.scale) == [1, 3, 5, 7, 9]
    assert R.cycle_months == 24 and R.criteria_days == 30 and R.criteria_days_after_negative == 7
    assert R.max_additional_criteria == 3
    assert C_MANDATORY == ["wykorzystywanie_wiedzy", "rzetelnosc", "organizacja_pracy", "wspolpraca", "komunikacja"]


def test_average_3_8_is_negative():
    r = compute_result([3, 3, 5, 5, 3], R)
    assert r.average == Fraction(19, 5) and r.average_display == 3.8
    assert r.level == "poniżej oczekiwań"
    assert r.outcome is Outcome.NEGATIVE


def test_any_partial_score_of_1_is_negative_despite_high_average():
    r = compute_result([9, 9, 9, 9, 1], R)
    assert r.average_display == 7.4 and r.level == "powyżej oczekiwań"
    assert r.outcome is Outcome.NEGATIVE


def test_average_6_75_is_positive_above_expectations():
    r = compute_result([7, 7, 7, 7, 7, 7, 7, 5], R)
    assert r.average_display == 6.75
    assert r.level == "powyżej oczekiwań"
    assert r.outcome is Outcome.POSITIVE


@pytest.mark.parametrize(
    "scores, level, outcome",
    [
        ([3, 3, 3, 3, 3, 3, 3, 3], "poniżej oczekiwań", Outcome.NEGATIVE),
        ([5, 3], "poniżej oczekiwań", Outcome.NEGATIVE),  # exactly 4 -> upper bound inclusive
        ([5, 5, 5, 5, 3], "na poziomie oczekiwań", Outcome.POSITIVE),  # 4.6
        ([7, 5], "na poziomie oczekiwań", Outcome.POSITIVE),  # exactly 6
        ([9, 7], "powyżej oczekiwań", Outcome.POSITIVE),  # exactly 8
        ([9, 9, 7], "znacznie powyżej oczekiwań", Outcome.POSITIVE),  # 8.33
        ([1, 3], "znacznie poniżej oczekiwań", Outcome.NEGATIVE),  # exactly 2
    ],
)
def test_band_boundaries(scores, level, outcome):
    r = compute_result(scores, R)
    assert r.level == level
    assert r.outcome is outcome


def test_only_scale_values_allowed():
    for bad in ([2, 5], [0], [10], [5.0], [True]):
        with pytest.raises(ValidationError):
            compute_result(bad, R)


def test_additional_criteria_rules():
    assert validate_additional_criteria("C", ["kreatywnosc", "negocjowanie", "myslenie_analityczne"], R) == []
    assert validate_additional_criteria("C", [], R) == []
    too_many = validate_additional_criteria("C", ["kreatywnosc", "negocjowanie", "myslenie_analityczne",
                                                  "orientacja_na_klienta"], R)
    assert any("najwyżej 3" in p for p in too_many)
    assert any("więcej niż raz" in p for p in validate_additional_criteria("C", ["kreatywnosc", "kreatywnosc"], R))
    assert any("obowiązkowe w arkuszu C" in p for p in validate_additional_criteria("C", ["rzetelnosc"], R))
    assert any("Nieznane" in p for p in validate_additional_criteria("C", ["latanie"], R))
    # zarządzanie ludźmi is mandatory in B but may be additional in C
    assert validate_additional_criteria("C", ["zarzadzanie_ludzmi"], R) == []
    assert validate_additional_criteria("B", ["zarzadzanie_ludzmi"], R) != []


def test_negative_requires_justification_and_iprz_always_required():
    neg = dict(zip(C_MANDATORY, [3, 3, 5, 5, 3]))
    with pytest.raises(ValidationError) as e:
        validate_evaluation(C_MANDATORY, neg, "", "", R)
    assert len(e.value.problems) == 2
    assert any("uzasadnienie" in p for p in e.value.problems)
    assert any("rozwoju zawodowego" in p for p in e.value.problems)
    assert validate_evaluation(C_MANDATORY, neg, "Uzasadnienie.", "Szkolenie.", R).outcome is Outcome.NEGATIVE

    pos = dict(zip(C_MANDATORY, [5, 5, 7, 7, 5]))
    assert validate_evaluation(C_MANDATORY, pos, "", "Szkolenie.", R).outcome is Outcome.POSITIVE
    with pytest.raises(ValidationError):
        validate_evaluation(C_MANDATORY, pos, "", "   ", R)


def test_scores_must_cover_exactly_sheet_criteria():
    partial = dict(zip(C_MANDATORY[:4], [5, 5, 5, 5]))
    with pytest.raises(ValidationError, match="Brak oceny cząstkowej dla: Komunikacja"):
        validate_evaluation(C_MANDATORY, partial, "", "x", R)
    extra = {**dict(zip(C_MANDATORY, [5] * 5)), "kreatywnosc": 5}
    with pytest.raises(ValidationError, match="spoza arkusza: Kreatywność"):
        validate_evaluation(C_MANDATORY, extra, "", "x", R)
