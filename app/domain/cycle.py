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
from datetime import date, timedelta
from enum import Enum
from typing import Any, Mapping

from .calendar import WorkingCalendar
from .deadlines import (
    Absence,
    PositionChange,
    criteria_deadline,
    evaluation_deadline,
    delivery_day,
    objection_deadline,
    position_change,
    reevaluation_date,
)
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
    OBJECTION = "sprzeciw_zlozony"  # art. 83: the evaluated person objected; the reviewer (DG) decides


STATUS_LABELS = {
    Status.CYCLE_STARTED: "cykl rozpoczęty",
    Status.CRITERIA_SET: "kryteria wyznaczone",
    Status.CRITERIA_CONFIRMED: "kryteria potwierdzone przez ocenianego",
    Status.MEETING_HELD: "rozmowa oceniająca odbyta",
    Status.EVALUATION_DONE: "ocena sporządzona",
    Status.ACKNOWLEDGED: "ocena zapoznana",
    Status.OBJECTION: "sprzeciw złożony",
}

# step -> statuses it may start from, and the status it leads to
TRANSITIONS: dict[str, tuple[frozenset[Status], Status]] = {
    "set_criteria": (frozenset({Status.CYCLE_STARTED, Status.CRITERIA_SET}), Status.CRITERIA_SET),
    "confirm_criteria": (frozenset({Status.CRITERIA_SET}), Status.CRITERIA_CONFIRMED),
    "record_review_meeting": (frozenset({Status.CRITERIA_CONFIRMED}), Status.MEETING_HELD),
    "submit_evaluation": (frozenset({Status.MEETING_HELD}), Status.EVALUATION_DONE),
    "acknowledge": (frozenset({Status.EVALUATION_DONE}), Status.ACKNOWLEDGED),
    # paper flow: the evaluator records the signature date, or the refusal to sign (fikcja zapoznania)
    "record_signature": (frozenset({Status.EVALUATION_DONE}), Status.ACKNOWLEDGED),
    "refuse_acknowledgement": (frozenset({Status.EVALUATION_DONE}), Status.ACKNOWLEDGED),
    "file_objection": (frozenset({Status.ACKNOWLEDGED}), Status.OBJECTION),
    # not upheld -> ACKNOWLEDGED again; upheld -> back to the evaluator (MEETING_HELD) to change / redo it
    "decide_objection": (frozenset({Status.OBJECTION}), Status.ACKNOWLEDGED),
}

# upheld objection (art. 83 ust. 4): the director general orders one of the two, the evaluator carries it out
CHANGE = "ZMIANA_OCENY"  # parts of the evaluation replaced; it stays the same (acknowledged) evaluation
REDO = "PONOWNE_SPORZADZENIE"  # annulled and drawn up a second time (that one may be objected to again)
OBJECTION_OUTCOMES = {CHANGE: "zmiana oceny", REDO: "ponowne sporządzenie oceny"}

STEP_LABELS = {
    "set_criteria": "wyznaczenie kryteriów",
    "confirm_criteria": "potwierdzenie kryteriów przez ocenianego",
    "record_review_meeting": "zapisanie rozmowy oceniającej",
    "submit_evaluation": "dokonanie oceny",
    "acknowledge": "zapoznanie się z oceną",
    "record_signature": "zapisanie daty podpisu na papierze",
    "refuse_acknowledgement": "odmowa podpisu (fikcja zapoznania)",
    "file_objection": "złożenie sprzeciwu",
    "decide_objection": "rozpatrzenie sprzeciwu",
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
    "promotion_request": _EVALUATION_STAGE,
    "promotion_motivation": _EVALUATION_STAGE,
    "held_grade": _EVALUATION_STAGE,
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
    "promotion_request": "wniosek o kolejny stopień służbowy",
    "promotion_motivation": "umotywowanie wniosku o stopień",
    "held_grade": "posiadany stopień służbowy",
}


@dataclass(frozen=True)
class PreviousEvaluation:
    outcome: str | None  # "pozytywna" / "negatywna" / None (brak)
    level: str | None
    date: date | None  # drawn up in writing (sporządzenie) – starts the criteria deadline, § 7
    acknowledged: date | None = None  # employee acknowledged it (zapoznanie) – starts art. 81 ust. 9 / art. 83


