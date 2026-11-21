"""Deadlines (art. 81 of the Act, § 7 of the regulation, KPRM "liczenie terminów").

- evaluation: start + N months (end-of-month clamping), extended by every justified continuous absence
  longer than M months, then moved off a Saturday / Sunday / holiday;
- criteria: N days counted from the day after the event (shorter after a negative evaluation), moved likewise;
- re-evaluation after a negative evaluation, objection, change of position (art. 81 ust. 6, 9; art. 83; § 9).
All values come from reguly.json via RuleBook; the rules and their sources are listed in docs/terminy.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Literal

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
    """A period of exactly `months` months ends ON add_months(start); only an end after that is longer.

    KPRM guide p. 13: for an absence from 9.09.2014 "miesięczny okres … upływał 9 października 2014",
    so 9.09–9.10 is exactly one month and 9.09–10.10 is longer than a month.
    """
    return absence.end > add_months(absence.start, months)


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


def reevaluation_date(acknowledged: date, rules: RuleBook, cal: WorkingCalendar | None = None) -> date:
    """Art. 81 ust. 9: re-evaluation "po upływie 6 miesięcy od dnia zapoznania się" with a negative evaluation.

    The day after the N-month period ends (KPRM guide: acknowledged 15.02.2015 -> after 15.08.2015), moved off
    a Saturday / Sunday / holiday like every other deadline: 16.08.2015 is a Sunday -> 17.08.2015 (confirmed by
    the KPRM mentor, 21.11.2026 – the guide's example skipped the shift).
    NOT extended by absences: art. 81 ust. 7–8 apply only to the 24-month deadline (ust. 4).
    """
    cal = cal or WorkingCalendar()
    return cal.next_working_day(add_months(acknowledged, rules.reevaluation_after_negative_months) + timedelta(days=1))


def delivery_day(acknowledged: date, absences: Iterable[Absence], cal: WorkingCalendar | None = None) -> date:
    """The day the evaluation counts as delivered for the objection period (spec, use case "Pani X"): the
    acknowledgement, or – if a justified absence of the evaluated person is going on that day – the first day
    back at work (end of that absence + 1; absences that follow without a gap are joined). The period then runs
    from that day like from an acknowledgement: the day itself is not counted."""
    periods = sorted((a for a in absences if a.justified), key=lambda a: a.start)
    end = None
    for a in periods:
        if end is None and a.start <= acknowledged <= a.end:
            end = a.end
        elif end is not None and a.start <= end + timedelta(days=1):
            end = max(end, a.end)
    if end is None:
        return acknowledged
    back = end + timedelta(days=1)
    return cal.next_working_day(back) if cal else back  # back at work on the first working day


def objection_deadline(acknowledged: date, rules: RuleBook, cal: WorkingCalendar) -> date:
    """Art. 83 ust. 1: objection within N days of acknowledging the evaluation.

    The acknowledgement day is not counted; an end on Saturday / Sunday / holiday moves to the next working day.
    """
    return cal.next_working_day(acknowledged + timedelta(days=rules.objection_days))


@dataclass(frozen=True)
class PositionChange:
    """What a change of position with a significant change of duties means for the running cycle.

    NOWE_KRYTERIA (§ 9 ust. 1): the change falls within 6 months of the reference date – criteria and the opening
        conversation are done again by `deadline`; the evaluation deadline does NOT change.
    OCENA (art. 81 ust. 6, § 9 ust. 2): more than 6 months have passed – an evaluation is made between
        `earliest` (7 days before the change) and `deadline` (30 days after it).
    """

    kind: Literal["NOWE_KRYTERIA", "OCENA"]
    change: date
    reference: date
    deadline: date
    earliest: date | None = None


def position_change(change: date, reference: date, rules: RuleBook, cal: WorkingCalendar) -> PositionChange:
    """`reference` = date of the last evaluation, or – for someone evaluated for the first time – the date the
    criteria were set (§ 9 ust. 1; art. 81 ust. 6: "okres podlegający ocenie jest dłuższy niż 6 miesięcy").

    "More than 6 months" uses the same month arithmetic as absences: a period of exactly 6 months ends ON
    add_months(reference, 6), so only a change after that day counts as later than 6 months.
    The latest day moves off a Saturday / Sunday / holiday (art. 115 Civil Code, as for every deadline in days);
    the earliest day is a "not before" bound and is not moved.
    """
    if change < reference:
        raise ValidationError([f"Zmiana stanowiska ({change:%d.%m.%Y}) nie może być wcześniejsza niż "
                               f"data odniesienia ({reference:%d.%m.%Y})."])
    if change > add_months(reference, rules.position_change_threshold_months):
        return PositionChange(
            "OCENA", change, reference,
            deadline=cal.next_working_day(change + timedelta(days=rules.position_change_eval_days_after)),
            earliest=change - timedelta(days=rules.position_change_eval_days_before),
        )
    return PositionChange(
        "NOWE_KRYTERIA", change, reference,
        deadline=cal.next_working_day(change + timedelta(days=rules.position_change_criteria_days)),
    )
