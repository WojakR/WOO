"""Use cases UC1–UC5 of the periodic evaluation (no UI, no LLM).

UC1 start_cycle + set_criteria, UC2 confirm_criteria, UC3 reminders / register_absence,
UC4 meeting_prep, UC5 record_review_meeting + submit_evaluation, then acknowledge.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

from app.domain.calendar import WorkingCalendar
from app.domain.cycle import EvaluationCycle, PreviousEvaluation, Status
from app.domain.deadlines import Absence, PositionChange
from app.domain.employee import Employee
from app.domain.errors import InvalidTransition, NotFound, ValidationError
from app.domain.meeting_prep import MeetingPrep, build_meeting_prep
from app.domain.reminder_schedule import ReminderSchedule, Stage, at_time, reminder_dates
from app.domain.rulebook import RuleBook
from app.domain.scoring import EvaluationResult, Outcome

from .ports import Clock, CycleRepository, EmployeeDirectory


@dataclass(frozen=True)
class Reminder:
    cycle_id: str
    employee_id: str
    recipient_id: str
    kind: str  # "criteria" | "evaluation" | "acknowledgement" | "objection" | "reevaluation"
    due: date
    days_left: int  # negative = overdue
    message: str  # Polish, shown to the user


@dataclass(frozen=True)
class PlannedReminder:
    """One reminder from the configurable schedule (office default or the recipient's own)."""
    key: str  # stable id: cycle, stage, recipient, day
    cycle_id: str
    employee_id: str
    recipient_id: str
    stage: Stage
    when: datetime
    deadline: date
    message: str


ACKNOWLEDGEMENT_WINDOW_DAYS = 30  # how long to keep reminding about acknowledging ("niezwłocznie", § 12 ust. 1)


class EvaluationService:
    def __init__(
        self,
        rules: RuleBook,
        cycles: CycleRepository,
        employees: EmployeeDirectory,
        clock: Clock,
        calendar: WorkingCalendar | None = None,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
        deputies: Callable[[str, date], set[str]] = lambda evaluator_id, day: set(),
    ):
        self.rules = rules
        self.cycles = cycles
        self.employees = employees
        self.clock = clock
        self.calendar = calendar or WorkingCalendar()
        self._new_id = new_id
        self.deputies = deputies  # evaluator id, day -> ids of people standing in for them that day

    def _as_evaluator(self, cycle_id: str, actor_id: str, step: str,
                      action: Callable[[EvaluationCycle, str], Any]) -> Any:
        """Run an evaluator's step. An active deputy acts on the evaluator's behalf (the domain still checks
        "only the evaluator"); the cycle records who really acted, and who drew up the evaluation."""
        today = self.clock.today()

        def run(c: EvaluationCycle) -> Any:
            acting = actor_id
            if (actor_id not in (c.evaluator_id, c.employee_id)
                    and actor_id in self.deputies(c.evaluator_id, today)):
                acting = c.evaluator_id
                c.deputy_actions.append((today, actor_id, step))
            out = action(c, acting)
            if step == "submit_evaluation":
                c.drawn_up_by = actor_id
            return out

        return self._apply(cycle_id, run)

    # ---- helpers ---------------------------------------------------------------------------------
    def _employee(self, employee_id: str) -> Employee:
        emp = self.employees.get(employee_id)
        if emp is None:
            raise NotFound(f"Nie znaleziono pracownika „{employee_id}”.")
        return emp

    def _cycle(self, cycle_id: str) -> EvaluationCycle:
        cycle = self.cycles.get(cycle_id)
        if cycle is None:
            raise NotFound(f"Nie znaleziono oceny „{cycle_id}”.")
        return cycle

    def _apply(self, cycle_id: str, action: Callable[[EvaluationCycle], Any]) -> Any:
        cycle = self._cycle(cycle_id)
        out = action(cycle)
        self.cycles.save(cycle)
        return out

    def evaluation_deadline(self, cycle_id: str) -> date:
        return self._cycle(cycle_id).evaluation_deadline(self.rules, self.calendar)

    # ---- UC1 -------------------------------------------------------------------------------------
    def start_cycle(
        self,
        employee_id: str,
        start_date: date | None = None,
        after_negative: bool | None = None,
        negative_acknowledged_on: date | None = None,
        previous_evaluation: PreviousEvaluation | None = None,
    ) -> EvaluationCycle:
        """Open a cycle. Defaults: start = day the previous evaluation was drawn up (else today, i.e. hiring);
        `after_negative` from the previous outcome (shortens the criteria deadline, § 7 pkt 2);
        `negative_acknowledged_on` from the previous evaluation (starts the re-evaluation, art. 81 ust. 9);
        `previous_evaluation` overrides the directory's data (the cycle that has just ended)."""
        emp = self._employee(employee_id)
        if not emp.evaluator_id:
            raise ValidationError([f"Pracownik {emp.full_name} nie ma przypisanego oceniającego."])
        if self.cycles.find_open_for(employee_id) is not None:
            raise InvalidTransition(f"{emp.full_name} ma już otwarty cykl oceny.")
        prev = previous_evaluation or emp.previous_evaluation
        today = self.clock.today()
        if start_date is None:
            start_date = prev.date if prev and prev.date else today
        if after_negative is None:
            after_negative = bool(prev and prev.outcome == "negatywna")
        cycle = EvaluationCycle.start(
            self._new_id(), emp.id, emp.evaluator_id, emp.sheet, start_date, today,
            self.rules, self.calendar, after_negative, prev, negative_acknowledged_on,
        )
        self.cycles.save(cycle)
        return cycle

    def set_criteria(
        self,
        cycle_id: str,
        actor_id: str,
        additional_criteria: list[str] | None = None,
        goals: list[str] | None = None,
        deadline_override: date | None = None,
    ) -> EvaluationCycle:
        today = self.clock.today()
        self._as_evaluator(cycle_id, actor_id, "set_criteria", lambda c, a: c.set_criteria(
            a, today, self.rules, additional_criteria, goals, deadline_override))
        return self._cycle(cycle_id)

    def edit(self, cycle_id: str, actor_id: str, **changes: Any) -> EvaluationCycle:
        """Draft edits (e.g. scores during the meeting); locked fields raise FieldLocked."""
        self._as_evaluator(cycle_id, actor_id, "edit", lambda c, a: c.edit(a, self.rules, **changes))
        return self._cycle(cycle_id)

    # ---- UC2 -------------------------------------------------------------------------------------
    def confirm_criteria(self, cycle_id: str, actor_id: str) -> EvaluationCycle:
        today = self.clock.today()
        self._apply(cycle_id, lambda c: c.confirm_criteria(actor_id, today))
        return self._cycle(cycle_id)

    # ---- UC3 -------------------------------------------------------------------------------------
    def register_absence(self, cycle_id: str, absence: Absence) -> date:
        """Record a justified absence; returns the (possibly extended) evaluation deadline."""
        self._apply(cycle_id, lambda c: c.register_absence(absence))
        return self.evaluation_deadline(cycle_id)

    def register_position_change(self, cycle_id: str, change: date) -> PositionChange:
        """Change of position with a significant change of duties (art. 81 ust. 6, § 9 of the regulation).
        Returns what it means: new criteria by a date, or an evaluation within a window."""
        today = self.clock.today()
        return self._apply(cycle_id, lambda c: c.register_position_change(change, self.rules, self.calendar, today))

    def objection_deadline(self, cycle_id: str) -> date | None:
        """Last day for an objection (art. 83 ust. 1); None until the evaluation is acknowledged.
        Feeds `CzescII.termin_sprzeciwu` in the API."""
        return self._cycle(cycle_id).objection_deadline(self.rules, self.calendar)

    def reminders(self, lead_days: int = 30) -> list[Reminder]:
        """Reminders due today across all cycles. `lead_days` is an app setting, not a legal term."""
        today = self.clock.today()
        out: list[Reminder] = []
        for c in self.cycles.list_all():
            if c.status is Status.ACKNOWLEDGED:
                out.extend(self._after_acknowledgement(c, today, lead_days))
                continue
            if c.status is Status.CYCLE_STARTED:
                due, kind, who, what = c.criteria_deadline, "criteria", c.evaluator_id, "wyznaczenie kryteriów oceny"
            elif c.status is Status.CRITERIA_SET:
                due, kind, who, what = c.criteria_deadline, "criteria", c.employee_id, "potwierdzenie kryteriów oceny"
            elif c.status in (Status.CRITERIA_CONFIRMED, Status.MEETING_HELD):
                due, kind, who = c.evaluation_deadline(self.rules, self.calendar), "evaluation", c.evaluator_id
                what = "sporządzenie oceny okresowej"
            elif c.status is Status.EVALUATION_DONE:
                out.append(Reminder(c.id, c.employee_id, c.employee_id, "acknowledgement", today, 0,
                                    "Oczekuje na zapoznanie się z oceną okresową."))
                continue
            else:
                continue
            left = (due - today).days
            if left > lead_days:
                continue
            name = self._name(c.employee_id)
            if left < 0:
                msg = f"Termin na {what} ({name}) minął {due:%d.%m.%Y} – {-left} dni temu."
            elif left == 0:
                msg = f"Dziś mija termin na {what} ({name})."
            else:
                msg = f"Termin na {what} ({name}) upływa {due:%d.%m.%Y} – zostało {left} dni."
            out.append(Reminder(c.id, c.employee_id, who, kind, due, left, msg))
        return sorted(out, key=lambda r: r.days_left)

    def _after_acknowledgement(self, c: EvaluationCycle, today: date, lead_days: int) -> list[Reminder]:
        """Objection window for the evaluated person; re-evaluation date for the evaluator after a negative one."""
        out = []
        objection = c.objection_deadline(self.rules, self.calendar)
        if objection is not None and today <= objection:
            left = (objection - today).days
            out.append(Reminder(c.id, c.employee_id, c.employee_id, "objection", objection, left,
                                f"Możesz złożyć sprzeciw od oceny do dyrektora generalnego do {objection:%d.%m.%Y}."))
        due = c.next_evaluation_due(self.rules, self.calendar)
        if due is not None and (due - today).days <= lead_days:
            left = (due - today).days
            out.append(Reminder(c.id, c.employee_id, c.evaluator_id, "reevaluation", due, left,
                                f"Po ocenie negatywnej {self._name(c.employee_id)} podlega ponownej ocenie "
                                f"od {due:%d.%m.%Y} (6 miesięcy od zapoznania się z oceną)."))
        return out

    # ---- configurable reminder schedule -----------------------------------------------------------
    def _stage(self, c: EvaluationCycle) -> tuple[Stage, date, date, str, str] | None:
        """(stage, start, deadline, recipient, what) of the stage the cycle is in now; None = nothing to remind."""
        if c.status is Status.CYCLE_STARTED:
            return Stage.CRITERIA, c.start_date, c.criteria_deadline, c.evaluator_id,                 "wyznacz kryteria oceny i przeprowadź rozmowę rozpoczynającą"
        if c.status is Status.CRITERIA_SET:
            return Stage.CRITERIA, c.criteria_set_on or c.start_date, c.criteria_deadline, c.employee_id,                 "potwierdź kryteria oceny"
        if c.status in (Status.CRITERIA_CONFIRMED, Status.MEETING_HELD):
            start = c.criteria_confirmed_on or c.criteria_set_on or c.start_date
            return Stage.PERIOD, start, c.evaluation_deadline(self.rules, self.calendar), c.evaluator_id,                 "przeprowadź rozmowę oceniającą i sporządź ocenę"
        if c.status is Status.EVALUATION_DONE and c.evaluated_on:
            return Stage.ACKNOWLEDGEMENT, c.evaluated_on,                 c.evaluated_on + timedelta(days=ACKNOWLEDGEMENT_WINDOW_DAYS), c.employee_id, "zapoznaj się z oceną"
        return None

    def reminder_plan(self, cycle: EvaluationCycle,
                      schedule_for: Callable[[str], ReminderSchedule]) -> list[PlannedReminder]:
        """All reminders of the current stage (past and future), per the recipient's schedule."""
        stage = self._stage(cycle)
        if stage is None:
            return []
        kind, start, deadline, who, what = stage
        schedule = schedule_for(who)
        name = self._name(cycle.employee_id)
        out = []
        for day in reminder_dates(schedule.rules.get(kind, ()), start, deadline, self.calendar):
            left = (deadline - day).days
            msg = (f"Przypomnienie: {what} ({name}) – termin {deadline:%d.%m.%Y}, zostało {left} dni."
                   if kind is not Stage.ACKNOWLEDGEMENT else
                   f"Przypomnienie: {what} – ocena czeka od {start:%d.%m.%Y}.")
            out.append(PlannedReminder(f"{cycle.id}:{kind.value}:{who}:{day.isoformat()}", cycle.id,
                                       cycle.employee_id, who, kind, at_time(day, schedule), deadline, msg))
        return out

    def reminders_between(self, after: date, until: date,
                          schedule_for: Callable[[str], ReminderSchedule]) -> list[PlannedReminder]:
        """Reminders that go out on days in (after, until] – e.g. when the demo clock moves forward."""
        out = [r for c in self.cycles.list_all() for r in self.reminder_plan(c, schedule_for)
               if after < r.when.date() <= until]
        return sorted(out, key=lambda r: r.when)

    def _name(self, employee_id: str) -> str:
        emp = self.employees.get(employee_id)
        return emp.full_name if emp else employee_id

    # ---- UC4 -------------------------------------------------------------------------------------
    def meeting_prep(self, cycle_id: str) -> MeetingPrep:
        cycle = self._cycle(cycle_id)
        employee = self._employee(cycle.employee_id)
        evaluator = self.employees.get(cycle.evaluator_id)
        return build_meeting_prep(cycle, employee, evaluator, self.rules, self.calendar, self.clock.today())

    # ---- UC5 -------------------------------------------------------------------------------------
    def record_review_meeting(
        self,
        cycle_id: str,
        actor_id: str,
        meeting_date: date | None = None,
        period_from: date | None = None,
        period_to: date | None = None,
    ) -> EvaluationCycle:
        today = self.clock.today()
        self._as_evaluator(cycle_id, actor_id, "record_review_meeting", lambda c, a: c.record_review_meeting(
            a, today, self.rules, meeting_date or today, period_from, period_to))
        return self._cycle(cycle_id)

    def submit_evaluation(
        self,
        cycle_id: str,
        actor_id: str,
        scores: Mapping[str, int] | None = None,
        justification: str | None = None,
        iprz_conclusions: str | None = None,
    ) -> EvaluationResult:
        today = self.clock.today()
        return self._as_evaluator(cycle_id, actor_id, "submit_evaluation", lambda c, a: c.submit_evaluation(
            a, today, self.rules, scores, justification, iprz_conclusions))

    def acknowledge(self, cycle_id: str, actor_id: str) -> EvaluationCycle:
        """The evaluated person acknowledges the evaluation – and the next cycle starts on its own, so its deadline
        runs automatically: 24 months (reguly.json) from drawing up the evaluation, or – after a negative one – the
        re-evaluation 6 months from acknowledging it (art. 81 ust. 9) with criteria within 7 days (§ 7 pkt 2)."""
        today = self.clock.today()
        self._apply(cycle_id, lambda c: c.acknowledge(actor_id, today))
        done = self._cycle(cycle_id)
        self.start_next_cycle(done)
        return done

    def start_next_cycle(self, done: EvaluationCycle) -> EvaluationCycle | None:
        """Open the cycle that follows an acknowledged evaluation (None if one is open or there is no evaluator)."""
        emp = self.employees.get(done.employee_id)
        if emp is None or not emp.evaluator_id or self.cycles.find_open_for(done.employee_id) is not None:
            return None
        result = done.result
        negative = result is not None and result.outcome is Outcome.NEGATIVE
        previous = PreviousEvaluation(result.outcome.value if result else None, result.level if result else None,
                                      done.evaluated_on, acknowledged=done.acknowledged_on)
        return self.start_cycle(
            done.employee_id, start_date=done.evaluated_on or done.acknowledged_on, after_negative=negative,
            negative_acknowledged_on=done.acknowledged_on if negative else None, previous_evaluation=previous)
