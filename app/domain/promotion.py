"""Part III of the sheet – the request for the next grade (wniosek o kolejny stopień służbowy, UC9).

Art. 89 ust. 1: a civil servant MAY get the next grade after a POSITIVE evaluation that contains the direct
supervisor's motivated request. So: only civil servants; a negative evaluation blocks the request; at the highest
grade (9, reguly.json) there is nothing to request; requested = held + 1. Art. 89 ust. 2 (obligatory grade) is
computed in consequences.py and only shown here.
"""
from __future__ import annotations

from dataclasses import dataclass

from .rulebook import RuleBook


@dataclass(frozen=True)
class PromotionView:
    applies: str  # TAK | NIE | NIE_DOTYCZY – what goes into the sheet ("czy dołączono wniosek")
    held_grade: int | None
    requested_grade: int | None
    mandatory: bool
    can_request: bool  # the evaluator may (still) tick "TAK"
    blocked_reason: str | None


def promotion_view(civil_servant: bool, held_grade: int | None, positive: bool | None, requested: bool | None,
                   mandatory: bool, rules: RuleBook) -> PromotionView:
    if not civil_servant:
        return PromotionView("NIE_DOTYCZY", None, None, False, False,
                             "Oceniany jest pracownikiem służby cywilnej – wniosek o stopień nie dotyczy.")
    if held_grade is not None and held_grade >= rules.max_grade:
        return PromotionView("NIE", held_grade, None, False, False,
                             "Ocenianemu nie można przyznać kolejnego stopnia służbowego. Oceniany posiada już "
                             "najwyższy możliwy stopień służbowy.")
    nxt = held_grade + 1 if held_grade is not None else None
    if positive is False:
        return PromotionView("NIE", held_grade, None, False, False,
                             f"Przy ocenie negatywnej nie można wnioskować o kolejny stopień ({rules.promotion_basis}).")
    return PromotionView("TAK" if requested else "NIE", held_grade, nxt if requested or mandatory else None,
                         mandatory, True, None)


def check_request(civil_servant: bool, held_grade: int | None, positive: bool | None, requested: bool,
                  rules: RuleBook) -> list[str]:
    """Problems with ticking "TAK" (empty = fine)."""
    if not requested:
        return []
    v = promotion_view(civil_servant, held_grade, positive, True, False, rules)
    problems = [v.blocked_reason] if not v.can_request and v.blocked_reason else []
    if v.can_request and held_grade is None:
        problems.append("Uzupełnij posiadany stopień służbowy.")
    return problems
