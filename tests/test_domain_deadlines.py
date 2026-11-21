from datetime import date

import pytest

from app.domain.calendar import WorkingCalendar, add_months, easter_sunday
from app.domain.deadlines import (
    Absence,
    criteria_deadline,
    evaluation_deadline,
    is_longer_than,
    merge_absences,
)
from app.domain.errors import ValidationError
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend import kprm

R = kprm_rulebook()
CAL = WorkingCalendar()


@pytest.mark.parametrize(
    "start, months, expected",
    [
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # leap year
        (date(2025, 1, 31), 1, date(2025, 2, 28)),
        (date(2024, 1, 31), 13, date(2025, 2, 28)),  # KPRM example
        (date(2024, 3, 16), 24, date(2026, 3, 16)),  # KPRM example
        (date(2024, 12, 15), 1, date(2025, 1, 15)),
        (date(2024, 8, 31), 6, date(2025, 2, 28)),
    ],
)
def test_add_months_clamps_to_month_end(start, months, expected):
    assert add_months(start, months) == expected


def test_polish_holidays():
    assert easter_sunday(2026) == date(2026, 4, 5)
    for d in (date(2026, 4, 6), date(2026, 6, 4), date(2026, 11, 11), date(2026, 12, 24), date(2026, 1, 6)):
        assert CAL.is_day_off(d), d
    assert not CAL.is_day_off(date(2026, 11, 12))
    assert CAL.is_day_off(date(2026, 11, 21))  # Saturday
    assert WorkingCalendar([date(2026, 11, 12)]).is_day_off(date(2026, 11, 12))


@pytest.mark.parametrize(
    "start, expected",
    [
        (date(2024, 6, 12), date(2026, 6, 12)),  # Friday – unchanged
        (date(2024, 11, 21), date(2026, 11, 23)),  # Saturday -> Monday
        (date(2024, 11, 11), date(2026, 11, 12)),  # Independence Day -> next day
        (date(2024, 12, 24), date(2026, 12, 28)),  # 24–27.12 off (holidays + weekend)
    ],
)
def test_evaluation_deadline_24_months_and_working_day_shift(start, expected):
    assert evaluation_deadline(start, R, CAL) == expected


def _kprm_example_absences() -> list[Absence]:
    ex = kprm.rules()["przyklad_testowy_nieobecnosci"]
    return [Absence(date.fromisoformat(o["od"]), date.fromisoformat(o["do"]), o["typ"]) for o in ex["okresy"]]


def test_kprm_absence_example_is_continuous_and_longer_than_a_month():
    expected = kprm.rules()["przyklad_testowy_nieobecnosci"]["oczekiwany_wynik"]
    merged = merge_absences(_kprm_example_absences(), CAL)
    assert len(merged) == 1
    assert merged[0].start == date.fromisoformat(expected["ciagla_od"])
    assert merged[0].end == date.fromisoformat(expected["ciagla_do"])
    assert is_longer_than(merged[0], R.absence_extends_after_months) is expected["dluzsza_niz_miesiac"]
    assert merged[0].days == 33


def test_working_day_between_absences_breaks_continuity():
    parts = [Absence(date(2026, 10, 5), date(2026, 10, 16)), Absence(date(2026, 10, 20), date(2026, 11, 6))]
    merged = merge_absences(parts, CAL)
    assert len(merged) == 2
    assert not any(is_longer_than(a, 1) for a in merged)


def test_unjustified_absence_is_ignored():
    assert merge_absences([Absence(date(2026, 1, 5), date(2026, 3, 5), justified=False)], CAL) == []


def test_exactly_one_month_is_not_longer_than_a_month():
    assert not is_longer_than(Absence(date(2026, 10, 5), date(2026, 11, 4)), 1)
    assert is_longer_than(Absence(date(2026, 10, 5), date(2026, 11, 5)), 1)


def test_long_absence_extends_evaluation_deadline_by_its_length():
    start = date(2024, 11, 23)
    assert evaluation_deadline(start, R, CAL) == date(2026, 11, 23)
    # +33 days -> 26.12.2026 (holiday, Saturday), 27.12 Sunday -> Monday 28.12
    assert evaluation_deadline(start, R, CAL, _kprm_example_absences()) == date(2026, 12, 28)
    short = [Absence(date(2026, 10, 5), date(2026, 10, 16))]
    assert evaluation_deadline(start, R, CAL, short) == date(2026, 11, 23)


def test_criteria_deadline_30_days_or_7_after_negative():
    assert criteria_deadline(date(2024, 6, 12), R, CAL) == date(2024, 7, 12)
    assert criteria_deadline(date(2024, 6, 12), R, CAL, after_negative=True) == date(2024, 6, 19)
    assert criteria_deadline(date(2026, 11, 14), R, CAL, after_negative=True) == date(2026, 11, 23)  # Sat -> Mon


def test_absence_end_before_start_rejected():
    with pytest.raises(ValidationError):
        Absence(date(2026, 2, 1), date(2026, 1, 1))
