"""Deleting a person's data (KPRM use case "zakończenie: usunięcie danych pracownika").

After the employment ended the person's working data leaves the system, but the evaluations stay in the archive:
they are part of the personnel file (§ 6 ust. 3, § 12 ust. 2 of the regulation) and are kept 10 years from the end
of the year the employment ended (art. 94 pkt 9b of the Labour Code, app/application/archive.py). So:
- blocked while the person still evaluates anyone, or while an evaluation of theirs is not closed (drawn up and
  waiting for the acknowledgement, the objection period running, an objection pending),
- every closed evaluation is frozen in the archive first,
- unfinished cycles (no evaluation drawn up – nothing for the personnel file) and the working material are removed,
- the directory keeps only a record without personal data (id, office, sheet, end of employment, removal date):
  the archive's retention is counted from it, and the ids of everyone else stay stable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

from app.domain.cycle import EvaluationCycle, Status
from app.domain.employee import Employee

DRAWN_UP = (Status.EVALUATION_DONE, Status.ACKNOWLEDGED, Status.OBJECTION)


@dataclass
class RemovalPlan:
    employee_id: str
    employment_end: date | None
    blockers: list[str] = field(default_factory=list)
    archive: list[str] = field(default_factory=list)  # closed evaluations: frozen before the data goes
    discard: list[str] = field(default_factory=list)  # cycles without an evaluation drawn up: removed

    @property
    def ok(self) -> bool:
        return not self.blockers


def plan_removal(person: Employee, people: Iterable[Employee], cycles: Iterable[EvaluationCycle],
                 closed: Callable[[EvaluationCycle], bool], employment_end: date | None, today: date,
                 name_of: Callable[[str], str]) -> RemovalPlan:
    end = employment_end or person.employment_end
    plan = RemovalPlan(person.id, end)
    if person.removed_on:
        plan.blockers.append(f"Dane tej osoby zostały już usunięte ({person.removed_on:%d.%m.%Y}).")
        return plan
    if end is None:
        plan.blockers.append("Podaj datę ustania stosunku pracy – od niej liczy się okres przechowywania ocen "
                             "w archiwum (10 lat od końca roku, art. 94 pkt 9b Kodeksu pracy).")
    elif end > today:
        plan.blockers.append(f"Stosunek pracy ustaje {end:%d.%m.%Y} – dane można usunąć dopiero po tej dacie.")
    subordinates = sorted(name_of(e.id) for e in people if e.evaluator_id == person.id and e.removed_on is None)
    if subordinates:
        plan.blockers.append("Ta osoba jest oceniającym: " + ", ".join(subordinates) + ". Najpierw zmień ich "
                             "oceniającego (Zmiana oceniającego albo edycja pracownika).")
    mine = [c for c in cycles if c.employee_id == person.id]
    for c in cycles:
        if c.evaluator_id == person.id and c.employee_id != person.id and c.status not in (Status.ACKNOWLEDGED,
                                                                                          Status.OBJECTION):
            plan.blockers.append(f"Prowadzi ocenę w toku ({name_of(c.employee_id)}) – zmień oceniającego.")
    for c in mine:
        if c.status in DRAWN_UP:
            if closed(c):
                plan.archive.append(c.id)
            else:
                plan.blockers.append(f"Ocena sporządzona {c.evaluated_on:%d.%m.%Y} nie jest zamknięta (czeka na "
                                     "zapoznanie, biegnie termin sprzeciwu albo sprzeciw jest rozpatrywany)."
                                     if c.evaluated_on else "Ocena w toku postępowania sprzeciwowego.")
        else:
            plan.discard.append(c.id)
    return plan


def anonymised(person: Employee, employment_end: date, today: date) -> Employee:
    """The record that stays in the directory: no name, no contact, no position – only what the archive needs."""
    return Employee(id=person.id, first_name="", last_name="(dane usunięte)", office=person.office, unit="",
                    position="", sheet=person.sheet, evaluator_id=None, employment_end=employment_end,
                    removed_on=today)
