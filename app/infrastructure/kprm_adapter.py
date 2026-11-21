"""Builds domain objects from the KPRM data, read only through backend.kprm."""
from __future__ import annotations

from datetime import date
from functools import lru_cache

from app.domain.cycle import PreviousEvaluation
from app.domain.employee import Employee
from app.domain.rulebook import RuleBook
from backend import kprm


@lru_cache
def kprm_rulebook() -> RuleBook:
    return RuleBook.from_kprm(kprm.rules(), kprm.sheets(), kprm.criteria())


def _employee(raw: dict) -> Employee:
    prev = raw.get("poprzednia_ocena")
    return Employee(
        id=raw["id"],
        first_name=raw["imie"],
        last_name=raw["nazwisko"],
        office=raw.get("urzad", ""),
        unit=raw.get("komorka", ""),
        position=raw.get("stanowisko", ""),
        sheet=raw["arkusz"],
        evaluator_id=raw.get("oceniajacy"),
        civil_servant=bool(raw.get("urzednik_mianowany", False)),
        grade=raw.get("stopien_sluzbowy"),
        grade_since=date.fromisoformat(raw["data_przyznania_stopnia"]) if raw.get("data_przyznania_stopnia") else None,
        manages_people=raw.get("zarzadza_ludzmi", raw.get("kieruje_zespolem")),
        is_office_head=raw.get("kierownik_urzedu"),
        email=raw.get("email"),
        employment_end=date.fromisoformat(raw["data_ustania_zatrudnienia"]) if raw.get("data_ustania_zatrudnienia") else None,
        previous_evaluation=PreviousEvaluation(
            outcome=prev.get("ocena"),
            level=prev.get("poziom"),
            date=date.fromisoformat(prev["data"]) if prev.get("data") else None,
            acknowledged=date.fromisoformat(prev["data_zapoznania"]) if prev.get("data_zapoznania") else None,
        ) if prev else None,
    )


class KprmEmployeeDirectory:
    """EmployeeDirectory backed by pracownicy.json (fictional sample people)."""

    def __init__(self):
        self._by_id = {eid: _employee(e) for eid, e in kprm.employees().items()}

    def get(self, employee_id: str) -> Employee | None:
        return self._by_id.get(employee_id)

    def all(self) -> list[Employee]:
        return list(self._by_id.values())

    def upsert(self, employees: list[Employee]) -> None:
        """People from the HR import: same id = updated, new id = added (order of the directory kept)."""
        for e in employees:
            self._by_id[e.id] = e
