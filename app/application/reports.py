"""Reports for HR, the director general and managers (spec, point 4): progress of the evaluations across the
organisation (T17) and their outcomes (T18). Pure aggregation over cycles – the router only picks the scope
(AccessPolicy: HR the whole office, a manager their subtree) and shapes the JSON.

Deadlines are the ones the evaluation shows (app/domain/timeline.py), never computed again here.
Outcomes hide every group with fewer than `min_group` people, so nobody can be identified from a chart.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Callable, Iterable, Sequence

from app.domain.calendar import WorkingCalendar
from app.domain.cycle import EvaluationCycle, Status
from app.domain.employee import Employee
from app.domain.rulebook import RuleBook
from app.domain.scoring import Outcome
from app.domain.timeline import deadlines_of

OVERDUE_KINDS = ("KRYTERIA", "OCENA", "ROZPATRZENIE_SPRZECIWU")  # what the office must do on time
WAITING_FOR_EMPLOYEE = (Status.CRITERIA_SET, Status.EVALUATION_DONE)
NO_UNIT = "(bez komórki)"


@dataclass(frozen=True)
class Scope:
    """What a report is about: the people visible to the user, their cycles, and the rules to read them by."""
    employees: Sequence[Employee]
    cycles: Sequence[EvaluationCycle]
    rules_for: Callable[[EvaluationCycle], RuleBook]
    calendar: WorkingCalendar
    today: date
    year: int | None = None
    unit: str | None = None

    def people(self) -> list[Employee]:
        return [e for e in self.employees if e.evaluator_id and (self.unit is None or e.unit == self.unit)]

    def in_scope(self) -> list[EvaluationCycle]:
        """Cycles of the people in scope (not imported ones), by the year of their evaluation deadline."""
        ids = {e.id for e in self.people()}
        out = []
        for c in self.cycles:
            if c.employee_id not in ids or c.imported:
                continue
            if self.year is not None and c.evaluation_deadline(self.rules_for(c), self.calendar).year != self.year:
                continue
            out.append(c)
        return out


# ---------------------------------------------------------------- T17 progress

@dataclass
class UnitProgress:
    unit: str
    people: int = 0
    cycles: int = 0
    drawn_up: int = 0
    in_progress: int = 0
    overdue: int = 0
    on_time: int = 0

    @property
    def on_time_percent(self) -> float | None:
        return round(100 * self.on_time / self.drawn_up, 1) if self.drawn_up else None


@dataclass
class Progress:
    people: int
    cycles: int
    statuses: dict[str, int]
    drawn_up: int
    in_progress: int
    waiting_for_employee: int
    overdue: int
    on_time: int
    on_time_percent: float | None
    not_started: int  # people without any cycle in scope
    stage_days: dict[str, float]  # status -> average days spent in it (finished stays only)
    units: list[UnitProgress] = field(default_factory=list)
    overdue_cycles: list[str] = field(default_factory=list)


def _overdue(c: EvaluationCycle, scope: Scope) -> bool:
    items = deadlines_of(c, scope.rules_for(c), scope.calendar, scope.today)
    return any(i.kind in OVERDUE_KINDS and i.state == "PO_TERMINIE" for i in items)


def _on_time(c: EvaluationCycle, scope: Scope) -> bool:
    item = next(i for i in deadlines_of(c, scope.rules_for(c), scope.calendar, scope.today) if i.kind == "OCENA")
    return item.done_on is not None and item.due is not None and item.done_on <= item.due


def _stage_days(cycles: Iterable[EvaluationCycle]) -> dict[str, float]:
    spans: dict[str, list[int]] = defaultdict(list)
    for c in cycles:
        for (start, status), (end, _) in zip(c.history, c.history[1:]):
            spans[status.value].append((end - start).days)
    return {k: round(sum(v) / len(v), 1) for k, v in spans.items() if v}


def progress(scope: Scope) -> Progress:
    people = scope.people()
    cycles = scope.in_scope()
    unit_of = {e.id: e.unit or NO_UNIT for e in people}
    units: dict[str, UnitProgress] = {}
    for e in people:
        units.setdefault(unit_of[e.id], UnitProgress(unit_of[e.id])).people += 1
    overdue_ids, drawn, on_time = [], 0, 0
    for c in cycles:
        u = units[unit_of[c.employee_id]]
        u.cycles += 1
        if c.evaluated_on is not None:
            drawn += 1
            u.drawn_up += 1
            if _on_time(c, scope):
                on_time += 1
                u.on_time += 1
        else:
            u.in_progress += 1
        if _overdue(c, scope):
            overdue_ids.append(c.id)
            u.overdue += 1
    with_cycle = {c.employee_id for c in cycles}
    return Progress(
        people=len(people), cycles=len(cycles), statuses=dict(Counter(c.status.value for c in cycles)),
        drawn_up=drawn, in_progress=sum(1 for c in cycles if c.evaluated_on is None),
        waiting_for_employee=sum(1 for c in cycles if c.status in WAITING_FOR_EMPLOYEE),
        overdue=len(overdue_ids), on_time=on_time,
        on_time_percent=round(100 * on_time / drawn, 1) if drawn else None,
        not_started=sum(1 for e in people if e.id not in with_cycle),
        stage_days=_stage_days(cycles), units=sorted(units.values(), key=lambda u: u.unit),
        overdue_cycles=overdue_ids,
    )


# ---------------------------------------------------------------- T18 outcomes

@dataclass(frozen=True)
class Group:
    """One aggregate; `hidden` = fewer than min_group people – the values are withheld."""
    key: str
    people: int
    average: float | None = None
    positive_percent: float | None = None
    hidden: bool = False


@dataclass(frozen=True)
class PersonOutcome:
    employee_id: str
    name: str
    unit: str
    level: str
    average: float
    outcome: str
    evaluated_on: date
    cycle_id: str


@dataclass
class Outcomes:
    min_group: int
    total: int  # people with a drawn-up evaluation in scope
    hidden: bool  # the whole scope is smaller than min_group
    levels: list[tuple[str, int]]  # in the order of the scale
    criteria: list[Group]
    units: list[Group]
    trend: list[Group]  # per year the evaluation was drawn up (every year, regardless of the filter)
    people: list[PersonOutcome]  # for the chosen bar; permissions already applied by the scope


def _finished(scope: Scope, by_year: bool = True) -> list[EvaluationCycle]:
    ids = {e.id for e in scope.people()}
    out = [c for c in scope.cycles if c.employee_id in ids and c.result is not None and c.evaluated_on is not None]
    if scope.year is not None and by_year:
        out = [c for c in out if c.evaluated_on.year == scope.year]
    return out


def _group(key: str, cycles: list[EvaluationCycle], min_group: int) -> Group:
    people = len({c.employee_id for c in cycles})
    if people < min_group:
        return Group(key, people, hidden=True)
    avg = sum((c.result.average for c in cycles), Fraction(0)) / len(cycles)
    pos = sum(1 for c in cycles if c.result.outcome is Outcome.POSITIVE)
    return Group(key, people, round(float(avg), 2), round(100 * pos / len(cycles), 1))


def outcomes(scope: Scope, current: RuleBook, min_group: int, level: str | None = None,
             outcome: str | None = None) -> Outcomes:
    cycles = _finished(scope)
    who = {e.id: e for e in scope.employees}
    people_n = len({c.employee_id for c in cycles})
    hidden = people_n < min_group
    counts = Counter(c.result.level for c in cycles)
    levels = [] if hidden else [(b.level, counts.get(b.level, 0)) for b in current.level_bands]

    by_criterion: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for c in cycles:
        for cid, pts in c.scores.items():
            by_criterion[cid].append((c.employee_id, pts))

    def number(cid: str) -> int:
        crit = current.criteria.get(cid)
        return crit.number if crit else 99

    criteria = []
    for cid in sorted(by_criterion, key=number):
        vals = by_criterion[cid]
        n = len({e for e, _ in vals})
        name = current.criterion_name(cid)
        criteria.append(Group(name, n, hidden=True) if n < min_group
                        else Group(name, n, round(sum(p for _, p in vals) / len(vals), 2)))

    by_unit: dict[str, list[EvaluationCycle]] = defaultdict(list)
    for c in cycles:
        by_unit[who[c.employee_id].unit or NO_UNIT].append(c)
    units = [_group(u, cs, min_group) for u, cs in sorted(by_unit.items())]

    by_year: dict[int, list[EvaluationCycle]] = defaultdict(list)
    for c in _finished(scope, by_year=False):
        by_year[c.evaluated_on.year].append(c)
    trend = [_group(str(y), cs, min_group) for y, cs in sorted(by_year.items())]

    chosen = [c for c in cycles if (level is None or c.result.level == level)
              and (outcome is None or c.result.outcome.value == outcome)]
    people = [PersonOutcome(c.employee_id, who[c.employee_id].full_name, who[c.employee_id].unit, c.result.level,
                            c.result.average_display, c.result.outcome.value, c.evaluated_on, c.id)
              for c in sorted(chosen, key=lambda c: (c.result.average, c.employee_id))]
    return Outcomes(min_group, people_n, hidden, levels, criteria, units, trend, people)
