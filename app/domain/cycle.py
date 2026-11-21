"""Evaluation cycle aggregate: a state machine with field locks (KPRM sheet field schemas A/B/C).

start_cycle -> set_criteria -> confirm_criteria (evaluated person) -> record_review_meeting
-> submit_evaluation -> acknowledge (evaluated person)

Field locks follow wiedza/schemat-pol-arkusz-*.md: additional criteria and the deadline are editable until
the evaluated person confirms them; the review-meeting date and period only at the review-meeting stage;
scores, justification, IPRZ conclusions and previous-evaluation data from the meeting until submission.
After that everything is locked (admin error correction is out of scope).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Mapping

from .calendar import WorkingCalendar
from .deadlines import Absence, criteria_deadline, evaluation_deadline
from .errors import FieldLocked, InvalidTransition, NotAuthorized, ValidationError
from .rulebook import RuleBook
from .scoring import EvaluationResult, Outcome, validate_additional_criteria, validate_evaluation


class Status(str, Enum):
    """Values equal reguly.json['statusy_procesu'] (the happy-path subset)."""

    CYCLE_STARTED = "cykl_rozpoczety"
    CRITERIA_SET = "kryteria_wyznaczone"
    CRITERIA_CONFIRMED = "kryteria_potwierdzone_przez_ocenianego"
    MEETING_HELD = "rozmowa_oceniajaca_odbyta"
    EVALUATION_DONE = "ocena_sporzadzona"
    ACKNOWLEDGED = "ocena_zapoznana"


STATUS_LABELS = {
    Status.CYCLE_STARTED: "cykl rozpoczęty",
    Status.CRITERIA_SET: "kryteria wyznaczone",
    Status.CRITERIA_CONFIRMED: "kryteria potwierdzone przez ocenianego",
    Status.MEETING_HELD: "rozmowa oceniająca odbyta",
    Status.EVALUATION_DONE: "ocena sporządzona",
    Status.ACKNOWLEDGED: "ocena zapoznana",
}

# step -> statuses it may start from, and the status it leads to
TRANSITIONS: dict[str, tuple[frozenset[Status], Status]] = {
    "set_criteria": (frozenset({Status.CYCLE_STARTED, Status.CRITERIA_SET}), Status.CRITERIA_SET),
    "confirm_criteria": (frozenset({Status.CRITERIA_SET}), Status.CRITERIA_CONFIRMED),
    "record_review_meeting": (frozenset({Status.CRITERIA_CONFIRMED}), Status.MEETING_HELD),
    "submit_evaluation": (frozenset({Status.MEETING_HELD}), Status.EVALUATION_DONE),
    "acknowledge": (frozenset({Status.EVALUATION_DONE}), Status.ACKNOWLEDGED),
}

STEP_LABELS = {
    "set_criteria": "wyznaczenie kryteriów",
    "confirm_criteria": "potwierdzenie kryteriów przez ocenianego",
    "record_review_meeting": "zapisanie rozmowy oceniającej",
    "submit_evaluation": "dokonanie oceny",
    "acknowledge": "zapoznanie się z oceną",
}

_CRITERIA_STAGE = frozenset({Status.CYCLE_STARTED, Status.CRITERIA_SET})
_MEETING_STAGE = frozenset({Status.CRITERIA_CONFIRMED})
_EVALUATION_STAGE = frozenset({Status.MEETING_HELD})

# editable field -> statuses in which the evaluator may change it
EDITABLE_IN: dict[str, frozenset[Status]] = {
    "additional_criteria": _CRITERIA_STAGE,
    "deadline_override": _CRITERIA_STAGE,
    "goals": _CRITERIA_STAGE,
    "meeting_date": _MEETING_STAGE,
    "period_from": _MEETING_STAGE,
    "period_to": _MEETING_STAGE,
    "scores": _EVALUATION_STAGE,
    "justification": _EVALUATION_STAGE,
    "iprz_conclusions": _EVALUATION_STAGE,
    "previous_evaluation": _EVALUATION_STAGE,
}

FIELD_LABELS = {
    "additional_criteria": "kryteria dodatkowe",
    "deadline_override": "termin sporządzenia oceny",
    "goals": "cele / oczekiwania",
    "meeting_date": "data rozmowy oceniającej",
    "period_from": "okres oceny (od)",
    "period_to": "okres oceny (do)",
    "scores": "oceny cząstkowe",
    "justification": "uzasadnienie oceny",
    "iprz_conclusions": "wnioski IPRZ",
    "previous_evaluation": "dane poprzedniej oceny",
}


@dataclass(frozen=True)
class PreviousEvaluation:
    outcome: str | None  # "pozytywna" / "negatywna" / None (brak)
    level: str | None
    date: date | None


@dataclass
class EvaluationCycle:
    id: str
    employee_id: str
    evaluator_id: str
    sheet: str
    start_date: date  # previous evaluation or start of permanent employment
    after_negative: bool
    criteria_deadline: date
    status: Status = Status.CYCLE_STARTED
    additional_criteria: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    deadline_override: date | None = None
    absences: list[Absence] = field(default_factory=list)
    criteria_set_on: date | None = None
    criteria_confirmed_on: date | None = None
    meeting_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    previous_evaluation: PreviousEvaluation | None = None
    scores: dict[str, int] = field(default_factory=dict)
    justification: str = ""
    iprz_conclusions: str = ""
    result: EvaluationResult | None = None
    evaluated_on: date | None = None
    acknowledged_on: date | None = None
    history: list[tuple[date, Status]] = field(default_factory=list)

    # ---- creation -------------------------------------------------------------------------------
    @classmethod
    def start(
        cls,
        cycle_id: str,
        employee_id: str,
        evaluator_id: str,
        sheet: str,
        start_date: date,
        today: date,
        rules: RuleBook,
        cal: WorkingCalendar,
        after_negative: bool = False,
        previous_evaluation: PreviousEvaluation | None = None,
    ) -> EvaluationCycle:
        rules.mandatory(sheet)  # validates the sheet
        cycle = cls(
            id=cycle_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            sheet=sheet,
            start_date=start_date,
            after_negative=after_negative,
            criteria_deadline=criteria_deadline(start_date, rules, cal, after_negative),
            previous_evaluation=previous_evaluation,
        )
        cycle.history.append((today, Status.CYCLE_STARTED))
        return cycle

    # ---- derived ---------------------------------------------------------------------------------
    def criteria_ids(self, rules: RuleBook) -> list[str]:
        return list(rules.mandatory(self.sheet)) + list(self.additional_criteria)

    def evaluation_deadline(self, rules: RuleBook, cal: WorkingCalendar) -> date:
        if self.deadline_override is not None:
            return cal.next_working_day(self.deadline_override)
        return evaluation_deadline(self.start_date, rules, cal, self.absences)

    def can(self, step: str) -> bool:
        return self.status in TRANSITIONS[step][0]

    def is_editable(self, field_name: str) -> bool:
        return self.status in EDITABLE_IN[field_name]

    # ---- guards ----------------------------------------------------------------------------------
    def _require_step(self, step: str) -> Status:
        allowed, target = TRANSITIONS[step]
        if self.status not in allowed:
            raise InvalidTransition(
                f"Nie można wykonać kroku „{STEP_LABELS[step]}” – ocena jest w statusie "
                f"„{STATUS_LABELS[self.status]}”."
            )
        return target

    def _require_editable(self, *fields: str) -> None:
        for f in fields:
            if not self.is_editable(f):
                raise FieldLocked(
                    f"Pole „{FIELD_LABELS[f]}” jest zablokowane do edycji w statusie „{STATUS_LABELS[self.status]}”."
                )

    def _require_actor(self, actor_id: str, expected: str, role: str) -> None:
        if actor_id != expected:
            raise NotAuthorized(f"Ten krok może wykonać tylko {role}.")

    def _move(self, target: Status, today: date) -> None:
        self.status = target
        self.history.append((today, target))

    # ---- editing ---------------------------------------------------------------------------------
    def edit(self, actor_id: str, rules: RuleBook, **changes: Any) -> None:
        """Evaluator edits draft fields; every field must be editable in the current status."""
        self._require_actor(actor_id, self.evaluator_id, "oceniający")
        unknown = [f for f in changes if f not in EDITABLE_IN]
        if unknown:
            raise ValidationError([f"Nieznane pole: {', '.join(unknown)}."])
        self._require_editable(*changes)
        if "additional_criteria" in changes:
            additional = list(changes["additional_criteria"])
            if problems := validate_additional_criteria(self.sheet, additional, rules):
                raise ValidationError(problems)
            changes["additional_criteria"] = additional
        for name, value in changes.items():
            setattr(self, name, value)

    # ---- steps -----------------------------------------------------------------------------------
    def set_criteria(
        self,
        actor_id: str,
        today: date,
        rules: RuleBook,
        additional_criteria: list[str] | None = None,
        goals: list[str] | None = None,
        deadline_override: date | None = None,
    ) -> None:
        target = self._require_step("set_criteria")
        self.edit(
            actor_id,
            rules,
            additional_criteria=list(additional_criteria or []),
            goals=[g.strip() for g in goals or [] if g and g.strip()],
            deadline_override=deadline_override,
        )
        self.criteria_set_on = today
        self._move(target, today)

    def confirm_criteria(self, actor_id: str, today: date) -> None:
        target = self._require_step("confirm_criteria")
        self._require_actor(actor_id, self.employee_id, "oceniany")
        self.criteria_confirmed_on = today
        self._move(target, today)

    def record_review_meeting(
        self,
        actor_id: str,
        today: date,
        rules: RuleBook,
        meeting_date: date,
        period_from: date | None = None,
        period_to: date | None = None,
    ) -> None:
        target = self._require_step("record_review_meeting")
        self._require_actor(actor_id, self.evaluator_id, "oceniający")
        period_from = period_from or self.criteria_set_on or self.start_date
        period_to = period_to or meeting_date
        problems = []
        if meeting_date > today:
            problems.append("Data rozmowy oceniającej nie może być z przyszłości.")
        if period_to < period_from:
            problems.append("Okres oceny: data „do” jest wcześniejsza niż data „od”.")
        if problems:
            raise ValidationError(problems)
        self.edit(actor_id, rules, meeting_date=meeting_date, period_from=period_from, period_to=period_to)
        self._move(target, today)

    def submit_evaluation(
        self,
        actor_id: str,
        today: date,
        rules: RuleBook,
        scores: Mapping[str, int] | None = None,
        justification: str | None = None,
        iprz_conclusions: str | None = None,
    ) -> EvaluationResult:
        target = self._require_step("submit_evaluation")
        changes: dict[str, Any] = {}
        if scores is not None:
            changes["scores"] = dict(scores)
        if justification is not None:
            changes["justification"] = justification
        if iprz_conclusions is not None:
            changes["iprz_conclusions"] = iprz_conclusions
        self._require_actor(actor_id, self.evaluator_id, "oceniający")
        self._require_editable(*changes)
        merged = {"scores": self.scores, "justification": self.justification,
                  "iprz_conclusions": self.iprz_conclusions, **changes}
        result = validate_evaluation(
            self.criteria_ids(rules), merged["scores"], merged["justification"], merged["iprz_conclusions"], rules
        )
        self.edit(actor_id, rules, **changes)
        self.result = result
        self.evaluated_on = today
        self._move(target, today)
        return result

    def acknowledge(self, actor_id: str, today: date) -> None:
        target = self._require_step("acknowledge")
        self._require_actor(actor_id, self.employee_id, "oceniany")
        self.acknowledged_on = today
        self._move(target, today)

    # ---- absences (UC3/UC8) ----------------------------------------------------------------------
    def register_absence(self, absence: Absence) -> None:
        """Justified absences extend the evaluation deadline (art. 81 ust. 7) until the evaluation is made."""
        if self.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED):
            raise InvalidTransition("Ocena została już sporządzona – nieobecność nie wpływa na jej termin.")
        self.absences.append(absence)

    @property
    def is_negative(self) -> bool:
        return self.result is not None and self.result.outcome is Outcome.NEGATIVE

