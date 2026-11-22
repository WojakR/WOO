"""Use cases UC1–UC5 of the periodic evaluation (no UI, no LLM).

UC1 start_cycle + set_criteria, UC2 confirm_criteria, UC3 reminders / register_absence,
UC4 meeting_prep, UC5 record_review_meeting + submit_evaluation, then acknowledge.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

from app.domain.calendar import WorkingCalendar
from app.domain.cycle import CHANGE, REDO, EvaluationCycle, PreviousEvaluation, Status
from app.domain.deadlines import Absence, PositionChange
from app.domain.employee import Employee
from app.domain.errors import InvalidTransition, NotFound, ValidationError
from app.domain.meeting_prep import MeetingPrep, build_meeting_prep
from app.domain.reminder_schedule import ReminderSchedule, Stage, at_time, reminder_dates
from app.domain.rulebook import RuleBook
from app.domain.scoring import EvaluationResult, Outcome
from app.domain.sheet_choice import SheetSuggestion, suggest_sheet

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


@dataclass(frozen=True)
class ProcessEvent:
    """Something happened in an evaluation that someone has to be told about (UC: "wysłanie powiadomienia")."""
    kind: str  # OCENA_SPORZADZONA | OCENA_SPORZADZONA_PONOWNIE | OCENA_ZMIENIONA | SPRZECIW_ZLOZONY | SPRZECIW_ROZPATRZONY
    cycle: EvaluationCycle  # as it is right after the step
    on: date


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
        self.objection_reviewer = "kadry"  # who decides objections (office setting, art. 83 ust. 1: DG)
        # per evaluation (edge cases: head of the office, no DG – app/domain/objection.py); default: the DG
        self.objection_reviewer_for: Callable[[EvaluationCycle], str] = lambda c: self.objection_reviewer
        self.sheet_mapping: Mapping | None = None  # arkusze.json["dobor_arkusza"]; None = the HR record's sheet
        # called when an evaluation becomes final for the personnel file (acknowledged / refusal noted /
        # objection not upheld) – e.g. the e-Akt export (app/application/personnel_export.py)
        self.on_final: list[Callable[[EvaluationCycle], None]] = []
        # called after a step others must hear about (ProcessEvent.kind) – the state turns them into notices
        self.on_event: list[Callable[[ProcessEvent], None]] = []
        # versions of the regulation (state wires app/infrastructure/regulations.py; None = one rule book only)
        self.version_at: Callable[[date], int | None] = lambda day: None
        self.rulebook_of: Callable[[int | None], RuleBook] | None = None

    def rules_for(self, c: EvaluationCycle) -> RuleBook:
        """The rule book this cycle follows: the version of the regulation in force on the day its criteria were
        set (before that: the day it started) – an amendment never changes a running evaluation."""
        if self.rulebook_of is None:
            return self.rules
        version = c.rules_version
        if version is None:  # cycles stored before versioning: the version in force on their reference day
            version = self.version_at(c.criteria_set_on or (c.history[0][0] if c.history else self.clock.today()))
        return self.rulebook_of(version)

    def _pin_rules(self, c: EvaluationCycle, day: date) -> None:
        if self.rulebook_of is not None:
            c.rules_version = self.version_at(day)

    def _final(self, cycle_id: str) -> None:
        c = self._cycle(cycle_id)
        for hook in self.on_final:
            hook(c)

    def _emit(self, kind: str, cycle_id: str) -> None:
        """Tell the listeners (notifications, app/application/notices.py) what has just happened."""
        if not self.on_event:
            return
        event = ProcessEvent(kind, self._cycle(cycle_id), self.clock.today())
        for listener in self.on_event:
            listener(event)

    def employee_absences(self, employee_id: str) -> list[Absence]:
        """Every absence of the person registered in any of their cycles (an absence after the evaluation was
        drawn up is registered on the next cycle, but still moves the objection period of the previous one)."""
        out: list[Absence] = []
        for c in self.cycles.list_all():
            if c.employee_id == employee_id:
                out.extend(a for a in c.absences if a not in out)
        return out

    def suggest_sheet(self, employee_id: str) -> SheetSuggestion:
        emp = self._employee(employee_id)
        if self.sheet_mapping is None:
            return SheetSuggestion(emp.sheet, "Arkusz z danych kadrowych pracownika.")
        return suggest_sheet(emp, self.sheet_mapping)

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
        c = self._cycle(cycle_id)
        return c.evaluation_deadline(self.rules_for(c), self.calendar)

    def check_deadline_change(self, cycle_id: str, actor_id: str, reason: str, new_deadline: date | None,
                              justification: str) -> tuple[date, date]:
        """Validate a change of the deadline without applying it (a request waiting for HR) -> (old, new)."""
        c = self._cycle(cycle_id)
        probe = copy.deepcopy(c)
        acting = c.evaluator_id if actor_id in self.deputies(c.evaluator_id, self.clock.today()) else actor_id
        return probe.change_deadline(acting, reason, new_deadline, justification, self.clock.today(), self.rules,
                                     self.calendar)

    def change_deadline(self, cycle_id: str, actor_id: str, reason: str, new_deadline: date | None,
                        justification: str) -> tuple[date, date]:
        """Art. 81 ust. 8 – the evaluator (or their deputy) moves the deadline -> (old, new)."""
        today = self.clock.today()
        return self._as_evaluator(cycle_id, actor_id, "change_deadline", lambda c, a: c.change_deadline(
            a, reason, new_deadline, justification, today, self.rules, self.calendar))

    # ---- UC1 -------------------------------------------------------------------------------------
    def start_cycle(
        self,
        employee_id: str,
        start_date: date | None = None,
        after_negative: bool | None = None,
        negative_acknowledged_on: date | None = None,
        previous_evaluation: PreviousEvaluation | None = None,
        sheet: str | None = None,
        sheet_reason: str = "",
        by: str = "kadry",
    ) -> EvaluationCycle:
        """Open a cycle. Defaults: start = day the previous evaluation was drawn up (else today, i.e. hiring);
        the sheet = the system's suggestion from the position (§ 3); another `sheet` needs `sheet_reason`;
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
        suggestion = self.suggest_sheet(employee_id)
        if sheet is not None and sheet != suggestion.sheet and not sheet_reason.strip():
            raise ValidationError([f"System podpowiada arkusz {suggestion.sheet} ({suggestion.reason}) – "
                                   f"podaj uzasadnienie wyboru arkusza {sheet}."])
        cycle = EvaluationCycle.start(
            self._new_id(), emp.id, emp.evaluator_id, sheet or suggestion.sheet, start_date, today,
            self.rules, self.calendar, after_negative, prev, negative_acknowledged_on,
        )
        self._pin_rules(cycle, today)
        cycle.sheet_suggested, cycle.sheet_reason, cycle.sheet_warning = (suggestion.sheet, suggestion.reason,
                                                                          suggestion.warning)
        if sheet is not None and sheet != suggestion.sheet:
            cycle.sheet_changes.append((today, by, suggestion.sheet, sheet, sheet_reason.strip()))
        self.cycles.save(cycle)
        return cycle

    def change_sheet(self, cycle_id: str, sheet: str, reason: str, by: str) -> EvaluationCycle:
        """HR changes the sheet (with a reason) – only before the criteria are approved."""
        today = self.clock.today()
        self._apply(cycle_id, lambda c: c.change_sheet(sheet, reason, by, today, self.rules_for(c)))
        return self._cycle(cycle_id)

    def set_criteria(
        self,
        cycle_id: str,
        actor_id: str,
        additional_criteria: list[str] | None = None,
        goals: list[str] | None = None,
        deadline_override: date | None = None,
    ) -> EvaluationCycle:
        today = self.clock.today()
        def run(c: EvaluationCycle, a: str) -> None:
            self._pin_rules(c, today)  # the version in force on the day the criteria are set
            c.set_criteria(a, today, self.rules_for(c), additional_criteria, goals, deadline_override)

        self._as_evaluator(cycle_id, actor_id, "set_criteria", run)
        return self._cycle(cycle_id)

    def edit(self, cycle_id: str, actor_id: str, **changes: Any) -> EvaluationCycle:
        """Draft edits (e.g. scores during the meeting); locked fields raise FieldLocked."""
        self._as_evaluator(cycle_id, actor_id, "edit", lambda c, a: c.edit(a, self.rules_for(c), **changes))
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

    def evaluator_change_check(self, employee_id: str, change_on: date):
        """May the leaving evaluator draw up the evaluation before `change_on` (art. 81 ust. 8 pkt 1)?"""
        from app.domain.evaluator_change import check_evaluator_change

        c = self.cycles.find_open_for(employee_id)
        if c is None:
            raise InvalidTransition("Pracownik nie ma otwartego cyklu oceny.")
        return c, check_evaluator_change(c.start_date, c.evaluator_since(), change_on, self.rules)

    def change_evaluator(self, employee_id: str, new_evaluator_id: str, on: date,
                         early_evaluation: bool) -> tuple[str, EvaluationCycle | None]:
        """Move the person to a new evaluator (the directory is updated by the caller).
        - `early_evaluation`: the leaving evaluator has drawn up the evaluation already (art. 81 ust. 8 pkt 1) – the
          following cycle (if it runs) goes to the new evaluator, who sets new criteria -> ("NOWY_CYKL", cycle).
        - otherwise the running cycle goes to the new evaluator, criteria and deadline unchanged (§ 9 ust. 3)
          -> ("PRZEJECIE", cycle)."""
        self._employee(new_evaluator_id)
        leaving = self._employee(employee_id).evaluator_id  # the directory still has the leaving evaluator
        if early_evaluation:
            done = [c for c in self.cycles.list_all() if c.employee_id == employee_id
                    and c.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION)
                    and c.evaluated_on is not None and c.evaluated_on <= on]
            last = max(done, key=lambda c: c.evaluated_on, default=None)
            # the latest evaluation must be the leaving evaluator's, drawn up while they were the evaluator
            if last is None or last.evaluator_id != leaving or last.evaluated_on < last.evaluator_since():
                raise InvalidTransition("Odchodzący oceniający nie sporządził oceny – wybierz przejęcie oceny przez "
                                        "nowego oceniającego (§ 9 ust. 3).")
            nxt = self.cycles.find_open_for(employee_id)
            if nxt is None:
                return "NOWY_CYKL", None  # starts with the new evaluator once the evaluation is acknowledged
            if nxt.status is not Status.CYCLE_STARTED:  # criteria already set in the following cycle: not "now"
                raise InvalidTransition("Po ostatniej ocenie trwa już kolejny cykl z wyznaczonymi kryteriami – "
                                        "wybierz przejęcie oceny przez nowego oceniającego (§ 9 ust. 3).")
            self._apply(nxt.id, lambda c: c.reassign_evaluator(new_evaluator_id, on))
            return "NOWY_CYKL", self._cycle(nxt.id)
        c = self.cycles.find_open_for(employee_id)
        if c is None:
            raise InvalidTransition("Pracownik nie ma otwartego cyklu oceny.")
        self._apply(c.id, lambda x: x.reassign_evaluator(new_evaluator_id, on))
        return "PRZEJECIE", self._cycle(c.id)

    def register_position_change(self, cycle_id: str, change: date, new_sheet: str | None = None) -> PositionChange:
        """Change of position with a significant change of duties (art. 81 ust. 6, § 9 of the regulation).
        Returns what it means: new criteria by a date, or an evaluation within a window. With new criteria and a
        position that needs another sheet, the sheet changes before the criteria are set again (an evaluation in
        the window still covers the old position, so its sheet stays; the next cycle takes the new one)."""
        today = self.clock.today()

        def run(c: EvaluationCycle) -> PositionChange:
            out = c.register_position_change(change, self.rules_for(c), self.calendar, today)
            if out.kind == "NOWE_KRYTERIA" and new_sheet and new_sheet != c.sheet:
                c.change_sheet(new_sheet, "Zmiana stanowiska – nowe kryteria (§ 9 rozporządzenia).", "kadry", today,
                               self.rules_for(c))
            return out

        return self._apply(cycle_id, run)

    def objection_deadline(self, cycle_id: str) -> date | None:
        """Last day for an objection (art. 83 ust. 1); None until the evaluation is acknowledged.
        Feeds `CzescII.termin_sprzeciwu` in the API."""
        c = self._cycle(cycle_id)
        return c.objection_deadline(self.rules_for(c), self.calendar, self.employee_absences(c.employee_id))

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
                due, kind, who = c.evaluation_deadline(self.rules_for(c), self.calendar), "evaluation", c.evaluator_id
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
        objection = c.objection_deadline(self.rules_for(c), self.calendar, self.employee_absences(c.employee_id))
        if objection is not None and today <= objection:
            left = (objection - today).days
            out.append(Reminder(c.id, c.employee_id, c.employee_id, "objection", objection, left,
                                f"Możesz złożyć sprzeciw od oceny do dyrektora generalnego do {objection:%d.%m.%Y}."))
        due = c.next_evaluation_due(self.rules_for(c), self.calendar)
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
            return Stage.PERIOD, start, c.evaluation_deadline(self.rules_for(c), self.calendar), c.evaluator_id,                 "przeprowadź rozmowę oceniającą i sporządź ocenę"
        if c.status is Status.OBJECTION and c.objection_filed_on:
            return Stage.OBJECTION_REVIEW, c.objection_filed_on, c.objection_review_deadline(self.rules_for(c), self.calendar),                 self.objection_reviewer_for(c), "rozpatrz sprzeciw od oceny okresowej"
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
        return build_meeting_prep(cycle, employee, evaluator, self.rules_for(cycle), self.calendar, self.clock.today())

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
            a, today, self.rules_for(c), meeting_date or today, period_from, period_to))
        return self._cycle(cycle_id)

    def submit_evaluation(
        self,
        cycle_id: str,
        actor_id: str,
        scores: Mapping[str, int] | None = None,
        justification: str | None = None,
        iprz_conclusions: str | None = None,
    ) -> EvaluationResult:
        """Draw up the evaluation. After an upheld objection this carries out the director general's order: the
        evaluation drawn up a second time goes to the evaluated person again; a changed one is final at once
        (it stays the evaluation acknowledged before) – the next cycle restarts from the changed result."""
        today = self.clock.today()
        order = self._cycle(cycle_id).objection_outcome if self._cycle(cycle_id).objection_order_pending else None
        result = self._as_evaluator(cycle_id, actor_id, "submit_evaluation", lambda c, a: c.submit_evaluation(
            a, today, self.rules_for(c), scores, justification, iprz_conclusions))
        kind = {CHANGE: "OCENA_ZMIENIONA", REDO: "OCENA_SPORZADZONA_PONOWNIE"}.get(order, "OCENA_SPORZADZONA")
        self._emit(kind, cycle_id)
        if order == CHANGE:
            self._after_acknowledgement_done(cycle_id)
        return result

    def acknowledge(self, cycle_id: str, actor_id: str) -> EvaluationCycle:
        """The evaluated person acknowledges the evaluation – and the next cycle starts on its own, so its deadline
        runs automatically: 24 months (reguly.json) from drawing up the evaluation, or – after a negative one – the
        re-evaluation 6 months from acknowledging it (art. 81 ust. 9) with criteria within 7 days (§ 7 pkt 2)."""
        today = self.clock.today()
        self._apply(cycle_id, lambda c: c.acknowledge(actor_id, today))
        return self._after_acknowledgement_done(cycle_id)

    def _after_acknowledgement_done(self, cycle_id: str) -> EvaluationCycle:
        done = self._cycle(cycle_id)
        self.start_next_cycle(done)
        self._final(cycle_id)
        return done

    # ---- paper flow ---------------------------------------------------------------------------------
    def record_paper(self, cycle_id: str, actor_id: str, printed_on: date | None = None,
                     signed_on: date | None = None) -> EvaluationCycle:
        """Print date and/or signature date entered by the evaluator; the signature is the acknowledgement."""
        today = self.clock.today()
        before = self._cycle(cycle_id).status
        self._as_evaluator(cycle_id, actor_id, "record_paper",
                           lambda c, a: c.record_paper(a, today, printed_on, signed_on))
        if before is Status.EVALUATION_DONE and self._cycle(cycle_id).status is Status.ACKNOWLEDGED:
            return self._after_acknowledgement_done(cycle_id)
        return self._cycle(cycle_id)

    def refuse_acknowledgement(self, cycle_id: str, actor_id: str, note: str,
                               delivered_on: date | None = None) -> EvaluationCycle:
        """Fikcja zapoznania: the evaluated person refused to sign; counts as acknowledged on that day."""
        today = self.clock.today()
        self._as_evaluator(cycle_id, actor_id, "refuse_acknowledgement",
                           lambda c, a: c.refuse_acknowledgement(a, today, note, delivered_on))
        return self._after_acknowledgement_done(cycle_id)

    # ---- objection (art. 83) ------------------------------------------------------------------------
    def file_objection(self, cycle_id: str, actor_id: str, text: str) -> EvaluationCycle:
        today = self.clock.today()
        absences = self.employee_absences(self._cycle(cycle_id).employee_id)
        self._apply(cycle_id, lambda c: c.file_objection(actor_id, today, text, self.rules_for(c), self.calendar, absences))
        self._emit("SPRZECIW_ZLOZONY", cycle_id)
        return self._cycle(cycle_id)

    def decide_objection(self, cycle_id: str, reviewer_id: str, upheld: bool, reason: str,
                         outcome: str | None = None) -> EvaluationCycle:
        """Upheld (`outcome` CHANGE or REDO, art. 83 ust. 4): the evaluation returns to the evaluator; the follow-up
        cycle started automatically at the acknowledgement is removed if nobody has worked on it yet (it was
        computed from the old result) – it starts again when the evaluation is changed, or drawn up again and
        acknowledged."""
        today = self.clock.today()
        before = self._cycle(cycle_id)
        self._apply(cycle_id, lambda c: c.decide_objection(reviewer_id, today, upheld, reason, outcome))
        self._emit("SPRZECIW_ROZPATRZONY", cycle_id)
        if upheld:  # the reopened evaluation is open again too, so look for the follow-up explicitly
            for f in self.cycles.list_all():
                if (f.id != cycle_id and f.employee_id == before.employee_id and f.status is Status.CYCLE_STARTED
                        and f.previous_evaluation and f.previous_evaluation.acknowledged == before.acknowledged_on):
                    self.cycles.delete(f.id)
        else:
            self._final(cycle_id)  # the evaluation stays: export it again with the decision
        return self._cycle(cycle_id)

    def start_next_cycle(self, done: EvaluationCycle) -> EvaluationCycle | None:
        """Open the cycle that follows an acknowledged evaluation (None if one is open or there is no evaluator)."""
        emp = self.employees.get(done.employee_id)
        if emp is None or not emp.evaluator_id or self.cycles.find_open_for(done.employee_id) is not None:
            return None
        result = done.result
        # Only the first negative gets the 6-month re-evaluation (art. 81 ust. 9): a negative re-evaluation
        # starts the ordinary 24-month cycle again (KPRM spec: "negatywna jest jedna").
        negative = result is not None and result.outcome is Outcome.NEGATIVE and not done.after_negative
        previous = PreviousEvaluation(result.outcome.value if result else None, result.level if result else None,
                                      done.evaluated_on, acknowledged=done.acknowledged_on)
        return self.start_cycle(
            done.employee_id, start_date=done.evaluated_on or done.acknowledged_on, after_negative=negative,
            negative_acknowledged_on=done.acknowledged_on if negative else None, previous_evaluation=previous)
