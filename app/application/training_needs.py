"""Training needs from low partial scores (spec, point 4).

1. per person – criteria of their latest drawn-up evaluation scored below the office threshold
   (config/ustawienia_urzedu.json "szkolenia") + the IPRZ conclusions;
2. per unit / office – a ranking of the criteria with the most low scores;
3. criterion -> training area is data (data/kprm/kryteria.json "obszar_szkoleniowy");
4. a recommendation worded by the assistant (only aggregates go to the model) or by a template.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.domain.cycle import EvaluationCycle
from app.domain.employee import Employee
from app.domain.rulebook import RuleBook


@dataclass(frozen=True)
class Need:
    criterion_id: str
    criterion: str
    score: int
    area: str


@dataclass(frozen=True)
class PersonNeeds:
    employee_id: str
    name: str
    unit: str
    cycle_id: str
    needs: tuple[Need, ...]
    iprz: str


@dataclass(frozen=True)
class RankItem:
    criterion_id: str
    criterion: str
    area: str
    low_scores: int  # people with a low score in this criterion
    evaluated: int  # people evaluated in this criterion


def latest_drawn_up(cycles: Sequence[EvaluationCycle]) -> dict[str, EvaluationCycle]:
    """The latest evaluation with a result per person (imported ones count – they are real history)."""
    out: dict[str, EvaluationCycle] = {}
    for c in cycles:
        if c.result is None or c.evaluated_on is None:
            continue
        if c.employee_id not in out or c.evaluated_on > out[c.employee_id].evaluated_on:
            out[c.employee_id] = c
    return out


def person_needs(c: EvaluationCycle, employee: Employee, rules: RuleBook, below: int,
                 areas: Mapping[str, str]) -> PersonNeeds:
    needs = tuple(Need(cid, rules.criterion_name(cid), pts, areas.get(cid, rules.criterion_name(cid)))
                  for cid, pts in sorted(c.scores.items(), key=lambda kv: (kv[1], kv[0])) if pts < below)
    return PersonNeeds(employee.id, employee.full_name, employee.unit, c.id, needs, c.iprz_conclusions)


def analyse(employees: Sequence[Employee], cycles: Sequence[EvaluationCycle], rules: RuleBook, below: int,
            areas: Mapping[str, str], unit: str | None = None) -> tuple[list[PersonNeeds], list[RankItem]]:
    who = {e.id: e for e in employees if unit is None or e.unit == unit}
    latest = {k: v for k, v in latest_drawn_up(cycles).items() if k in who}
    people = [person_needs(c, who[eid], rules, below, areas) for eid, c in sorted(latest.items())]
    low: dict[str, int] = defaultdict(int)
    seen: dict[str, int] = defaultdict(int)
    for c in latest.values():
        for cid, pts in c.scores.items():
            seen[cid] += 1
            low[cid] += pts < below
    ranking = sorted((RankItem(cid, rules.criterion_name(cid), areas.get(cid, rules.criterion_name(cid)), low[cid],
                               seen[cid]) for cid in seen if low[cid]),
                     key=lambda r: (-r.low_scores, r.criterion))
    return [p for p in people if p.needs], ranking


def template_recommendation(ranking: Sequence[RankItem], limit: int = 3) -> str:
    if not ranking:
        return "Brak ocen cząstkowych poniżej progu – nie ma wspólnych potrzeb szkoleniowych do zaplanowania."
    top = "; ".join(f"{r.area} (kryterium „{r.criterion}”: {r.low_scores} "
                    f"{'osoba' if r.low_scores == 1 else 'osoby' if r.low_scores < 5 else 'osób'})"
                    for r in ranking[:limit])
    return (f"Najwięcej niskich ocen dotyczy: {top}. Zaplanuj w pierwszej kolejności szkolenia w tych obszarach "
            "i uwzględnij je w indywidualnych programach rozwoju zawodowego.")


def to_csv(people: Sequence[PersonNeeds]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["pracownik", "komorka", "kryterium", "ocena_czastkowa", "obszar_szkoleniowy", "wnioski_iprz"])
    for p in people:
        for n in p.needs:
            w.writerow([p.name, p.unit, n.criterion, n.score, n.area, p.iprz])
    return buf.getvalue()
