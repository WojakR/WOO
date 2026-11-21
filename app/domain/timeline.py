"""Every deadline of one evaluation, computed automatically from what has happened so far.

Entering the evaluation (drawn up) and the employee's signature (acknowledgement) start new terms by themselves:
the objection period (art. 83 ust. 1), the next evaluation (art. 81 ust. 4) or – after a negative one – the
re-evaluation (art. 81 ust. 9), and the criteria for the next period (§ 7). All lengths come from the RuleBook,
so an amendment entered by the administrator changes them without touching the code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .calendar import WorkingCalendar
from .cycle import EvaluationCycle, Status
from .deadlines import criteria_deadline, evaluation_deadline
from .rulebook import RuleBook

State = Literal["SPELNIONY", "AKTUALNY", "PO_TERMINIE", "NASTEPNY_OKRES"]


@dataclass(frozen=True)
class DeadlineItem:
    kind: str
    label: str
    due: date | None  # None: "niezwłocznie" (no fixed day)
    basis: str
    state: State
    done_on: date | None = None
    note: str = ""


def _state(due: date | None, done_on: date | None, today: date) -> State:
    if done_on is not None:
        return "SPELNIONY"
    return "PO_TERMINIE" if due is not None and today > due else "AKTUALNY"


def deadlines_of(c: EvaluationCycle, rules: RuleBook, cal: WorkingCalendar, today: date) -> list[DeadlineItem]:
    out: list[DeadlineItem] = []
    after_negative_basis = "§ 7 pkt 2 rozporządzenia" if c.after_negative else "§ 7 pkt 1 rozporządzenia"
    out.append(DeadlineItem(
        "KRYTERIA", "Wyznaczenie kryteriów i rozmowa rozpoczynająca", c.criteria_deadline, after_negative_basis,
        _state(c.criteria_deadline, c.criteria_set_on, today), c.criteria_set_on,
        f"{rules.criteria_days_after_negative if c.after_negative else rules.criteria_days} dni od "
        f"{'oceny negatywnej' if c.after_negative else 'poprzedniej oceny / zatrudnienia'}"))

    deadline = c.evaluation_deadline(rules, cal)
    if c.deadline_override is not None:
        basis, note = "art. 81 ust. 8 ustawy / § 9 rozporządzenia", "termin zmieniony decyzją oceniającego"
    elif c.after_negative:
        basis, note = "art. 81 ust. 9 ustawy", f"{rules.reevaluation_after_negative_months} mies. po ocenie negatywnej"
    else:
        basis = "art. 81 ust. 4 i 7 ustawy"
        note = f"{rules.cycle_months} mies." + (" + nieobecności dłuższe niż miesiąc" if c.absences else "")
    out.append(DeadlineItem("OCENA", "Sporządzenie oceny", deadline, basis,
                            _state(deadline, c.evaluated_on, today), c.evaluated_on, note))

    if c.evaluated_on is None:
        return out

    # the evaluation is entered -> the employee is acquainted with it "niezwłocznie" (§ 12 ust. 1)
    out.append(DeadlineItem(
        "ZAPOZNANIE", "Zapoznanie się z oceną", None, "§ 12 ust. 1 rozporządzenia",
        "SPELNIONY" if c.acknowledged_on else "AKTUALNY", c.acknowledged_on, "niezwłocznie"))

    if c.acknowledged_on is None:
        return out

    # the employee signed -> objection period, next evaluation, criteria for the next period
    objection = c.objection_deadline(rules, cal)
    out.append(DeadlineItem(
        "SPRZECIW", "Sprzeciw do dyrektora generalnego", objection, "art. 83 ust. 1 ustawy",
        "PO_TERMINIE" if objection and today > objection else "AKTUALNY", None,
        f"{rules.objection_days} dni od zapoznania się z oceną"))

    if c.status is not Status.ACKNOWLEDGED:
        return out
    if c.is_negative:
        nxt = c.next_evaluation_due(rules, cal)
        out.append(DeadlineItem("KOLEJNA_OCENA", "Ponowna ocena (po ocenie negatywnej)", nxt, "art. 81 ust. 9 ustawy",
                                "NASTEPNY_OKRES", None,
                                f"po {rules.reevaluation_after_negative_months} mies. od zapoznania się z oceną"))
    else:
        nxt = evaluation_deadline(c.evaluated_on, rules, cal)
        out.append(DeadlineItem("KOLEJNA_OCENA", "Kolejna ocena okresowa", nxt, "art. 81 ust. 4 ustawy",
                                "NASTEPNY_OKRES", None, f"{rules.cycle_months} mies. od sporządzenia tej oceny"))
    next_criteria = criteria_deadline(c.evaluated_on, rules, cal, c.is_negative)
    out.append(DeadlineItem(
        "KRYTERIA_NASTEPNE", "Kryteria na kolejny okres", next_criteria,
        "§ 7 pkt 2 rozporządzenia" if c.is_negative else "§ 7 pkt 1 rozporządzenia", "NASTEPNY_OKRES", None,
        f"{rules.criteria_days_after_negative if c.is_negative else rules.criteria_days} dni od sporządzenia oceny"))
    return out
