import os
import sys
from pathlib import Path

os.environ["LLM_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import kprm  # noqa: E402


def test_fourteen_criteria_with_indicators():
    crit = kprm.criteria()
    assert len(crit) == 14
    assert all(c["wskazniki_behawioralne"] for c in crit.values())
    assert crit["rzetelnosc"]["nazwa"] == "Rzetelność"


def test_sheet_mandatory_criteria_match_regulation():
    names = lambda s: [c["nazwa"] for c in kprm.mandatory_criteria(s)]  # noqa: E731
    assert len(names("A")) == 6 and "Zarządzanie strategiczne" in names("A")
    assert len(names("B")) == 5 and "Zarządzanie strategiczne" not in names("B")
    assert names("C") == ["Wykorzystywanie wiedzy i doskonalenie zawodowe", "Rzetelność",
                          "Organizacja pracy i orientacja na osiąganie celów", "Współpraca", "Komunikacja"]
    for s in "ABC":
        assert len(kprm.mandatory_criteria(s)) + len(kprm.optional_criteria(s)) == 14


def test_rules_scale_and_deadlines():
    r = kprm.rules()
    assert [x["punkty"] for x in r["skala_ocen_czastkowych"]] == [1, 3, 5, 7, 9]
    assert r["terminy"]["ocena_co_miesiecy"] == 24
    assert r["ocena_pozytywna_gdy"]["i_zadna_ocena_czastkowa_rowna"] == 1


# ---------------------------------------------------------------- data vs. regulation (rozporządzenie PRM z 4.04.2016,
# Dz. U. poz. 470) and the Act (ustawa o służbie cywilnej). Each test cites the provision it guards.

def test_criteria_list_matches_annex_1():
    # Załącznik nr 1: 14 criteria, numbered, each with its behavioural indicators
    annex = {
        1: ("Komunikacja", 4), 2: ("Kreatywność", 2), 3: ("Negocjowanie", 3),
        4: ("Organizacja pracy i orientacja na osiąganie celów", 5), 5: ("Orientacja na klienta/interesanta", 2),
        6: ("Podejmowanie decyzji i odpowiedzialność", 3), 7: ("Radzenie sobie w sytuacjach kryzysowych", 3),
        8: ("Rzetelność", 2), 9: ("Myślenie analityczne", 3), 10: ("Wykorzystywanie wiedzy i doskonalenie zawodowe", 3),
        11: ("Współpraca", 6), 12: ("Wystąpienia publiczne", 4), 13: ("Zarządzanie ludźmi", 6),
        14: ("Zarządzanie strategiczne", 3),
    }
    data = {c["nr"]: (c["nazwa"], len(c["wskazniki_behawioralne"])) for c in kprm.criteria().values()}
    assert data == annex


def test_mandatory_criteria_per_sheet_match_par_4():
    names = lambda s: [c["nazwa"] for c in kprm.mandatory_criteria(s)]  # noqa: E731
    b = ["Zarządzanie ludźmi", "Podejmowanie decyzji i odpowiedzialność",
         "Organizacja pracy i orientacja na osiąganie celów", "Współpraca", "Komunikacja"]
    assert names("A") == b + ["Zarządzanie strategiczne"]  # § 4 ust. 1
    assert names("B") == b  # § 4 ust. 2
    assert names("C") == ["Wykorzystywanie wiedzy i doskonalenie zawodowe", "Rzetelność",  # § 4 ust. 3
                          "Organizacja pracy i orientacja na osiąganie celów", "Współpraca", "Komunikacja"]


def test_additional_criteria_at_most_three_without_repeats():
    sheets = kprm.sheets()
    assert sheets["max_kryteriow_dodatkowych"] == 3  # § 5 ust. 2
    assert sheets["kryteria_dodatkowe_bez_powtorzen"] is True
    for s in "ABC":  # an additional criterion is never one of the sheet's mandatory ones
        mandatory = {c["nazwa"] for c in kprm.mandatory_criteria(s)}
        assert not mandatory & {c["nazwa"] for c in kprm.optional_criteria(s)}


def test_partial_score_scale_matches_par_11_1_pkt_1():
    scale = {x["punkty"]: x["poziom"] for x in kprm.rules()["skala_ocen_czastkowych"]}
    assert scale == {1: "znacznie poniżej oczekiwań", 3: "poniżej oczekiwań", 5: "na poziomie oczekiwań",
                     7: "powyżej oczekiwań", 9: "znacznie powyżej oczekiwań"}


def test_overall_level_bands_match_par_11_1_pkt_2():
    from fractions import Fraction

    from app.infrastructure.kprm_adapter import kprm_rulebook

    bands = kprm_rulebook().level_bands
    level = lambda avg: next(b.level for b in bands if b.contains(Fraction(avg)))  # noqa: E731
    expected = [  # "od 1 do 2", "powyżej 2 do 4", "powyżej 4 do 6", "powyżej 6 do 8", "powyżej 8 do 9"
        ("1", "znacznie poniżej oczekiwań"), ("2", "znacznie poniżej oczekiwań"),
        ("2.2", "poniżej oczekiwań"), ("4", "poniżej oczekiwań"),
        ("4.2", "na poziomie oczekiwań"), ("6", "na poziomie oczekiwań"),
        ("6.2", "powyżej oczekiwań"), ("8", "powyżej oczekiwań"),
        ("8.2", "znacznie powyżej oczekiwań"), ("9", "znacznie powyżej oczekiwań"),
    ]
    assert [(avg, level(avg)) for avg, _ in expected] == expected


def test_positive_outcome_condition_matches_par_11_1_pkt_3_4():
    cond = kprm.rules()["ocena_pozytywna_gdy"]
    assert set(cond["poziom_ogolny_w"]) == {"na poziomie oczekiwań", "powyżej oczekiwań", "znacznie powyżej oczekiwań"}
    assert cond["i_zadna_ocena_czastkowa_rowna"] == 1  # any "znacznie poniżej oczekiwań" -> negative


def test_justification_and_iprz_rules():
    r = kprm.rules()
    assert r["uzasadnienie"]["obowiazkowe_przy_negatywnej"] is True  # § 11 ust. 3
    assert r["uzasadnienie"]["opcjonalne_przy_pozytywnej"] is True  # § 11 ust. 4
    assert r["wnioski_ipzr_obowiazkowe"] is True  # § 11 ust. 1 pkt 5, art. 81 ust. 5


def test_deadlines_match_act_and_regulation():
    assert kprm.rules()["terminy"] == {
        "ocena_co_miesiecy": 24,  # art. 81 ust. 4
        "wyznaczenie_kryteriow_dni_od_poprzedniej_oceny_lub_zatrudnienia": 30,  # § 7 pkt 1
        "wyznaczenie_kryteriow_dni_po_negatywnej": 7,  # § 7 pkt 2
        "ponowna_ocena_po_negatywnej_miesiecy": 6,  # art. 81 ust. 9
        "nieobecnosc_przedluzajaca_termin_powyzej_miesiecy": 1,  # art. 81 ust. 7
        "zmiana_terminu_mozliwa_po_miesiacach_od_ostatniej_oceny": 6,  # art. 81 ust. 8
        "zmiana_stanowiska_ponowne_kryteria_dni": 30,  # § 9 ust. 1
        "zmiana_stanowiska_prog_miesiecy": 6,  # art. 81 ust. 6
        "zmiana_stanowiska_ocena_najwczesniej_dni_przed": 7,  # § 9 ust. 2
        "zmiana_stanowiska_ocena_najpozniej_dni_po": 30,  # § 9 ust. 2
        "sprzeciw_dni_od_zapoznania": 7,  # art. 83 ust. 1
        "rozpatrzenie_sprzeciwu_dni": 14,  # art. 83 ust. 3
        "odwolanie_do_sadu_pracy_dni": 14,  # art. 83 ust. 5
        "obligatoryjny_stopien_dni_od_zapoznania": 30,  # art. 89 ust. 2
    }


def test_civil_service_grades():
    grades = kprm.rules()["stopnie_sluzbowe"]
    assert grades["liczba"] == 9  # art. 86 ust. 1: dziewięć stopni służbowych
    assert len(grades["nazwy_kolejnych"]) == 8  # second … ninth can be granted


def test_employees_reference_existing_evaluators_and_sheets():
    emps = kprm.employees()
    assert "grzegorz.wzor" in emps
    for e in emps.values():
        assert e["arkusz"] in "ABC"
        if "oceniajacy" in e:
            assert e["oceniajacy"] in emps


def test_knowledge_base_and_examples_present():
    docs = dict(kprm.knowledge_docs())
    assert "ustawa-sc-wyciag-oceny.md" in docs and "Art. 83" in docs["ustawa-sc-wyciag-oceny.md"]
    assert len(kprm.example_evaluations()) == 11
