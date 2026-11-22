"""The person's history as the evaluator should see it before the review meeting (spec, points 3 and 9).

Tenure in the office + the levels of the consecutive evaluations (the earlier ones and – if all partial scores are
in – the current one) give one or more findings, e.g.:
- SPADEK_PRZY_STAZU – long tenure and the result dropped (or keeps dropping): the cause may lie outside skills,
- SPADEK_TRENDU     – several evaluations in a row, each lower than the one before,
- STAGNACJA         – the same middle level for several evaluations despite growing experience,
- STABILNIE_WYSOKO  – several evaluations in a row on one of the two top levels,
- WZROST            – higher than the previous evaluation,
- NOWY_PRACOWNIK    – short tenure (first evaluation in the office).
The assistant turns them into conversation topics and development ideas (texts: config/ustawienia_urzedu.json
"profil_pracownika"). Findings are hints for the evaluator, never a judgement of the person and never a diagnosis.
Thresholds are office settings, not rules of law.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

KINDS = ("SPADEK_PRZY_STAZU", "SPADEK_TRENDU", "STAGNACJA", "STABILNIE_WYSOKO", "WZROST", "NOWY_PRACOWNIK")


@dataclass(frozen=True)
class ProfileSettings:
    long_tenure_years: int = 5  # "doświadczony pracownik"
    new_employee_months: int = 12
    trend_evaluations: int = 3  # strictly falling over this many results = a falling trend
    plateau_evaluations: int = 2  # the same level this many times in a row = a plateau
    plateau_min_tenure_years: int = 3  # "mimo większego doświadczenia"

    @classmethod
    def from_dict(cls, raw: Mapping | None) -> ProfileSettings:
        raw = raw or {}
        d = cls()
        values = {
            "long_tenure_years": int(raw.get("staz_dlugi_lat", d.long_tenure_years)),
            "new_employee_months": int(raw.get("nowy_pracownik_miesiecy", d.new_employee_months)),
            "trend_evaluations": int(raw.get("trend_ocen", d.trend_evaluations)),
            "plateau_evaluations": int(raw.get("stagnacja_ocen", d.plateau_evaluations)),
            "plateau_min_tenure_years": int(raw.get("stagnacja_min_stazu_lat", d.plateau_min_tenure_years)),
        }
        if values["trend_evaluations"] < 2 or values["plateau_evaluations"] < 2:
            raise ValueError("profil_pracownika: trend_ocen i stagnacja_ocen muszą wynosić co najmniej 2.")
        return cls(**values)


@dataclass(frozen=True)
class ResultPoint:
    """One evaluation in the history, oldest first. `rank`: 0 = the lowest level of the rule book."""
    on: date | None
    level: str
    rank: int
    current: bool = False  # the evaluation being drawn up now (scores entered, not yet signed)

    def label(self) -> str:
        when = "teraz (z wpisanych ocen cząstkowych)" if self.current else f"{self.on:%d.%m.%Y}" if self.on else "wcześniej"
        return f"{when}: {self.level}"


@dataclass(frozen=True)
class ProfileFinding:
    kind: str
    evidence: tuple[str, ...]


def tenure_months(start: date | None, today: date) -> int | None:
    if start is None or start > today:
        return None
    return (today.year - start.year) * 12 + today.month - start.month - (1 if today.day < start.day else 0)


def tenure_text(months: int) -> str:
    years, rest = divmod(months, 12)
    if years == 0:
        return f"staż w urzędzie: {rest} mies."
    return f"staż w urzędzie: {years} lat" + (f" {rest} mies." if rest else "")


def employee_profile(points: Sequence[ResultPoint], top_rank: int, employment_start: date | None, today: date,
                     settings: ProfileSettings = ProfileSettings()) -> list[ProfileFinding]:
    """`points` oldest first; `top_rank` = rank of the highest level. Several findings may apply at once."""
    months = tenure_months(employment_start, today)
    ranks = [p.rank for p in points]
    tenure = (tenure_text(months),) if months is not None else ()
    seq = (" → ".join(p.label() for p in points[-max(settings.trend_evaluations, settings.plateau_evaluations):]),) \
        if points else ()
    found: list[ProfileFinding] = []

    if months is not None and months < settings.new_employee_months:
        found.append(ProfileFinding("NOWY_PRACOWNIK", tenure))

    n = settings.trend_evaluations
    falling = len(ranks) >= n and all(a > b for a, b in zip(ranks[-n:], ranks[-n + 1:]))
    dropped = len(ranks) >= 2 and ranks[-1] < ranks[-2]
    long_tenure = months is not None and months >= 12 * settings.long_tenure_years
    if dropped and long_tenure:
        found.append(ProfileFinding("SPADEK_PRZY_STAZU", (*tenure, *seq)))
    elif falling:
        found.append(ProfileFinding("SPADEK_TRENDU", (*tenure, *seq)))

    p = settings.plateau_evaluations
    last = ranks[-p:]
    if len(ranks) >= p and len(set(last)) == 1:
        if last[0] >= top_rank - 1:  # one of the two top levels (as in art. 89 ust. 2)
            found.append(ProfileFinding("STABILNIE_WYSOKO", (*tenure, *seq)))
        else:
            experienced = (months is not None and months >= 12 * settings.plateau_min_tenure_years) or \
                (months is None and len(ranks) > p)  # unknown tenure, but a long history
            if experienced:
                found.append(ProfileFinding("STAGNACJA", (*tenure, *seq)))
    elif len(ranks) >= 2 and ranks[-1] > ranks[-2]:
        found.append(ProfileFinding("WZROST", seq))
    return found
