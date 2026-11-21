"""Requirements of the regulation as data the office administrator can change when the law is amended.

The defaults come from server/data/kprm/reguly.json (the regulation of 4.04.2016 and the Civil Service Act).
Overrides are kept in the application state (database) with who/when/why, and every deadline is computed from
the current values – no term is written into the code. Only numeric terms and the additional-criteria limit are
editable; the scale, levels and the positive-outcome rule are shown read-only (changing them means a new form).
"""
from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from app.domain.errors import ValidationError
from app.domain.rulebook import Criterion, RuleBook
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


def rulebook(overrides: dict[str, int] | None = None, criteria: dict[str, dict] | None = None) -> RuleBook:
    """The rule book with the administrator's changes applied (none -> exactly reguly.json).
    `criteria`: {id: {"nazwa": ..., "wskazniki": [...], "dostepne": bool}} – edits of the criteria list."""
    rules, sheets = copy.deepcopy(kprm.rules()), copy.deepcopy(kprm.sheets())
    for key, value in (overrides or {}).items():
        if key == "max_kryteriow_dodatkowych":
            sheets[key] = value
        elif key in rules["terminy"]:
            rules["terminy"][key] = value
    rb = RuleBook.from_kprm(rules, sheets, kprm.criteria())
    if not criteria:
        return rb
    crit = dict(rb.criteria)
    for cid, ch in criteria.items():
        old = crit[cid]
        crit[cid] = Criterion(cid, old.number, ch.get("nazwa") or old.name,
                              tuple(ch["wskazniki"]) if ch.get("wskazniki") else old.indicators)
    off = frozenset(cid for cid, ch in criteria.items() if ch.get("dostepne") is False)
    return dataclasses.replace(rb, criteria=crit, unavailable_additional=off)


# ---------------------------------------------------------------- versions (an amendment never changes running cycles)

CRITERION_FIELDS = ("nazwa", "wskazniki", "dostepne")


@dataclass(frozen=True)
class RuleVersion:
    """One version of the requirements: the full set of the office's changes against reguly.json, in force from
    `valid_from`. Version 0 = the published regulation (implicit, in force since forever)."""
    id: int
    valid_from: date
    values: dict[str, int] = field(default_factory=dict)
    criteria: dict[str, dict] = field(default_factory=dict)
    description: str = "rozporządzenie w brzmieniu opublikowanym (reguly.json)"
    author: str = ""
    created_on: date | None = None


PUBLISHED = RuleVersion(0, date.min)


def validate_criteria(changes: dict[str, dict]) -> dict[str, dict]:
    """Edits of the criteria list: known ids, a name, indicators as a list; a criterion mandatory in some sheet
    cannot be withdrawn (it is in the form by law)."""
    problems, out = [], {}
    known = kprm.criteria()
    mandatory = {cid for s in kprm.sheets()["arkusze"].values() for cid in s["kryteria_obowiazkowe"]}
    for cid, ch in changes.items():
        if cid not in known:
            problems.append(f"Nieznane kryterium: {cid}.")
            continue
        if not isinstance(ch, dict) or any(k not in CRITERION_FIELDS for k in ch):
            problems.append(f"{cid}: dozwolone pola zmiany: {', '.join(CRITERION_FIELDS)}.")
            continue
        clean: dict = {}
        if "nazwa" in ch:
            if not isinstance(ch["nazwa"], str) or not ch["nazwa"].strip():
                problems.append(f"{cid}: nazwa kryterium nie może być pusta.")
                continue
            clean["nazwa"] = ch["nazwa"].strip()
        if "wskazniki" in ch:
            items = ch["wskazniki"]
            if not isinstance(items, list) or not items or not all(isinstance(x, str) and x.strip() for x in items):
                problems.append(f"{cid}: wskaźniki behawioralne to niepusta lista tekstów.")
                continue
            clean["wskazniki"] = [x.strip() for x in items]
        if "dostepne" in ch:
            if not isinstance(ch["dostepne"], bool):
                problems.append(f"{cid}: „dostepne” musi być true albo false.")
                continue
            if ch["dostepne"] is False and cid in mandatory:
                problems.append(f"Kryterium „{known[cid]['nazwa']}” jest obowiązkowe w arkuszu – nie można go wycofać.")
                continue
            clean["dostepne"] = ch["dostepne"]
        out[cid] = clean
    if problems:
        raise ValidationError(problems)
    return out


