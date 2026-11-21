"""Deadlines (art. 81 of the Act, § 7 of the regulation, KPRM "liczenie terminów").

- evaluation: start + N months (end-of-month clamping), extended by every justified continuous absence
  longer than M months, then moved off a Saturday / Sunday / holiday;
- criteria: N days counted from the day after the event (shorter after a negative evaluation), moved likewise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .calendar import WorkingCalendar, add_months
from .errors import ValidationError
from .rulebook import RuleBook


@dataclass(frozen=True)
class Absence:
    start: date
    end: date  # inclusive
    kind: str = ""
    justified: bool = True

    def __post_init__(self):
        if self.end < self.start:
            raise ValidationError([f"Nieobecność kończy się ({self.end}) przed jej początkiem ({self.start})."])

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def merge_absences(absences: Iterable[Absence], cal: WorkingCalendar) -> list[Absence]:
    """Join justified absences into continuous periods; days off between them do not break continuity."""
    periods = sorted((a for a in absences if a.justified), key=lambda a: a.start)
    merged: list[Absence] = []
    for a in periods:
        if merged and _continuous(merged[-1].end, a.start, cal):
            last = merged[-1]
            kinds = last.kind if a.kind in last.kind.split(" + ") else f"{last.kind} + {a.kind}".strip(" +")
            merged[-1] = Absence(last.start, max(last.end, a.end), kinds)
        else:
            merged.append(a)
    return merged


def _continuous(prev_end: date, next_start: date, cal: WorkingCalendar) -> bool:
    day = prev_end + timedelta(days=1)
    while day < next_start:
        if not cal.is_day_off(day):
            return False
        day += timedelta(days=1)
    return True


def is_longer_than(absence: Absence, months: int) -> bool:
    """A period of exactly `months` months ends the day before add_months(start); anything later is longer."""
    return absence.end >= add_months(absence.start, months)


def extending_absences(absences: Iterable[Absence], rules: RuleBook, cal: WorkingCalendar) -> list[Absence]:
    return [a for a in merge_absences(absences, cal) if is_longer_than(a, rules.absence_extends_after_months)]


def evaluation_deadline(
    start: date, rules: RuleBook, cal: WorkingCalendar, absences: Iterable[Absence] = ()
) -> date:
    base = add_months(start, rules.cycle_months)
    extension = sum(a.days for a in extending_absences(absences, rules, cal))
    return cal.next_working_day(base + timedelta(days=extension))


def criteria_deadline(event: date, rules: RuleBook, cal: WorkingCalendar, after_negative: bool = False) -> date:
    days = rules.criteria_days_after_negative if after_negative else rules.criteria_days
    return cal.next_working_day(event + timedelta(days=days))


def reevaluation_date(acknowledged: date, rules: RuleBook) -> date:
    """Art. 81 ust. 9: re-evaluation "po upływie 6 miesięcy od dnia zapoznania się" with a negative evaluation.

    The day after the N-month period ends, as in the KPRM guide: acknowledged 15.02.2015 -> 16.08.2015.
    Deliberately NOT extended by absences and NOT moved off a day off: art. 81 ust. 7–8 apply only to the
    24-month deadline (ust. 4), and the KPRM example keeps 16.08.2015 although it is a Sunday.
    """
    return add_months(acknowledged, rules.reevaluation_after_negative_months) + timedelta(days=1)


def objection_deadline(acknowledged: date, rules: RuleBook, cal: WorkingCalendar) -> date:
    """Art. 83 ust. 1: objection within N days of acknowledging the evaluation.

    The acknowledgement day is not counted; an end on Saturday / Sunday / holiday moves to the next working day.
    """
    return cal.next_working_day(acknowledged + timedelta(days=rules.objection_days))
