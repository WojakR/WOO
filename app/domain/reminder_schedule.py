"""Reminder schedules per stage of the process – an office/user setting, not a rule of law.

Each stage (defining criteria, the evaluation period, acknowledging the evaluation) has its own list of rules,
as many as someone wants (1 or 20):
- CO_DNI n          – every n days from the start of the stage until its deadline (e.g. "add the criteria!"),
- DNI_PRZED n       – n days before the deadline; TYGODNIE_PRZED / MIESIACE_PRZED likewise,
- PROCENT_OKRESU p  – when p % of the stage has passed (the evaluation period is 12–24 months, so 50 % / 75 %
                      adapts to its length).
Reminders are sent only on working days, inside office working hours: a date on a Saturday / Sunday / holiday
moves to the previous working day (so it still comes before the deadline), and a time outside working hours is
rejected when the schedule is saved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum

from .calendar import WorkingCalendar, add_months
from .errors import ValidationError


class Stage(str, Enum):
    CRITERIA = "WYZNACZENIE_KRYTERIOW"  # cycle started -> criteria set and confirmed (30 / 7 days)
    PERIOD = "OKRES_OCENY"  # criteria confirmed -> evaluation drawn up (24 months or 6 after a negative one)
    ACKNOWLEDGEMENT = "ZAPOZNANIE"  # evaluation drawn up -> employee acknowledged it
    OBJECTION_REVIEW = "ROZPATRZENIE_SPRZECIWU"  # objection filed -> decided (14 days, art. 83 ust. 3)


class RuleKind(str, Enum):
    EVERY_DAYS = "CO_DNI"
    DAYS_BEFORE = "DNI_PRZED"
    WEEKS_BEFORE = "TYGODNIE_PRZED"
    MONTHS_BEFORE = "MIESIACE_PRZED"
    PERCENT = "PROCENT_OKRESU"


_LIMITS = {RuleKind.EVERY_DAYS: (1, 365), RuleKind.DAYS_BEFORE: (0, 730), RuleKind.WEEKS_BEFORE: (1, 104),
           RuleKind.MONTHS_BEFORE: (1, 24), RuleKind.PERCENT: (1, 99)}
MAX_RULES_PER_STAGE = 30


@dataclass(frozen=True)
class ReminderRule:
    kind: RuleKind
    value: int

    def label(self) -> str:
        return {RuleKind.EVERY_DAYS: "co {} dni", RuleKind.DAYS_BEFORE: "{} dni przed terminem",
                RuleKind.WEEKS_BEFORE: "{} tyg. przed terminem", RuleKind.MONTHS_BEFORE: "{} mies. przed terminem",
                RuleKind.PERCENT: "po {} % okresu"}[self.kind].format(self.value)


@dataclass(frozen=True)
class WorkingHours:
    start: time = time(8, 0)
    end: time = time(16, 0)

    def __post_init__(self):
        if not self.start < self.end:
            raise ValidationError(["Godziny pracy: początek musi być przed końcem."])

    def contains(self, t: time) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class ReminderSchedule:
    rules: dict[Stage, tuple[ReminderRule, ...]] = field(default_factory=dict)
    at: time = time(11, 0)  # hour the reminders arrive

    def validated(self, hours: WorkingHours) -> ReminderSchedule:
        """Every rule within limits; the hour inside office working hours (no reminders after hours)."""
        problems = []
        if not hours.contains(self.at):
            problems.append(f"Przypomnienia przychodzą tylko w godzinach pracy urzędu "
                            f"({hours.start:%H:%M}–{hours.end:%H:%M}), nie o {self.at:%H:%M}.")
        for stage, rules in self.rules.items():
            if len(rules) > MAX_RULES_PER_STAGE:
                problems.append(f"Etap {stage.value}: najwyżej {MAX_RULES_PER_STAGE} przypomnień.")
            for r in rules:
                lo, hi = _LIMITS[r.kind]
                if not lo <= r.value <= hi:
                    problems.append(f"Etap {stage.value}: „{r.label()}” – wartość spoza zakresu {lo}–{hi}.")
        if problems:
            raise ValidationError(problems)
        return self


def _previous_working_day(d: date, cal: WorkingCalendar) -> date:
    while cal.is_day_off(d):
        d -= timedelta(days=1)
    return d


def reminder_dates(rules: tuple[ReminderRule, ...], start: date, deadline: date,
                   cal: WorkingCalendar) -> list[date]:
    """Working days on which reminders for one stage go out (sorted, no duplicates), all in [start, deadline]."""
    days: set[date] = set()
    span = (deadline - start).days
    for r in rules:
        if r.kind is RuleKind.EVERY_DAYS:
            d = start + timedelta(days=r.value)
            while d < deadline:
                days.add(d)
                d += timedelta(days=r.value)
        elif r.kind is RuleKind.PERCENT:
            days.add(start + timedelta(days=span * r.value // 100))
        elif r.kind is RuleKind.MONTHS_BEFORE:
            days.add(add_months(deadline, -r.value))
        else:
            weeks = r.kind is RuleKind.WEEKS_BEFORE
            days.add(deadline - timedelta(days=r.value * (7 if weeks else 1)))
    out = set()
    for d in days:
        if start <= d <= deadline:
            w = _previous_working_day(d, cal)
            out.add(w if w >= start else cal.next_working_day(d))
    return sorted(d for d in out if start <= d <= deadline)


def at_time(day: date, schedule: ReminderSchedule) -> datetime:
    return datetime.combine(day, schedule.at)
