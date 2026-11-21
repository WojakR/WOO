"""Evaluator's notes from the cycle (observations, feedback, meeting notes) and the evidence they add up to.

Pure domain: no storage, no AI. A note is tagged with a criterion and a sentiment either by the evaluator
or by an accepted AI suggestion; untagged notes do not count as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterable


class Sentiment(str, Enum):
    """Values equal the data model's `Wydzwiek`."""

    POSITIVE = "POZYTYWNY"
    NEUTRAL = "NEUTRALNY"
    NEGATIVE = "NEGATYWNY"


@dataclass(frozen=True)
class Note:
    id: str
    on: date
    text: str
    author_id: str | None = None
    criterion_id: str | None = None
    sentiment: Sentiment | None = None
    indicator: str | None = None  # behavioural indicator text, when known


@dataclass(frozen=True)
class CriterionEvidence:
    criterion_id: str
    positive: tuple[Note, ...] = field(default_factory=tuple)
    neutral: tuple[Note, ...] = field(default_factory=tuple)
    negative: tuple[Note, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.positive) + len(self.neutral) + len(self.negative)

    @property
    def balance(self) -> int:
        """> 0 mostly positive, < 0 mostly negative."""
        return len(self.positive) - len(self.negative)


def evidence_by_criterion(notes: Iterable[Note], criterion_ids: Iterable[str]) -> dict[str, CriterionEvidence]:
    """Tagged notes grouped per criterion (newest first), in the order of `criterion_ids`."""
    ids = list(criterion_ids)
    buckets: dict[str, dict[Sentiment, list[Note]]] = {cid: {s: [] for s in Sentiment} for cid in ids}
    for n in sorted(notes, key=lambda n: n.on, reverse=True):
        if n.criterion_id in buckets and n.sentiment is not None:
            buckets[n.criterion_id][n.sentiment].append(n)
    return {
        cid: CriterionEvidence(
            cid,
            tuple(b[Sentiment.POSITIVE]),
            tuple(b[Sentiment.NEUTRAL]),
            tuple(b[Sentiment.NEGATIVE]),
        )
        for cid, b in buckets.items()
    }
