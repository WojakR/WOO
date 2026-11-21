"""Which sheet (A/B/C) fits a position – § 3 ust. 2–4 of the regulation.

A – head of the office, B – a position managing people directly, C – everything else. The mapping (field ->
sheet, reasons) is data (arkusze.json["dobor_arkusza"]), not code; the first rule whose field is true wins.
Missing HR data never blocks the process: C is suggested with a warning, HR checks it before the criteria.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .employee import Employee

FIELDS = {"kierownik_urzedu": "is_office_head", "zarzadza_ludzmi": "manages_people"}


@dataclass(frozen=True)
class SheetSuggestion:
    sheet: str
    reason: str
    warning: str | None = None


def suggest_sheet(employee: Employee, mapping: Mapping) -> SheetSuggestion:
    """`mapping` = arkusze.json["dobor_arkusza"]."""
    values = {key: getattr(employee, attr) for key, attr in FIELDS.items()}
    for rule in mapping["reguly"]:
        if values.get(rule["pole"]) is True:
            return SheetSuggestion(rule["arkusz"], rule["powod"])
    if any(values.get(rule["pole"]) is None for rule in mapping["reguly"]):
        missing = mapping["brak_danych"]
        return SheetSuggestion(missing["arkusz"], missing["ostrzezenie"], warning=missing["ostrzezenie"])
    rest = mapping["pozostali"]
    return SheetSuggestion(rest["arkusz"], rest["powod"])
