"""Consequences of consecutive periodic evaluations – signals for the HR department, never automatic decisions.

- Two consecutive negative evaluations of a civil servant (urzędnik służby cywilnej): termination of employment
  with a 3-month notice (art. 71 ust. 1 pkt 1 ustawy). For a civil-service employee (pracownik) the Act has no such
  rule – HR only gets the information.
- Two consecutive positive evaluations on one of the two top levels since the last grade (art. 89 ust. 2): a civil
  servant receives the next grade within 30 days of acknowledging the evaluation (with it – the higher allowance
  for the grade). HR must grant it.
All numbers and levels come from the RuleBook (reguly.json "skutki_ocen").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .rulebook import RuleBook


@dataclass(frozen=True)
class FinishedEvaluation:
    """One evaluation in the person's history (from the system, or from the HR data before it)."""
    drawn_up: date
    outcome: str | None  # "pozytywna" / "negatywna" / None (unknown)
    level: str | None
    acknowledged: date | None = None
    evaluation_id: str | None = None


@dataclass(frozen=True)
class Signal:
    kind: str  # DWIE_NEGATYWNE | STOPIEN_OBLIGATORYJNY
    message: str
    basis: str | None  # legal basis – None when the rule does not apply to the person (information only)
    evaluation_id: str | None
    due: date | None = None  # e.g. the latest day to grant the obligatory grade


def _ordered(history: list[FinishedEvaluation]) -> list[FinishedEvaluation]:
    return sorted(history, key=lambda h: h.drawn_up)


def two_negatives(history: list[FinishedEvaluation], civil_servant: bool, rules: RuleBook) -> Signal | None:
    """The last N evaluations (N from the rules) are all negative -> a signal for HR."""
    n = rules.termination_after_negatives
    last = _ordered(history)[-n:]
    if len(last) < n or any(h.outcome != "negatywna" for h in last):
        return None
    if civil_servant:
        return Signal("DWIE_NEGATYWNE",
                      f"{n} kolejne negatywne oceny okresowe urzędnika służby cywilnej – podstawa rozwiązania "
                      f"stosunku pracy z zachowaniem {rules.termination_notice_months}-miesięcznego okresu "
                      f"wypowiedzenia ({rules.termination_basis}). Decyzję podejmuje dyrektor generalny.",
                      rules.termination_basis, last[-1].evaluation_id)
    return Signal("DWIE_NEGATYWNE",
                  f"{n} kolejne negatywne oceny okresowe pracownika służby cywilnej. Ustawa nie przewiduje tu "
                  "automatycznego skutku – informacja dla działu kadr (dalsze decyzje według prawa pracy).",
                  None, last[-1].evaluation_id)


def warning_before_submit(history: list[FinishedEvaluation], negative_now: bool, civil_servant: bool,
                          rules: RuleBook) -> str | None:
    """Shown to the evaluator (does not block) when the evaluation being drawn up would be the N-th negative."""
    if not negative_now:
        return None
    n = rules.termination_after_negatives
    before = _ordered(history)[-(n - 1):] if n > 1 else []
    if len(before) < n - 1 or any(h.outcome != "negatywna" for h in before):
        return None
    if civil_servant:
        return (f"To będzie {n}. z rzędu negatywna ocena urzędnika służby cywilnej – skutkuje rozwiązaniem stosunku "
                f"pracy ({rules.termination_basis}). Upewnij się, że uzasadnienie jest pełne.")
    return f"To będzie {n}. z rzędu negatywna ocena – dział kadr dostanie informację."


def mandatory_grade(history: list[FinishedEvaluation], civil_servant: bool, grade: int | None,
                    grade_since: date | None, rules: RuleBook) -> Signal | None:
    """Art. 89 ust. 2: since the last grade, the last N evaluations are positive on one of the top levels."""
    if not civil_servant or (grade is not None and grade >= rules.max_grade):
        return None
    since = [h for h in _ordered(history) if grade_since is None or h.drawn_up > grade_since]
    n = rules.mandatory_grade_after
    last = since[-n:]
    if len(last) < n or any(h.outcome != "pozytywna" or h.level not in rules.mandatory_grade_levels for h in last):
        return None
    due = last[-1].acknowledged + timedelta(days=rules.mandatory_grade_days) if last[-1].acknowledged else None
    to = f" (do {due:%d.%m.%Y})" if due else ""
    return Signal("STOPIEN_OBLIGATORYJNY",
                  f"{n} kolejne oceny na jednym z dwóch najwyższych poziomów od otrzymania ostatniego stopnia – "
                  f"urzędnik otrzymuje kolejny stopień służbowy w ciągu {rules.mandatory_grade_days} dni od "
                  f"zapoznania się z oceną{to} ({rules.mandatory_grade_basis}).",
                  rules.mandatory_grade_basis, last[-1].evaluation_id, due)


def would_be_mandatory(history: list[FinishedEvaluation], level_now: str | None, positive_now: bool,
                       civil_servant: bool, grade: int | None, grade_since: date | None, today: date,
                       rules: RuleBook) -> bool:
    """For the evaluation being drawn up: would it complete the series of art. 89 ust. 2?"""
    if not positive_now or level_now is None:
        return False
    probe = history + [FinishedEvaluation(today, "pozytywna", level_now)]
    return mandatory_grade(probe, civil_servant, grade, grade_since, rules) is not None
