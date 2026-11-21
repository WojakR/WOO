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
