"""Every dated example from the KPRM materials, as a test (proof that deadlines are counted the way KPRM does).

Sources (in server/data/kprm/wiedza/):
- L = liczenie-terminow.md ("KPRM – zasady liczenia terminów"),
- P = poradnik-oceny-okresowe-kprm.md (KPRM guide on periodic evaluations), page numbers as printed in the guide.
"""
from datetime import date

import pytest

from app.domain.calendar import WorkingCalendar, add_months
from app.domain.deadlines import (
    Absence,
    criteria_deadline,
    evaluation_deadline,
    extending_absences,
    is_longer_than,
    merge_absences,
    reevaluation_date,
)
from app.infrastructure.kprm_adapter import kprm_rulebook

R = kprm_rulebook()
CAL = WorkingCalendar()


# ---------------------------------------------------------------- months: same day number, else last day of month

@pytest.mark.parametrize(
    "start, months, expected, source",
    [
        (date(2024, 3, 16), 24, date(2026, 3, 16), "L: 24 mies. od 16.03.2024 upłynie 16.03.2026"),
        (date(2024, 1, 31), 13, date(2025, 2, 28), "L: 13 mies. od 31.01.2024 upłynie 28.02.2025"),
        (date(2024, 1, 31), 1, date(2024, 2, 29), "L: 1 mies. od 31.01.2024 (rok przestępny) – 29.02.2024"),
        (date(2013, 12, 4), 24, date(2015, 12, 4), "P s. 10: ostatnia ocena 4.12.2013 – kolejna 4.12.2015"),
    ],
)
def test_months_end_on_matching_day(start, months, expected, source):
    assert add_months(start, months) == expected, source


def test_evaluation_24_months_kprm_example():
    # P s. 10: 4.12.2015 is a Friday, so no shift
    assert evaluation_deadline(date(2013, 12, 4), R, CAL) == date(2015, 12, 4)


# ---------------------------------------------------------------- days: event day not counted, day off -> next working day

def test_criteria_30_days_from_employment_sunday_moves_to_monday():
    # P s. 10: hired 4.09.2015 -> 30 days end 4.10.2015 (Sunday) -> criteria "najpóźniej do końca dnia 5.10.2015"
    assert criteria_deadline(date(2015, 9, 4), R, CAL) == date(2015, 10, 5)


# ---------------------------------------------------------------- continuous justified absence longer than a month

def test_absence_days_off_between_periods_keep_continuity():
    # L (and reguly.json["przyklad_testowy_nieobecnosci"]): L4 5–16.10.2026 + leave 19.10–6.11.2026,
    # 17–18.10 is a weekend -> one absence 5.10–6.11.2026, longer than a month
    merged = merge_absences([Absence(date(2026, 10, 5), date(2026, 10, 16)), Absence(date(2026, 10, 19), date(2026, 11, 6))], CAL)
    assert [(a.start, a.end) for a in merged] == [(date(2026, 10, 5), date(2026, 11, 6))]
    assert is_longer_than(merged[0], R.absence_extends_after_months)


def test_absence_44_days_extends_deadline_then_sunday_moves_to_monday():
    # P s. 12: evaluation due 8.05.2015, continuous absence of 44 days in Nov–Dec 2014 ->
    # from 9.05.2015 add 44 days = 21.06.2015 (Sunday) -> 22.06.2015
    absence = Absence(date(2014, 11, 10), date(2014, 12, 23), "nieobecność ciągła")
    assert absence.days == 44
    assert evaluation_deadline(date(2013, 5, 8), R, CAL, [absence]) == date(2015, 6, 22)


def test_leave_then_sick_leave_41_days_extend_deadline():
    # P s. 13: 25-day leave from Tue 9.09.2014 (back due Tue 14.10), then sick leave, back Mon 20.10.2014 ->
    # continuous 9.09–19.10.2014, the month "upływał 9 października", extension = 41 days
    parts = [
        Absence(date(2014, 9, 9), date(2014, 10, 13), "urlop wypoczynkowy"),
        Absence(date(2014, 10, 14), date(2014, 10, 19), "zwolnienie lekarskie"),
    ]
    extending = extending_absences(parts, R, CAL)
    assert [(a.start, a.end) for a in extending] == [(date(2014, 9, 9), date(2014, 10, 19))]
    assert sum(a.days for a in extending) == 41
    # any cycle start: due 15.01.2015 (Thu) + 41 days = 25.02.2015 (Wed)
    assert evaluation_deadline(date(2013, 1, 15), R, CAL) == date(2015, 1, 15)
    assert evaluation_deadline(date(2013, 1, 15), R, CAL, parts) == date(2015, 2, 25)


@pytest.mark.parametrize(
    "end, longer",
    [
        (date(2014, 10, 8), False),
        (date(2014, 10, 9), False),  # P s. 13: the month from 9.09.2014 "upływał 9 października 2014"
        (date(2014, 10, 10), True),
    ],
)
def test_one_month_boundary_kprm(end, longer):
    assert is_longer_than(Absence(date(2014, 9, 9), end), R.absence_extends_after_months) is longer


def test_absence_of_exactly_one_month_does_not_extend_deadline():
    exactly_a_month = Absence(date(2014, 9, 9), date(2014, 10, 9))
    assert evaluation_deadline(date(2013, 1, 15), R, CAL, [exactly_a_month]) == date(2015, 1, 15)


# ---------------------------------------------------------------- re-evaluation after a negative evaluation

def test_reevaluation_kprm_example():
    # P s. 13–14: acknowledged negative evaluation 15.02.2015 -> re-evaluation "16.08.2015"; that day is a Sunday,
    # so it moves to Monday 17.08.2015 (KPRM mentor, 21.11.2026: the guide's example skipped the shift)
    assert reevaluation_date(date(2015, 2, 15), R, CAL) == date(2015, 8, 17)