class RuleVersions:
    """All versions; which one is in force on a day; the rule book of each (cached)."""

    def __init__(self, versions: list[RuleVersion] | None = None):
        self.versions = sorted(versions or [], key=lambda v: v.id)
        self._books: dict[int, RuleBook] = {}

    def all(self) -> list[RuleVersion]:
        return [PUBLISHED, *self.versions]

    def get(self, version_id: int | None) -> RuleVersion:
        return next((v for v in self.all() if v.id == version_id), PUBLISHED)

    def at(self, day: date) -> RuleVersion:
        """The version in force on `day`: the latest valid_from <= day (the later entry wins on the same day)."""
        return max((v for v in self.all() if v.valid_from <= day), key=lambda v: (v.valid_from, v.id))

    def latest(self) -> RuleVersion:
        """The last decision of the office (also one coming into force later) – base for the next change."""
        return max(self.all(), key=lambda v: (v.valid_from, v.id))

    def rulebook(self, version_id: int | None) -> RuleBook:
        v = self.get(version_id)
        if v.id not in self._books:
            self._books[v.id] = _cached_rulebook(_freeze(v.values), _freeze(v.criteria))
        return self._books[v.id]

    def add(self, values: dict[str, int], criteria: dict[str, dict], valid_from: date, description: str,
            author: str, today: date, replace: bool = False) -> RuleVersion:
        """New version = the latest one with these changes (or exactly them with `replace`). Not retroactive:
        in force from today at the earliest, so evaluations already running never change."""
        problems = []
        if valid_from < today:
            problems.append(f"Data wejścia w życie ({valid_from:%d.%m.%Y}) nie może być wcześniejsza niż dziś – "
                            "zmiana przepisów nie działa wstecz na trwające oceny.")
        if not description.strip():
            problems.append("Opisz zmianę (np. podstawa prawna nowelizacji).")
        if problems:
            raise ValidationError(problems)
        values, criteria = validate(values), validate_criteria(criteria)
        base = PUBLISHED if replace else self.latest()
        merged_crit = {k: dict(v) for k, v in base.criteria.items()}
        for cid, ch in criteria.items():
            merged_crit.setdefault(cid, {}).update(ch)
        default = defaults()
        merged = {k: v for k, v in {**base.values, **values}.items() if v != default[k]}
        v = RuleVersion(max((x.id for x in self.all()), default=0) + 1, valid_from, merged, merged_crit,
                        description.strip(), author, today)
        self.versions.append(v)
        return v

    def diff(self, v: RuleVersion) -> tuple[list[tuple[str, int, int]], list[tuple[str, str, object, object]]]:
        """What `v` changes against the version before it: (key, old, new) and (criterion, field, old, new)."""
        before = [x for x in self.all() if (x.valid_from, x.id) < (v.valid_from, v.id)]
        prev = max(before, key=lambda x: (x.valid_from, x.id)) if before else PUBLISHED
        default = defaults()
        old_vals, new_vals = {**default, **prev.values}, {**default, **v.values}
        values = [(k, old_vals[k], new_vals[k]) for k in default if old_vals[k] != new_vals[k]]
        crit = []
        for cid in sorted(set(prev.criteria) | set(v.criteria)):
            a, b = prev.criteria.get(cid, {}), v.criteria.get(cid, {})
            for f in CRITERION_FIELDS:
                if a.get(f) != b.get(f):
                    crit.append((cid, f, a.get(f), b.get(f)))
        return values, crit


def _freeze(d: dict) -> str:
    import json

    return json.dumps(d, sort_keys=True, ensure_ascii=False)


@lru_cache(maxsize=64)
def _cached_rulebook(values: str, criteria: str) -> RuleBook:
    import json

    return rulebook(json.loads(values), json.loads(criteria))


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
