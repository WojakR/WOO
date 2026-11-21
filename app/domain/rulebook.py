"""Rule book: every value that comes from regulations, parsed from the KPRM data dictionaries.

The domain never reads files. `RuleBook.from_kprm()` takes the already-loaded dictionaries
(reguly.json, arkusze.json, kryteria.json) so the parsing stays pure and testable;
the infrastructure adapter feeds it from `backend.kprm`.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .errors import ValidationError


@dataclass(frozen=True)
class Criterion:
    id: str
    number: int
    name: str
    indicators: tuple[str, ...]


@dataclass(frozen=True)
class LevelBand:
    """Average in (lower_exclusive, upper_inclusive] -> level. lower_exclusive=None means no lower bound."""

    lower_exclusive: Fraction | None
    upper_inclusive: Fraction
    level: str

    def contains(self, value: Fraction) -> bool:
        return (self.lower_exclusive is None or value > self.lower_exclusive) and value <= self.upper_inclusive


@dataclass(frozen=True)
class RuleBook:
    scale: dict[int, str]  # points -> level name, e.g. {1: "znacznie poniżej oczekiwań", ...}
    level_bands: tuple[LevelBand, ...]
    positive_levels: frozenset[str]
    forbidden_partial_score: int  # any partial score equal to this makes the evaluation negative
    justification_required_if_negative: bool
    iprz_required: bool
    cycle_months: int
    criteria_days: int
    criteria_days_after_negative: int
    absence_extends_after_months: int
    reevaluation_after_negative_months: int
    objection_days: int
    objection_review_days: int
    labour_court_days: int
    position_change_threshold_months: int  # art. 81 ust. 6 / § 9 ust. 1: "6 miesięcy"
    position_change_criteria_days: int  # § 9 ust. 1: criteria set again within 30 days of the change
    position_change_eval_days_before: int  # § 9 ust. 2: evaluation not earlier than 7 days before the change
    position_change_eval_days_after: int  # § 9 ust. 2: … and not later than 30 days after it
    max_additional_criteria: int
    additional_criteria_unique: bool
    sheets: dict[str, tuple[str, ...]]  # sheet -> mandatory criterion ids, in form order
    criteria: dict[str, Criterion]
    statuses: tuple[str, ...]
    deadline_change_after_months: int = 6  # art. 81 ust. 8: "więcej niż 6 miesięcy" since the last evaluation
    # consequences of consecutive evaluations (reguly.json "skutki_ocen")
    termination_after_negatives: int = 2  # art. 71 ust. 1 pkt 1 (civil servants only)
    termination_notice_months: int = 3
    termination_basis: str = "art. 71 ust. 1 pkt 1 ustawy o służbie cywilnej"
    max_grade: int = 9
    promotion_basis: str = "art. 89 ust. 1 ustawy o służbie cywilnej"
    mandatory_grade_after: int = 2  # art. 89 ust. 2: two consecutive evaluations on one of the two top levels
    mandatory_grade_levels: frozenset[str] = frozenset({"powyżej oczekiwań", "znacznie powyżej oczekiwań"})
    mandatory_grade_basis: str = "art. 89 ust. 2 ustawy o służbie cywilnej"
    mandatory_grade_days: int = 30  # … the next grade within 30 days of acknowledging the evaluation

    @classmethod
    def from_kprm(cls, rules: dict, sheets: dict, criteria: dict[str, dict]) -> RuleBook:
        positive = rules["ocena_pozytywna_gdy"]
        terms = rules["terminy"]
        return cls(
            scale={s["punkty"]: s["poziom"] for s in rules["skala_ocen_czastkowych"]},
            level_bands=tuple(
                LevelBand(
                    lower_exclusive=None if b["od_wylacznie"] is None else Fraction(str(b["od_wylacznie"])),
                    upper_inclusive=Fraction(str(b["do_wlacznie"])),
                    level=b["poziom"],
                )
                for b in rules["poziom_ogolny_ze_sredniej"]
            ),
            positive_levels=frozenset(positive["poziom_ogolny_w"]),
            forbidden_partial_score=positive["i_zadna_ocena_czastkowa_rowna"],
            justification_required_if_negative=rules["uzasadnienie"]["obowiazkowe_przy_negatywnej"],
            # NB: the key in reguly.json is spelled "ipzr"; the form calls it IPRZ.
            iprz_required=rules["wnioski_ipzr_obowiazkowe"],
            cycle_months=terms["ocena_co_miesiecy"],
            criteria_days=terms["wyznaczenie_kryteriow_dni_od_poprzedniej_oceny_lub_zatrudnienia"],
            criteria_days_after_negative=terms["wyznaczenie_kryteriow_dni_po_negatywnej"],
            absence_extends_after_months=terms["nieobecnosc_przedluzajaca_termin_powyzej_miesiecy"],
            reevaluation_after_negative_months=terms["ponowna_ocena_po_negatywnej_miesiecy"],
            objection_days=terms["sprzeciw_dni_od_zapoznania"],
            objection_review_days=terms["rozpatrzenie_sprzeciwu_dni"],
            labour_court_days=terms["odwolanie_do_sadu_pracy_dni"],
            position_change_threshold_months=terms["zmiana_stanowiska_prog_miesiecy"],
            position_change_criteria_days=terms["zmiana_stanowiska_ponowne_kryteria_dni"],
            position_change_eval_days_before=terms["zmiana_stanowiska_ocena_najwczesniej_dni_przed"],
            position_change_eval_days_after=terms["zmiana_stanowiska_ocena_najpozniej_dni_po"],
            max_additional_criteria=sheets["max_kryteriow_dodatkowych"],
            additional_criteria_unique=sheets["kryteria_dodatkowe_bez_powtorzen"],
            sheets={k: tuple(v["kryteria_obowiazkowe"]) for k, v in sheets["arkusze"].items()},
            criteria={
                cid: Criterion(cid, c["nr"], c["nazwa"], tuple(c["wskazniki_behawioralne"]))
                for cid, c in criteria.items()
            },
            statuses=tuple(rules["statusy_procesu"]),
            deadline_change_after_months=terms["zmiana_terminu_mozliwa_po_miesiacach_od_ostatniej_oceny"],
            **_consequences(rules.get("skutki_ocen") or {}, terms),
        )

    def mandatory(self, sheet: str) -> tuple[str, ...]:
        try:
            return self.sheets[sheet]
        except KeyError:
            raise ValidationError([f"Nieznany arkusz „{sheet}” (dostępne: {', '.join(sorted(self.sheets))})."]) from None

    def criterion_name(self, cid: str) -> str:
        c = self.criteria.get(cid)
        return c.name if c else cid


def _consequences(raw: dict, terms: dict) -> dict:
    """reguly.json "skutki_ocen" -> RuleBook fields (missing keys keep the defaults above)."""
    out: dict = {}
    term = raw.get("rozwiazanie_stosunku_pracy") or {}
    if "negatywnych_ocen_z_rzedu" in term:
        out["termination_after_negatives"] = int(term["negatywnych_ocen_z_rzedu"])
    if "okres_wypowiedzenia_miesiecy" in term:
        out["termination_notice_months"] = int(term["okres_wypowiedzenia_miesiecy"])
    if term.get("podstawa"):
        out["termination_basis"] = term["podstawa"]
    grade = raw.get("stopien_sluzbowy") or {}
    if "najwyzszy_stopien" in grade:
        out["max_grade"] = int(grade["najwyzszy_stopien"])
    if grade.get("podstawa_wniosku"):
        out["promotion_basis"] = grade["podstawa_wniosku"]
    if "obligatoryjny_po_ocenach_z_rzedu" in grade:
        out["mandatory_grade_after"] = int(grade["obligatoryjny_po_ocenach_z_rzedu"])
    if grade.get("obligatoryjny_poziomy"):
        out["mandatory_grade_levels"] = frozenset(grade["obligatoryjny_poziomy"])
    if grade.get("podstawa_obligatoryjnego"):
        out["mandatory_grade_basis"] = grade["podstawa_obligatoryjnego"]
    if "obligatoryjny_stopien_dni_od_zapoznania" in terms:
        out["mandatory_grade_days"] = int(terms["obligatoryjny_stopien_dni_od_zapoznania"])
    return out
