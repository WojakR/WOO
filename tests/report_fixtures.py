"""Shared set of cycles for the report tests: two units, a fixed clock, every stage of the process."""
from datetime import date

from app.application.use_cases import EvaluationService
from app.domain.employee import Employee
from app.infrastructure.kprm_adapter import kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository

BOSS_A, BOSS_B = "szef.a", "szef.b"


class Directory:
    def __init__(self, people):
        self._by_id = {e.id: e for e in people}

    def get(self, eid):
        return self._by_id.get(eid)

    def all(self):
        return list(self._by_id.values())


def person(eid, unit, boss, sheet="C"):
    return Employee(eid, eid.split(".")[0].title(), eid.split(".")[-1].title(), "Urząd Testowy", unit, "specjalista",
                    sheet, boss)


def build():
    """Unit A: a1..a6 (boss szef.a), unit B: b1..b2 (boss szef.b). Started 2.03.2026 (criteria by 1.04.2026).

    a1..a5: drawn up 8.06.2026 (on time, deadline 2.03.2028) and acknowledged – scores below;
    a6: criteria never set -> overdue on 25.05.2026; b1: criteria set, waiting for confirmation; b2: no cycle.
    """
    people = [person(f"a.{i}", "Wydział A", BOSS_A) for i in range(1, 7)] + \
             [person("b.1", "Wydział B", BOSS_B), person("b.2", "Wydział B", BOSS_B),
              person(BOSS_A, "Wydział A", None, "B"), person(BOSS_B, "Wydział B", None, "B")]
    clock = FixedClock(date(2026, 3, 2))
    svc = EvaluationService(kprm_rulebook(), InMemoryCycleRepository(), Directory(people), clock)
    rules = svc.rules
    ids = {}
    for e in people:
        if e.evaluator_id and e.id != "b.2":
            ids[e.id] = svc.start_cycle(e.id, start_date=date(2026, 3, 2)).id
    clock.set(date(2026, 3, 20))
    for i in range(1, 6):
        svc.set_criteria(ids[f"a.{i}"], BOSS_A, [])
        svc.confirm_criteria(ids[f"a.{i}"], f"a.{i}")
    svc.set_criteria(ids["b.1"], BOSS_B, [])
    clock.set(date(2026, 6, 8))
    # a.1 .. a.5 scores: komunikacja low for a.1–a.3; rzetelnosc low for a.1
    for i in range(1, 6):
        cid = ids[f"a.{i}"]
        svc.record_review_meeting(cid, BOSS_A)
        crit = svc.cycles.get(cid).criteria_ids(rules)
        scores = {c: 7 for c in crit}
        if i <= 3:
            scores["komunikacja"] = 3
        if i == 1:
            scores["rzetelnosc"] = 1
        svc.submit_evaluation(cid, BOSS_A, scores=scores, justification="Uzasadnienie." if i == 1 else "",
                              iprz_conclusions=f"Szkolenie {i}.")
    clock.set(date(2026, 6, 10))
    for i in range(1, 6):
        svc.acknowledge(ids[f"a.{i}"], f"a.{i}")
    return svc, clock, people, ids
