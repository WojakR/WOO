"""Suggested partial score from the evaluator's tagged notes – a readable hint, never applied automatically.

Rule: share of positive notes among positive + negative ones, mapped linearly onto the scale
(0 % -> lowest, 100 % -> highest), then kept inside the scale's inner values: the extremes
(e.g. 1 = automatic negative outcome under § 11) are left to the evaluator's own judgement.
No hint with fewer than `min_notes` notes. This is an app heuristic, not a legal rule.

The rule counts notes – it does not know how important or long a note is (one long, very positive note weighs as
much as one minor remark). So that nobody takes the number as a verdict, the hint also gives its range: the scores
it would suggest with one more positive or one more negative note. A wide range = the hint is weak; the reason
says so in words and always reminds that the evaluator decides.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MIN_NOTES = 3


@dataclass(frozen=True)
class ScoreHint:
    points: int
    reason: str  # Polish, shown in the UI
    low: int  # with one more negative note
    high: int  # with one more positive note

    @property
    def certain(self) -> bool:
        """One note more either way does not change the hint."""
        return self.low == self.high


def _point(positive: int, negative: int, values: Sequence[int]) -> int:
    index = round(positive / (positive + negative) * (len(values) - 1))
    return values[min(max(index, 1), len(values) - 2)]


def suggest_points(positive: int, negative: int, scale: Sequence[int], min_notes: int = MIN_NOTES) -> ScoreHint | None:
    values = sorted(scale)
    total = positive + negative
    if total < min_notes or len(values) < 3:
        return None
    points = _point(positive, negative, values)
    low, high = _point(positive, negative + 1, values), _point(positive + 1, negative, values)
    spread = "" if low == high else (
        f"; jedna obserwacja więcej w którąś stronę daje od {low} do {high} pkt – podpowiedź jest niepewna")
    return ScoreHint(
        points,
        f"na podstawie {total} notatek ({positive} pozytywnych, {negative} negatywnych){spread}. "
        "Asystent liczy notatki, nie ich wagę ani znaczenie – ocenę cząstkową ustala oceniający",
        low, high,
    )
