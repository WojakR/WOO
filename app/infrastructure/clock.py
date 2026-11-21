"""Clocks: the system clock of the office (production) and the controllable one (tests, demo "przewiń czas")."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

OFFICE_TZ = ZoneInfo("Europe/Warsaw")  # deadlines are calendar days in Poland, not in the server's zone


class SystemClock:
    """Today in Warsaw. Cannot be moved – production has no "przewiń czas"."""

    def today(self) -> date:
        return datetime.now(OFFICE_TZ).date()


class FixedClock:
    """Controllable clock for tests and the demo's "przewiń czas" button."""

    def __init__(self, today: date):
        self._today = today

    def today(self) -> date:
        return self._today

    def set(self, today: date) -> None:
        self._today = today

    def advance(self, days: int = 0, weeks: int = 0) -> date:
        self._today += timedelta(days=days, weeks=weeks)
        return self._today
