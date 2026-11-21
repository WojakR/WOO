"""Calendar arithmetic: months with end-of-month clamping and Polish working days.

Public holidays follow the Act on non-working days (ustawa z 18.01.1951 o dniach wolnych od pracy).
They are not in the KPRM data, so the statutory list is computed here (movable feasts from Easter);
`WorkingCalendar(extra_holidays=...)` lets an office add more days off.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable


def add_months(start: date, months: int) -> date:
    """Same day number `months` later; if that day does not exist – last day of that month (31.01 + 1 = 28/29.02)."""
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, _cal.monthrange(year, month)[1]))


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous algorithm, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@lru_cache
def polish_public_holidays(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    days = {
        date(year, 1, 1),
        date(year, 5, 1),
        date(year, 5, 3),
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
        easter,
        easter + timedelta(days=1),  # Easter Monday
        easter + timedelta(days=49),  # Pentecost
        easter + timedelta(days=60),  # Corpus Christi
    }
    if year >= 2011:
        days.add(date(year, 1, 6))  # Epiphany
    if year >= 2025:
        days.add(date(year, 12, 24))  # Christmas Eve
    return frozenset(days)


class WorkingCalendar:
    def __init__(self, extra_holidays: Iterable[date] = ()):
        self._extra = frozenset(extra_holidays)

    def is_day_off(self, day: date) -> bool:
        """Saturday, Sunday or a public holiday."""
        return day.weekday() >= 5 or day in polish_public_holidays(day.year) or day in self._extra

    def next_working_day(self, day: date) -> date:
        """`day` itself if it is a working day, otherwise the first working day after it."""
        while self.is_day_off(day):
            day += timedelta(days=1)
        return day
