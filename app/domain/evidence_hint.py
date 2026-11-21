"""Suggested partial score from the evaluator's tagged notes – a readable hint, never applied automatically.

Rule: share of positive notes among positive + negative ones, mapped linearly onto the scale
(0 % -> lowest, 100 % -> highest), then kept inside the scale's inner values: the extremes
(e.g. 1 = automatic negative outcome under § 11) are left to the evaluator's own judgement.
No hint with fewer than `min_notes` notes. This is an app heuristic, not a legal rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MIN_NOTES = 3


@dataclass(frozen=True)
class ScoreHint:
    points: int
    reason: str  # Polish, shown in the UI


def suggest_points(positive: int, negative: int, scale: Sequence[int], min_notes: int = MIN_NOTES) -> ScoreHint | None:
    values = sorted(scale)
    total = positive + negative
    if total < min_notes or len(values) < 3:
        return None
    share = positive / total
    index = round(share * (len(values) - 1))
    index = min(max(index, 1), len(values) - 2)
    return ScoreHint(
        values[index],
        f"na podstawie {total} notatek ({positive} pozytywnych, {negative} negatywnych)",
    )
