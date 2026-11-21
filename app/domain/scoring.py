"""§ 11 of the regulation: average of partial scores, overall level, positive/negative outcome, validations."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Iterable, Mapping

from .errors import ValidationError
from .rulebook import RuleBook


class Outcome(str, Enum):
    POSITIVE = "pozytywna"
    NEGATIVE = "negatywna"


@dataclass(frozen=True)
class EvaluationResult:
    average: Fraction  # exact, so threshold comparisons never suffer from float rounding
    level: str
    outcome: Outcome

    @property
    def average_display(self) -> float:
        return round(float(self.average), 2)


def validate_scores(scores: Iterable[int], rules: RuleBook) -> list[str]:
    allowed = sorted(rules.scale)
    return [
        f"Niedozwolona ocena cząstkowa {s!r} – dopuszczalne wartości: {', '.join(map(str, allowed))}."
        for s in scores
        if not isinstance(s, int) or isinstance(s, bool) or s not in rules.scale
    ]


def level_for_average(average: Fraction, rules: RuleBook) -> str:
    for band in rules.level_bands:
        if band.contains(average):
            return band.level
    raise ValidationError([f"Średnia {float(average):.2f} jest poza skalą ocen."])


def compute_result(scores: Iterable[int], rules: RuleBook) -> EvaluationResult:
    values = list(scores)
    if not values:
        raise ValidationError(["Brak ocen cząstkowych – nie można wyliczyć średniej."])
    if problems := validate_scores(values, rules):
        raise ValidationError(problems)
    average = Fraction(sum(values), len(values))
    level = level_for_average(average, rules)
    positive = level in rules.positive_levels and rules.forbidden_partial_score not in values
    return EvaluationResult(average, level, Outcome.POSITIVE if positive else Outcome.NEGATIVE)


def validate_additional_criteria(sheet: str, additional: list[str], rules: RuleBook) -> list[str]:
    mandatory = set(rules.mandatory(sheet))
    problems: list[str] = []
    if len(additional) > rules.max_additional_criteria:
        problems.append(
            f"Można wybrać najwyżej {rules.max_additional_criteria} kryteria dodatkowe (wybrano {len(additional)})."
        )
    if rules.additional_criteria_unique:
        for cid, n in Counter(additional).items():
            if n > 1:
                problems.append(f"Kryterium dodatkowe „{rules.criterion_name(cid)}” wybrano więcej niż raz.")
    for cid in dict.fromkeys(additional):
        if cid not in rules.criteria:
            problems.append(f"Nieznane kryterium „{cid}”.")
        elif cid in mandatory:
            problems.append(
                f"Kryterium „{rules.criterion_name(cid)}” jest obowiązkowe w arkuszu {sheet} – nie może być dodatkowe."
            )
        elif cid in rules.unavailable_additional:
            problems.append(f"Kryterium „{rules.criterion_name(cid)}” nie jest dostępne jako kryterium dodatkowe "
                            "(wersja przepisów obowiązująca dla tej oceny).")
    return problems


def validate_evaluation(
    criteria_ids: list[str],
    scores: Mapping[str, int],
    justification: str,
    iprz_conclusions: str,
    rules: RuleBook,
) -> EvaluationResult:
    """Full check before the evaluator submits; raises ValidationError listing every problem."""
    problems: list[str] = []
    missing = [c for c in criteria_ids if c not in scores]
    extra = [c for c in scores if c not in criteria_ids]
    if missing:
        problems.append("Brak oceny cząstkowej dla: " + ", ".join(rules.criterion_name(c) for c in missing) + ".")
    if extra:
        problems.append("Ocena dla kryterium spoza arkusza: " + ", ".join(rules.criterion_name(c) for c in extra) + ".")
    problems += validate_scores(scores.values(), rules)
    result = None
    if not problems:
        result = compute_result([scores[c] for c in criteria_ids], rules)
        if (
            result.outcome is Outcome.NEGATIVE
            and rules.justification_required_if_negative
            and not (justification or "").strip()
        ):
            problems.append("Ocena jest negatywna – uzasadnienie oceny jest obowiązkowe.")
    if rules.iprz_required and not (iprz_conclusions or "").strip():
        problems.append("Wnioski dotyczące indywidualnego programu rozwoju zawodowego są obowiązkowe.")
    if problems:
        raise ValidationError(problems)
    assert result is not None
    return result
