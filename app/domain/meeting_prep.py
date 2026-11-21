"""UC4: facts for the evaluator's note before the review meeting. Data only – no AI-generated text."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .calendar import WorkingCalendar
from .cycle import STATUS_LABELS, EvaluationCycle, PreviousEvaluation
from .employee import Employee
from .rulebook import RuleBook


@dataclass(frozen=True)
class CriterionBrief:
    id: str
    name: str
    mandatory: bool
    indicators: tuple[str, ...]


@dataclass(frozen=True)
class MeetingPrep:
    cycle_id: str
    employee_name: str
    position: str
    unit: str
    evaluator_name: str
    sheet: str
    status: str  # Polish label
    criteria: tuple[CriterionBrief, ...]
    goals: tuple[str, ...]
    evaluation_deadline: date
    days_to_deadline: int
    previous_evaluation: PreviousEvaluation | None


def build_meeting_prep(
    cycle: EvaluationCycle,
    employee: Employee,
    evaluator: Employee | None,
    rules: RuleBook,
    cal: WorkingCalendar,
    today: date,
) -> MeetingPrep:
    mandatory = set(rules.mandatory(cycle.sheet))
    deadline = cycle.evaluation_deadline(rules, cal)
    return MeetingPrep(
        cycle_id=cycle.id,
        employee_name=employee.full_name,
        position=employee.position,
        unit=employee.unit,
        evaluator_name=evaluator.full_name if evaluator else cycle.evaluator_id,
        sheet=cycle.sheet,
        status=STATUS_LABELS[cycle.status],
        criteria=tuple(
            CriterionBrief(cid, rules.criteria[cid].name, cid in mandatory, rules.criteria[cid].indicators)
            for cid in cycle.criteria_ids(rules)
        ),
        goals=tuple(cycle.goals),
        evaluation_deadline=deadline,
        days_to_deadline=(deadline - today).days,
        previous_evaluation=cycle.previous_evaluation or employee.previous_evaluation,
    )
