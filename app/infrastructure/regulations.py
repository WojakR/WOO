"""Requirements of the regulation as data the office administrator can change when the law is amended.

The defaults come from server/data/kprm/reguly.json (the regulation of 4.04.2016 and the Civil Service Act).
Overrides are kept in the application state (database) with who/when/why, and every deadline is computed from
the current values – no term is written into the code. Only numeric terms and the additional-criteria limit are
editable; the scale, levels and the positive-outcome rule are shown read-only (changing them means a new form).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from app.domain.errors import ValidationError
from app.domain.rulebook import RuleBook
from backend import kprm


@dataclass(frozen=True)
class EditableRule:
    key: str  # key in reguly.json["terminy"] (or "max_kryteriow_dodatkowych")
    label: str
    unit: str  # "dni" | "miesięcy" | "kryteria"
    basis: str  # legal basis shown next to the value
    low: int
    high: int


EDITABLE: tuple[EditableRule, ...] = (
    EditableRule("ocena_co_miesiecy", "Ocena okresowa co", "miesięcy", "art. 81 ust. 4 ustawy", 6, 60),
    EditableRule("wyznaczenie_kryteriow_dni_od_poprzedniej_oceny_lub_zatrudnienia",
                 "Wyznaczenie kryteriów od poprzedniej oceny / zatrudnienia", "dni", "§ 7 pkt 1 rozporządzenia", 1, 120),
    EditableRule("wyznaczenie_kryteriow_dni_po_negatywnej", "Wyznaczenie kryteriów po ocenie negatywnej", "dni",
                 "§ 7 pkt 2 rozporządzenia", 1, 60),
    EditableRule("ponowna_ocena_po_negatywnej_miesiecy", "Ponowna ocena po ocenie negatywnej", "miesięcy",
                 "art. 81 ust. 9 ustawy", 1, 24),
    EditableRule("nieobecnosc_przedluzajaca_termin_powyzej_miesiecy",
                 "Nieobecność przedłużająca termin oceny – dłuższa niż", "miesięcy", "art. 81 ust. 7 ustawy", 1, 12),
    EditableRule("zmiana_terminu_mozliwa_po_miesiacach_od_ostatniej_oceny",
                 "Wniosek o zmianę terminu oceny po", "miesięcy", "art. 81 ust. 8 ustawy", 1, 24),
    EditableRule("zmiana_stanowiska_ponowne_kryteria_dni", "Nowe kryteria po zmianie stanowiska", "dni",
                 "§ 9 ust. 1 rozporządzenia", 1, 120),
    EditableRule("zmiana_stanowiska_prog_miesiecy", "Zmiana stanowiska – próg", "miesięcy", "art. 81 ust. 6 ustawy",
                 1, 24),
    EditableRule("zmiana_stanowiska_ocena_najwczesniej_dni_przed", "Ocena przy zmianie stanowiska – najwcześniej przed",
                 "dni", "§ 9 ust. 2 rozporządzenia", 0, 60),
    EditableRule("zmiana_stanowiska_ocena_najpozniej_dni_po", "Ocena przy zmianie stanowiska – najpóźniej po", "dni",
                 "§ 9 ust. 2 rozporządzenia", 1, 120),
    EditableRule("sprzeciw_dni_od_zapoznania", "Sprzeciw od oceny", "dni", "art. 83 ust. 1 ustawy", 1, 60),
    EditableRule("rozpatrzenie_sprzeciwu_dni", "Rozpatrzenie sprzeciwu", "dni", "art. 83 ust. 3 ustawy", 1, 60),
    EditableRule("odwolanie_do_sadu_pracy_dni", "Odwołanie do sądu pracy", "dni", "art. 83 ust. 5 ustawy", 1, 60),
    EditableRule("obligatoryjny_stopien_dni_od_zapoznania", "Obligatoryjny stopień służbowy", "dni",
                 "art. 89 ust. 2 ustawy", 1, 120),
    EditableRule("max_kryteriow_dodatkowych", "Kryteria dodatkowe – najwyżej", "kryteria", "§ 5 ust. 2 rozporządzenia",
                 0, 10),
)
BY_KEY = {r.key: r for r in EDITABLE}


def defaults() -> dict[str, int]:
    terms = kprm.rules()["terminy"]
    out = {k: int(terms[k]) for k in terms if k in BY_KEY}
    out["max_kryteriow_dodatkowych"] = int(kprm.sheets()["max_kryteriow_dodatkowych"])
    return out


def validate(values: dict[str, int]) -> dict[str, int]:
    problems, out = [], {}
    for key, value in values.items():
        rule = BY_KEY.get(key)
        if rule is None:
            problems.append(f"Nieznany parametr: {key}.")
        elif not isinstance(value, int) or not rule.low <= value <= rule.high:
            problems.append(f"{rule.label}: wartość {value} poza zakresem {rule.low}–{rule.high} {rule.unit}.")
        else:
            out[key] = value
    if problems:
        raise ValidationError(problems)
    return out


def rulebook(overrides: dict[str, int] | None = None) -> RuleBook:
    """The rule book with the administrator's changes applied (none -> exactly reguly.json)."""
    rules, sheets = copy.deepcopy(kprm.rules()), copy.deepcopy(kprm.sheets())
    for key, value in (overrides or {}).items():
        if key == "max_kryteriow_dodatkowych":
            sheets[key] = value
        elif key in rules["terminy"]:
            rules["terminy"][key] = value
    return RuleBook.from_kprm(rules, sheets, kprm.criteria())


def requirements(rb: RuleBook) -> list[tuple[str, str, str]]:
    """Read-only summary of what the regulation requires (title, text, legal basis), from the current rules."""
    scale = ", ".join(f"{p} – {name}" for p, name in sorted(rb.scale.items()))
    bands = "; ".join(
        f"{'od ' + str(min(rb.scale)) if b.lower_exclusive is None else 'powyżej ' + format(float(b.lower_exclusive), 'g')}"
        f" do {float(b.upper_inclusive):g}: {b.level}" for b in rb.level_bands)
    sheets = "; ".join(f"arkusz {s}: {', '.join(rb.criterion_name(c) for c in ids)}" for s, ids in rb.sheets.items())
    return [
        ("Skala ocen cząstkowych", scale, "§ 11 ust. 1 pkt 1 rozporządzenia"),
        ("Poziom oceny ze średniej", bands, "§ 11 ust. 1 pkt 2 rozporządzenia"),
        ("Ocena pozytywna",
         f"poziom co najmniej „na poziomie oczekiwań” i żadna ocena cząstkowa równa {rb.forbidden_partial_score}",
         "§ 11 ust. 1 pkt 3–4 rozporządzenia"),
        ("Uzasadnienie", "obowiązkowe przy ocenie negatywnej, opcjonalne przy pozytywnej", "§ 11 ust. 3–4 rozporządzenia"),
        ("Wnioski do IPRZ", "obowiązkowe w każdej ocenie", "art. 81 ust. 5 ustawy"),
        ("Kryteria obowiązkowe", sheets, "§ 4 rozporządzenia"),
        ("Kryteria dodatkowe", f"najwyżej {rb.max_additional_criteria}, bez powtórzeń z obowiązkowymi",
         "§ 5 ust. 2 rozporządzenia"),
        ("Liczenie terminów", "; ".join(kprm.rules().get("liczenie_terminow", [])), "Kodeks cywilny, art. 111–115"),
    ]
