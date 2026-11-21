"""Change of the evaluator (the supervisor leaves, or someone else takes over the team) during the evaluated period.

Law (server/data/kprm/wiedza/):
- art. 81 ust. 8 pkt 1 ustawy: on a change on the evaluator's post the evaluator MAY change the deadline – so the
  leaving supervisor may draw up the evaluation now – only if more than 6 months passed since the last evaluation
  (for a first evaluation: the evaluated period is longer than 6 months). The threshold is
  `terminy.zmiana_terminu_mozliwa_po_miesiacach_od_ostatniej_oceny` in reguly.json (RuleBook).
- If the leaving supervisor draws it up: the new one sets new criteria; the next evaluation is due 24 months later
  (an ordinary new cycle from the day the evaluation was drawn up – poradnik KPRM s. 16).
- If not: the new evaluator evaluates on the criteria chosen before, by the same deadline (§ 9 ust. 3).

The specification of the system speaks of "6 months worked under the leaving supervisor"; the Act counts from the
last evaluation. The check follows the Act and also reports how long the person worked under the leaving
supervisor (since they became the evaluator), so the HR department sees both.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .calendar import add_months
from .rulebook import RuleBook


@dataclass(frozen=True)
class EvaluatorChangeCheck:
    may_evaluate_early: bool  # art. 81 ust. 8 pkt 1: the leaving evaluator may draw up the evaluation now
    counted_from: date  # last evaluation, or the start of the first evaluated period
    possible_from: date  # first day on which an early evaluation is allowed
    under_leaving_since: date  # since when the leaving supervisor evaluates this person
    days_under_leaving: int
    explanation: str


def check_evaluator_change(cycle_start: date, evaluator_since: date, change_on: date,
                           rules: RuleBook) -> EvaluatorChangeCheck:
    months = rules.deadline_change_after_months
    possible_from = add_months(cycle_start, months) + timedelta(days=1)
    may = change_on >= possible_from
    since = max(evaluator_since, cycle_start)
    days = max(0, (change_on - since).days)
    if may:
        text = (f"Od ostatniej oceny ({cycle_start:%d.%m.%Y}) minęło ponad {months} mies. – odchodzący oceniający może "
                f"sporządzić ocenę przed zmianą (art. 81 ust. 8 pkt 1). Wtedy nowy oceniający wyznacza nowe kryteria, "
                "a kolejna ocena za 24 miesiące. Jeśli tego nie zrobi, nowy oceniający ocenia na podstawie "
                "dotychczasowych kryteriów w niezmienionym terminie (§ 9 ust. 3).")
    else:
        text = (f"Od ostatniej oceny ({cycle_start:%d.%m.%Y}) nie minęło więcej niż {months} mies. (możliwe od "
                f"{possible_from:%d.%m.%Y}) – wcześniejszej oceny nie sporządza się. Nowy oceniający ocenia na podstawie "
                "dotychczasowych kryteriów w niezmienionym terminie (§ 9 ust. 3).")
    return EvaluatorChangeCheck(may, cycle_start, possible_from, since, days, text)
