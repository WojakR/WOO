"""Archive and retention (spec, point 4: kept for the whole employment and after it, as the law requires).

- A closed evaluation – acknowledged, and the objection period over (or the objection decided and not upheld) –
  is frozen once: an immutable JSON snapshot + the PDF of the sheet, each with its SHA-256. Freezing again
  returns the stored record; it is never rewritten (a changed cycle afterwards does not change the archive).
- Retention (config/ustawienia_urzedu.json "archiwum"): the evaluation is part of the personnel file (§ 6 ust. 3,
  § 12 ust. 2 of the regulation) – 10 years from the end of the calendar year in which the employment ended
  (art. 94 pkt 9b of the Labour Code). The evaluator's working notes are not personnel records: a shorter period
  after the evaluation closed (proposal: 12 months).
- Nothing is deleted automatically: the review lists records past their retention for HR; deleting needs the
  administrator's explicit approval.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from app.domain.calendar import WorkingCalendar, add_months
from app.domain.cycle import EvaluationCycle, Status
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.errors import InvalidTransition, NotFound, ValidationError
from app.domain.rulebook import RuleBook


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


@dataclass(frozen=True)
class Frozen:
    id: int | None
    cycle_id: str
    employee_id: str
    frozen_on: date
    snapshot: str
    snapshot_sha256: str
    pdf: bytes
    pdf_sha256: str

    def intact(self) -> bool:
        """Both checksums still match the stored content."""
        return sha256(self.snapshot) == self.snapshot_sha256 and sha256(self.pdf) == self.pdf_sha256


class ArchiveStore(Protocol):
    def get(self, cycle_id: str) -> Frozen | None: ...

    def by_id(self, record_id: int) -> Frozen | None: ...

    def add(self, record: Frozen) -> Frozen: ...

    def all(self) -> list[Frozen]: ...

    def delete(self, record_id: int) -> None: ...


def is_closed(c: EvaluationCycle, rules: RuleBook, cal: WorkingCalendar, today: date,
              absences: Sequence[Absence] = ()) -> bool:
    """Acknowledged, and either the objection was decided and not upheld, or the period for it is over."""
    if c.status is not Status.ACKNOWLEDGED or c.acknowledged_on is None:
        return False
    if c.objection_decision == "NIEUWZGLEDNIONY" and c.objection_decided_on:
        return True
    deadline = c.objection_deadline(rules, cal, list(absences))
    return deadline is not None and today > deadline


@dataclass(frozen=True)
class ReviewItem:
    kind: str  # "AKTA" (frozen evaluation) | "NOTATKI" (evaluator's working notes of a closed cycle)
    record_id: int | None
    cycle_id: str
    employee_id: str
    due: date  # retention ended on this day
    reason: str


def records_retention_end(employment_end: date, years: int) -> date:
    """10 years counted from the end of the calendar year in which the employment ended."""
    return date(employment_end.year + years, 12, 31)


class ArchiveService:
    def __init__(self, store: ArchiveStore, encode: Callable[[EvaluationCycle], str],
                 render_pdf: Callable[[EvaluationCycle], bytes], settings: Mapping):
        self.store = store
        self.encode = encode
        self.render_pdf = render_pdf
        self.settings = settings

    def freeze(self, c: EvaluationCycle, today: date) -> Frozen:
        existing = self.store.get(c.id)
        if existing is not None:
            return existing  # immutable: freezing again never rewrites the archive
        snap, pdf = self.encode(c), self.render_pdf(c)
        return self.store.add(Frozen(None, c.id, c.employee_id, today, snap, sha256(snap), pdf, sha256(pdf)))

    def freeze_closed(self, cycles: Iterable[EvaluationCycle], closed: Callable[[EvaluationCycle], bool],
                      today: date) -> list[Frozen]:
        """Freeze every closed evaluation not archived yet; returns the new records."""
        out = []
        for c in cycles:
            if self.store.get(c.id) is None and closed(c):
                out.append(self.freeze(c, today))
        return out

    def review(self, employees: Mapping[str, Employee], cycles: Mapping[str, EvaluationCycle],
               notes_count: Callable[[str], int], today: date) -> list[ReviewItem]:
        """Records past their retention, for HR to decide – nothing is deleted here."""
        years = int(self.settings.get("akta_lat_od_konca_roku_ustania_zatrudnienia", 10))
        months = int(self.settings.get("notatki_robocze_miesiecy_po_zakonczeniu", 12))
        basis = self.settings.get("podstawa", "art. 94 pkt 9b Kodeksu pracy")
        out = []
        for r in self.store.all():
            emp = employees.get(r.employee_id)
            if emp is None or emp.employment_end is None:
                continue  # still employed (or unknown): kept for the whole employment
            due = records_retention_end(emp.employment_end, years)
            if today > due:
                out.append(ReviewItem("AKTA", r.id, r.cycle_id, r.employee_id, due,
                                      f"{years} lat od końca roku ustania zatrudnienia ({emp.employment_end:%d.%m.%Y}) "
                                      f"– {basis}"))
        for cid, c in cycles.items():
            if c.acknowledged_on is None or not notes_count(cid):
                continue
            due = add_months(c.acknowledged_on, months)
            if today > due and self.store.get(cid) is not None:
                out.append(ReviewItem("NOTATKI", None, cid, c.employee_id, due,
                                      f"notatki robocze ({notes_count(cid)}): {months} mies. od zakończenia oceny"))
        return sorted(out, key=lambda i: i.due)

    def delete(self, record_id: int, approved: bool, due_items: Sequence[ReviewItem]) -> Frozen:
        """Only a record past its retention, only with the administrator's explicit approval."""
        record = self.store.by_id(record_id)
        if record is None:
            raise NotFound(f"Nie ma rekordu archiwum {record_id}.")
        if not any(i.kind == "AKTA" and i.record_id == record_id for i in due_items):
            raise InvalidTransition("Okres przechowywania tego rekordu jeszcze nie minął – nie można go usunąć.")
        if not approved:
            raise ValidationError(["Usunięcie rekordu archiwum wymaga zatwierdzenia przez administratora "
                                   "(„zatwierdzam”: true)."])
        self.store.delete(record_id)
        return record