@dataclass(frozen=True)
class SupersededEvaluation:
    """The evaluation as it was before an upheld objection: annulled (REDO) or replaced by its change (CHANGE)."""
    kind: str  # ZMIANA_OCENY | PONOWNE_SPORZADZENIE
    on: date  # the day of the decision
    evaluated_on: date | None
    result: EvaluationResult | None
    scores: dict[str, int]
    justification: str
    iprz_conclusions: str


@dataclass
class EvaluationCycle:
    id: str
    employee_id: str
    evaluator_id: str
    sheet: str
    start_date: date  # previous evaluation drawn up (sporządzenie) or start of permanent employment
    after_negative: bool
    criteria_deadline: date
    # after a negative evaluation: the day the employee acknowledged it (re-evaluation counts from here)
    negative_acknowledged_on: date | None = None
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
    position_changes: list[PositionChange] = field(default_factory=list)
    # deputy (zastępca) – who really acted on the evaluator's behalf, and who drew up the evaluation
    deputy_actions: list[tuple[date, str, str]] = field(default_factory=list)  # (day, deputy, step)
    drawn_up_by: str | None = None
    # objection (sprzeciw, art. 83) – the latest one; an evaluation drawn up again may be objected to again
    objection_filed_on: date | None = None
    objection_text: str = ""
    objection_decision: str | None = None  # UWZGLEDNIONY | NIEUWZGLEDNIONY
    objection_decided_on: date | None = None
    objection_decided_by: str | None = None
    objection_reason: str = ""
    # upheld: what the DG ordered (CHANGE / REDO), the scores it may not go below, and when it was carried out
    objection_outcome: str | None = None
    objection_baseline: dict[str, int] = field(default_factory=dict)
    objection_executed_on: date | None = None
    acknowledged_before_change: date | None = None  # CHANGE: the acknowledgement stays the original one
    superseded: list[SupersededEvaluation] = field(default_factory=list)
    history: list[tuple[date, Status]] = field(default_factory=list)
    # part III – request for the next grade (art. 89 ust. 1; civil servants only, positive evaluation only)
    promotion_request: bool = False
    promotion_motivation: str = ""
    held_grade: int | None = None  # posiadany stopień (default: the HR data)
    # change of the evaluator during the period (§ 9 ust. 3): (day, previous evaluator, new evaluator)
    evaluator_changes: list[tuple[date, str, str]] = field(default_factory=list)
    # sheet choice (§ 3): what the system suggested, why, and HR's changes (day, by, old, new, reason)
    sheet_suggested: str | None = None
    sheet_reason: str = ""
    sheet_warning: str | None = None
    sheet_changes: list[tuple[date, str, str, str, str]] = field(default_factory=list)
    # paper flow (use case "Pani X"): the printed form and the day the employee signed it (= acknowledgement)
    printed_on: date | None = None
    signed_on: date | None = None
    acknowledgement_refused: bool = False  # fikcja zapoznania: refused to sign, the evaluator's note below
    refusal_note: str = ""
    # version of the regulation the cycle follows (app/infrastructure/regulations.py; None = the current one)
    rules_version: int | None = None
    imported: bool = False  # legacy evaluation imported from a PDF (app/application/legacy_import.py)

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
        negative_acknowledged_on: date | None = None,
    ) -> EvaluationCycle:
        """`start_date` = day the previous evaluation was drawn up (or hiring): criteria deadline, § 7.
        After a negative one, `negative_acknowledged_on` (default: `previous_evaluation.acknowledged`)
        starts the re-evaluation deadline, art. 81 ust. 9."""
        rules.mandatory(sheet)  # validates the sheet
        if after_negative and negative_acknowledged_on is None and previous_evaluation is not None:
            negative_acknowledged_on = previous_evaluation.acknowledged
        if negative_acknowledged_on is not None and negative_acknowledged_on < start_date:
            raise ValidationError([
                f"Data zapoznania z oceną ({negative_acknowledged_on}) nie może być wcześniejsza "
                f"niż data jej sporządzenia ({start_date})."
            ])
        cycle = cls(
            id=cycle_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            sheet=sheet,
            start_date=start_date,
            after_negative=after_negative,
            criteria_deadline=criteria_deadline(start_date, rules, cal, after_negative),
            negative_acknowledged_on=negative_acknowledged_on if after_negative else None,
            previous_evaluation=previous_evaluation,
        )
        cycle.history.append((today, Status.CYCLE_STARTED))
        return cycle

    # ---- derived ---------------------------------------------------------------------------------
    def criteria_ids(self, rules: RuleBook) -> list[str]:
        return list(rules.mandatory(self.sheet)) + list(self.additional_criteria)

    def evaluation_deadline(self, rules: RuleBook, cal: WorkingCalendar) -> date:
        """24 months (+ long absences), or – after a negative evaluation – the re-evaluation date
        (art. 81 ust. 9, counted from the day the negative evaluation was acknowledged; if that day is
        unknown, from the day it was drawn up – § 12 ust. 1 requires acknowledgement "niezwłocznie").
        An explicit change (evaluator's decision or a change of position) wins."""
        if self.deadline_override is not None:
            return cal.next_working_day(self.deadline_override)
        if self.after_negative:
            return reevaluation_date(self.negative_acknowledged_on or self.start_date, rules, cal)
        return evaluation_deadline(self.start_date, rules, cal, self.absences)

    def objection_start(self, absences: list[Absence] | None = None,
                        cal: WorkingCalendar | None = None) -> date | None:
        """The day the 7 days run from: the acknowledgement, or – when the evaluated person was on a justified
        absence that day – the day they came back to work (absences: the cycle's own + the employee's later ones)."""
        if self.acknowledged_on is None:
            return None
        return delivery_day(self.acknowledged_on, [*self.absences, *(absences or [])], cal)

    def objection_deadline(self, rules: RuleBook, cal: WorkingCalendar,
                           absences: list[Absence] | None = None) -> date | None:
        """Art. 83 ust. 1: last day to object to the evaluation; None until the evaluation is acknowledged."""
        start = self.objection_start(absences, cal)
        return objection_deadline(start, rules, cal) if start else None

    def objection_review_deadline(self, rules: RuleBook, cal: WorkingCalendar) -> date | None:
        """Art. 83 ust. 3: the objection is decided within 14 days of filing it."""
        if self.objection_filed_on is None:
            return None
        return cal.next_working_day(self.objection_filed_on + timedelta(days=rules.objection_review_days))

    def labour_court_deadline(self, rules: RuleBook, cal: WorkingCalendar) -> date | None:
        """Art. 83 ust. 5: 14 days for an appeal to the labour court after the objection was not upheld."""
        if self.objection_decision != "NIEUWZGLEDNIONY" or self.objection_decided_on is None:
            return None
        return cal.next_working_day(self.objection_decided_on + timedelta(days=rules.labour_court_days))

    def next_evaluation_due(self, rules: RuleBook, cal: WorkingCalendar | None = None) -> date | None:
        """After an acknowledged NEGATIVE evaluation: when the re-evaluation is due (art. 81 ust. 9)."""
        if self.acknowledged_on and self.is_negative:
            return reevaluation_date(self.acknowledged_on, rules, cal)
        return None

    @property
    def objection_order_pending(self) -> bool:
        """An upheld objection is waiting for the evaluator: change the evaluation or draw it up again."""
        return self.objection_outcome is not None and self.objection_executed_on is None

    def objection_lowered(self, scores: Mapping[str, int]) -> list[str]:
        """Criteria scored lower than before the upheld objection (empty when no order is pending)."""
        if not self.objection_order_pending:
            return []
        return [cid for cid, old in self.objection_baseline.items() if scores.get(cid) is not None and scores[cid] < old]

    def objection_problems(self, scores: Mapping[str, int], justification: str, iprz: str) -> list[str]:
        """After an upheld objection the evaluation may not get worse (Poradnik KPRM to art. 83 ust. 4: upholding
        means agreeing with the evaluated person), and a change must replace something."""
        if not self.objection_order_pending:
            return []
        problems = [f"Ocena cząstkowa nie może być niższa niż przed sprzeciwem ({self.objection_baseline[cid]} → "
                    f"{scores[cid]}) – uwzględnienie sprzeciwu nie może pogorszyć oceny."
                    for cid in self.objection_lowered(scores)]
        before = self.superseded[-1] if self.superseded else None
        if (self.objection_outcome == CHANGE and before and dict(scores) == before.scores
                and justification.strip() == before.justification.strip()
                and iprz.strip() == before.iprz_conclusions.strip()):
            problems.append("Zmiana oceny zastępuje jej fragmenty (np. oceny cząstkowe, uzasadnienie) nowymi – "
                            "nic nie zostało zmienione.")
        return problems

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
        if problems := self.objection_problems(merged["scores"], merged["justification"], merged["iprz_conclusions"]):
            raise ValidationError(problems)
        self.edit(actor_id, rules, **changes)
        self.result = result
        if self.objection_order_pending:
            self.objection_executed_on = today
            if self.objection_outcome == CHANGE:
                # the changed evaluation is the same evaluation: drawn up and acknowledged when it first was
                self.acknowledged_on = self.acknowledged_before_change
                self._move(Status.ACKNOWLEDGED, today)
                return result
        self.evaluated_on = today
        self._move(target, today)
        return result

    def acknowledge(self, actor_id: str, today: date) -> None:
        target = self._require_step("acknowledge")
        self._require_actor(actor_id, self.employee_id, "oceniany")
        self.acknowledged_on = today
        self._move(target, today)

    # ---- paper flow (§ 12: the form is printed, the employee signs it) ------------------------------
    def record_paper(self, actor_id: str, today: date, printed_on: date | None, signed_on: date | None) -> None:
        """The evaluator enters the print date and/or the signature date. The signature is the acknowledgement:
        the objection period runs from it. Rules: no date from the future, drawn up <= printed <= signed."""
        self._require_actor(actor_id, self.evaluator_id, "oceniający")
        if self.status not in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION) or not self.evaluated_on:
            raise InvalidTransition("Daty wydruku i podpisu wpisuje się po sporządzeniu oceny.")
        printed = printed_on or self.printed_on
        problems = []
        for label, d in (("wydruku", printed_on), ("podpisu", signed_on)):
            if d is not None and d > today:
                problems.append(f"Data {label} ({d:%d.%m.%Y}) nie może być z przyszłości.")
        if printed is not None and printed < self.evaluated_on:
            problems.append(f"Data wydruku ({printed:%d.%m.%Y}) nie może być wcześniejsza niż data sporządzenia "
                            f"oceny ({self.evaluated_on:%d.%m.%Y}).")
        if signed_on is not None:
            if printed is None:
                problems.append("Najpierw wpisz datę wydruku arkusza – podpis jest na wydruku.")
            elif signed_on < printed:
                problems.append(f"Data podpisu ({signed_on:%d.%m.%Y}) nie może być wcześniejsza niż data wydruku "
                                f"({printed:%d.%m.%Y}).")
            if self.status is not Status.EVALUATION_DONE:
                problems.append("Zapoznanie z oceną zostało już odnotowane – daty podpisu nie można zmienić.")
        if problems:
            raise ValidationError(problems)
        self.printed_on = printed
        if signed_on is not None:
            target = self._require_step("record_signature")
            self.signed_on = self.acknowledged_on = signed_on
            self._move(target, today)

    def refuse_acknowledgement(self, actor_id: str, today: date, note: str, delivered_on: date | None = None) -> None:
        """Fikcja zapoznania: the evaluated person was shown the evaluation and refused to sign it. The evaluator
        notes it on the form with the date; from that day the evaluation counts as acknowledged."""
        target = self._require_step("refuse_acknowledgement")
        self._require_actor(actor_id, self.evaluator_id, "oceniający")
        day = delivered_on or today
        problems = []
        if not note.strip():
            problems.append("Wpisz adnotację o odmowie podpisu (kto, kiedy, w czyjej obecności).")
        if day > today:
            problems.append("Data odmowy podpisu nie może być z przyszłości.")
        if self.evaluated_on and day < self.evaluated_on:
            problems.append("Data odmowy podpisu nie może być wcześniejsza niż data sporządzenia oceny.")
        if problems:
            raise ValidationError(problems)
        self.acknowledgement_refused, self.refusal_note = True, note.strip()
        self.acknowledged_on = day
        self._move(target, today)

    # ---- sheet (§ 3) --------------------------------------------------------------------------------
    def change_sheet(self, sheet: str, reason: str, by: str, today: date, rules: RuleBook) -> None:
        """HR changes the sheet with a reason – only before the evaluator approves the criteria."""
        if self.status is not Status.CYCLE_STARTED:
            raise InvalidTransition("Arkusz można zmienić tylko przed zatwierdzeniem kryteriów oceny.")
        if not reason.strip():
            raise ValidationError(["Podaj uzasadnienie zmiany arkusza."])
        mandatory = set(rules.mandatory(sheet))  # validates the sheet
        if sheet == self.sheet:
            return
        self.sheet_changes.append((today, by, self.sheet, sheet, reason.strip()))
        self.sheet = sheet
        self.additional_criteria = [c for c in self.additional_criteria if c not in mandatory]

    # ---- objection (art. 83) ----------------------------------------------------------------------
    def file_objection(self, actor_id: str, today: date, text: str, rules: RuleBook, cal: WorkingCalendar,
                       absences: list[Absence] | None = None) -> None:
        """The evaluated person objects within 7 days of acknowledging the evaluation (art. 83 ust. 1)."""
        target = self._require_step("file_objection")
        self._require_actor(actor_id, self.employee_id, "oceniany")
        if self.objection_filed_on and self.acknowledged_on and self.objection_filed_on >= self.acknowledged_on:
            raise InvalidTransition("Sprzeciw od tej oceny został już złożony i rozpatrzony.")
        deadline = self.objection_deadline(rules, cal, absences)
        if deadline is None or today > deadline:
            raise InvalidTransition(f"Termin na sprzeciw minął {deadline:%d.%m.%Y} (7 dni od zapoznania się z oceną, "
                                    "art. 83 ust. 1 ustawy)." if deadline else "Ocena nie została jeszcze zapoznana.")
        if not text.strip():
            raise ValidationError(["Opisz, z czym się nie zgadzasz – treść sprzeciwu jest wymagana."])
        self.objection_filed_on, self.objection_text = today, text.strip()
        self.objection_decision = self.objection_decided_on = self.objection_decided_by = None
        self.objection_reason = ""
        self._move(target, today)

    def decide_objection(self, reviewer_id: str, today: date, upheld: bool, reason: str,
                         outcome: str | None = None) -> None:
        """The reviewer (director general) decides (art. 83 ust. 3–4). Not upheld: the evaluation stays and the
        person may go to the labour court. Upheld: the DG orders either
        - CHANGE (zmiana oceny): the evaluator replaces parts of it; it stays the evaluation drawn up and
          acknowledged before (no new acknowledgement, no new objection), or
        - REDO (ponowne sporządzenie): the evaluation is annulled and the process goes back to "rozmowa oceniająca
          i dokonanie oceny"; the one drawn up a second time is acknowledged and may be objected to again.
        Both are carried out by the evaluator (direct supervisor, art. 81 ust. 1 – Poradnik KPRM)."""
        self._require_step("decide_objection")
        problems = []
        if not reason.strip():
            problems.append("Uzasadnij rozstrzygnięcie sprzeciwu.")
        if upheld and outcome not in OBJECTION_OUTCOMES:
            problems.append("Wybierz, co wynika z uwzględnienia sprzeciwu: zmiana oceny albo ponowne sporządzenie "
                            "oceny (art. 83 ust. 4).")
        if problems:
            raise ValidationError(problems)
        self.objection_decision = "UWZGLEDNIONY" if upheld else "NIEUWZGLEDNIONY"
        self.objection_decided_on, self.objection_decided_by, self.objection_reason = today, reviewer_id, reason.strip()
        self.objection_outcome = outcome if upheld else None
        self.objection_executed_on = None
        if not upheld:
            self._move(Status.ACKNOWLEDGED, today)
            return
        self.objection_baseline = dict(self.scores)
        self.superseded.append(SupersededEvaluation(outcome, today, self.evaluated_on, self.result, dict(self.scores),
                                                    self.justification, self.iprz_conclusions))
        self.acknowledged_before_change = self.acknowledged_on if outcome == CHANGE else None
        self.acknowledged_on = None
        self.result = None  # recomputed live while the evaluator works on it, fixed again on submitting
        if outcome == REDO:  # annulled: drawn up and acknowledged anew
            self.evaluated_on = self.drawn_up_by = None
            self.printed_on = self.signed_on = None
            self.acknowledgement_refused, self.refusal_note = False, ""
        self._move(Status.MEETING_HELD, today)  # part II editable again

    # ---- absences (UC3/UC8) ----------------------------------------------------------------------
    def register_absence(self, absence: Absence) -> None:
        """Justified absences extend the evaluation deadline (art. 81 ust. 7) until the evaluation is made."""
        if self.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED):
            raise InvalidTransition("Ocena została już sporządzona – nieobecność nie wpływa na jej termin.")
        self.absences.append(absence)

    # ---- change of position with a significant change of duties (art. 81 ust. 6, § 9) ------------
    def register_position_change(self, change: date, rules: RuleBook, cal: WorkingCalendar, today: date) -> PositionChange:
        """Within 6 months of the reference date: criteria and the opening conversation are done again
        (back to "cykl rozpoczęty", new criteria deadline, evaluation deadline unchanged).
        Later: an evaluation is due between 7 days before and 30 days after the change (deadline override)."""
        if self.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED):
            raise InvalidTransition("Ocena została już sporządzona – zmiana stanowiska dotyczy kolejnego cyklu.")
        first_evaluation = self.previous_evaluation is None
        reference = (self.criteria_set_on or self.start_date) if first_evaluation else self.start_date
        outcome = position_change(change, reference, rules, cal)
        if outcome.kind == "NOWE_KRYTERIA":
            if self.status is Status.MEETING_HELD:
                raise InvalidTransition("Rozmowa oceniająca już się odbyła – nie można ponownie wyznaczyć kryteriów.")
            self.criteria_deadline = outcome.deadline
            self.criteria_confirmed_on = None
            if self.status is not Status.CYCLE_STARTED:
                self._move(Status.CYCLE_STARTED, today)
        else:
            self.deadline_override = outcome.deadline
        self.position_changes.append(outcome)
        return outcome

    def change_deadline(self, actor_id: str, reason: str, new_deadline: date | None, justification: str,
                        today: date, rules: RuleBook, cal: WorkingCalendar) -> tuple[date, date]:
        """Art. 81 ust. 8: the evaluator moves the evaluation deadline (-> (old, new)). Before the evaluation is
        drawn up only; the evaluated person is informed in writing (§ 8, letter: backend/notice_pdf.py)."""
        from .deadline_change import check_deadline_change

        self._require_actor(actor_id, self.evaluator_id, "oceniający (art. 81 ust. 8)")
        if self.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION):
            raise InvalidTransition("Ocena została już sporządzona – nie można zmienić jej terminu.")
        old = self.evaluation_deadline(rules, cal)
        new = check_deadline_change(reason, self.start_date, old, new_deadline, today, rules, cal, justification)
        self.deadline_override = new
        return old, new

    def evaluator_since(self) -> date:
        """Since when the current evaluator evaluates this person in this cycle."""
        return self.evaluator_changes[-1][0] if self.evaluator_changes else self.start_date

    def reassign_evaluator(self, new_evaluator: str, on: date) -> None:
        """§ 9 ust. 3: the new evaluator takes over the running cycle – the criteria chosen before and the
        deadline stay. Not after the evaluation has been drawn up (that one belongs to whoever drew it up)."""
        if self.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION):
            raise InvalidTransition("Ocena została już sporządzona – zmiana oceniającego dotyczy kolejnego cyklu.")
        if new_evaluator == self.employee_id:
            raise ValidationError(["Pracownik nie może oceniać sam siebie."])
        if new_evaluator == self.evaluator_id:
            raise ValidationError(["To jest już oceniający tego pracownika."])
        self.evaluator_changes.append((on, self.evaluator_id, new_evaluator))
        self.evaluator_id = new_evaluator

    @property
    def is_negative(self) -> bool:
        return self.result is not None and self.result.outcome is Outcome.NEGATIVE

