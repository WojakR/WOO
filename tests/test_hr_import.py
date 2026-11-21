"""T5: import of employees from the HR system – valid import, every kind of error, preview, rights."""
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.state as state_mod
from app.api.state import reset_state
from app.infrastructure.hr_import import build_report, read_rows
from backend.main import app

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from gen_fake_data import hr_rows  # noqa: E402

client = TestClient(app)
HR, BOSS = "kadry", "henryk.pryncypal"
HEADER = "id;imie;nazwisko;komorka;stanowisko;id_przelozonego;urzednik_mianowany;stopien_sluzbowy;email;data_ostatniej_oceny"


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 1), ai_mode="off")


def csv(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def upload(content: bytes, who=HR, name="kadry.csv", **params):
    return client.post("/api/admin/employees/import", headers={"X-User-Id": who}, params=params,
                       files={"file": (name, content, "text/csv")})


GOOD = csv("nowy.szef;Anna;Testowa;Wydział A;Naczelnik;;TAK;5;anna@urzad.example;2025-01-10",
           "nowy.prac;Jan;Próbny;Wydział A;Specjalista;nowy.szef;NIE;;jan@urzad.example;",
           f"grzegorz.wzor;Grzegorz;Wzór;Referat Przekładów;Starszy specjalista;{BOSS};TAK;3;;")


def test_valid_import_adds_and_updates_people(st):
    r = upload(GOOD)
    out = r.json()
    assert r.status_code == 200 and out["zapisano"] and out["problemy"] == []
    assert out["dodani"] == ["nowy.szef", "nowy.prac"] and out["zaktualizowani"] == ["grzegorz.wzor"]
    anna = st.directory.get("nowy.szef")
    assert anna.civil_servant and anna.grade == 5 and anna.email == "anna@urzad.example"
    assert anna.previous_evaluation.date == date(2025, 1, 10)
    g = st.directory.get("grzegorz.wzor")
    assert g.position == "Starszy specjalista" and g.civil_servant and g.grade == 3
    assert g.previous_evaluation.outcome == "pozytywna"  # the history from before stays


def test_civil_servant_status_reaches_the_api_and_the_pdf(st):
    upload(GOOD)
    eid = int(st.evaluations.cycles.find_open_for("grzegorz.wzor").id)
    from app.api.evaluations import _sheet_pdf_data

    assert _sheet_pdf_data(st, st.evaluations.cycles.get(str(eid))).civil_servant is True


def test_preview_saves_nothing(st):
    out = upload(GOOD, podglad="true").json()
    assert out["podglad"] and not out["zapisano"] and out["dodani"] == ["nowy.szef", "nowy.prac"]
    assert st.directory.get("nowy.szef") is None


@pytest.mark.parametrize("row,message", [
    ("x.1;Ala;Ma;W;Spec;nikt.taki;NIE;;;", "nieznany przełożony"),
    (";Ala;Ma;W;Spec;;NIE;;;", "brak wartości w kolumnie „id”"),
    ("x.1;Ala;Ma;W;;;NIE;;;", "brak wartości w kolumnie „stanowisko”"),
    ("x.1;Ala;Ma;W;Spec;;TAK;12;;", "liczba 1–9"),
    ("x.1;Ala;Ma;W;Spec;;NIE;4;;", "tylko urzędnik"),
    ("x.1;Ala;Ma;W;Spec;;NIE;;zly-adres;", "nieprawidłowy adres"),
    ("x.1;Ala;Ma;W;Spec;;NIE;;;31.02.2025", "oczekiwano daty"),
    ("x.1;Ala;Ma;W;Spec;;może;;;", "TAK / NIE"),
    ("x.1;Ala;Ma;W;Spec;x.1;NIE;;;", "swoim przełożonym"),
])
def test_each_kind_of_row_error_is_reported_and_nothing_is_saved(st, row, message):
    out = upload(csv(row)).json()
    assert not out["zapisano"] and len(out["problemy"]) == 1
    assert message in out["problemy"][0]["komunikat"] and out["problemy"][0]["wiersz"] == 1
    assert st.directory.get("x.1") is None


def test_duplicate_id(st):
    out = upload(csv("x.1;Ala;Ma;W;Spec;;NIE;;;", "x.1;Ola;Ma;W;Spec;;NIE;;;")).json()
    assert [p["wiersz"] for p in out["problemy"]] == [2] and "duplikat" in out["problemy"][0]["komunikat"]


def test_cycle_in_the_structure(st):
    out = upload(csv("a.1;A;A;W;Spec;b.1;NIE;;;", "b.1;B;B;W;Spec;c.1;NIE;;;", "c.1;C;C;W;Spec;a.1;NIE;;;")).json()
    assert len(out["problemy"]) == 1 and "cykl w strukturze" in out["problemy"][0]["komunikat"]


def test_bad_file_and_missing_columns(st):
    assert upload(b"id;imie\n1;A\n").json()["kod"] == "BLEDNY_PLIK"


def test_only_the_administrator_imports(st):
    assert upload(GOOD, who=BOSS).status_code == 403
    assert st.directory.get("nowy.szef") is None


def test_imported_people_survive_a_restart_and_cycles_can_be_opened(st):
    out = upload(GOOD, uruchom_cykle="true").json()
    assert out["uruchomione_cykle"] == ["nowy.prac"]
    restored = state_mod.restore(state_mod.snapshot(st), ai_mode="off")
    assert restored.directory.get("nowy.prac").email == "jan@urzad.example"
    assert restored.evaluations.cycles.find_open_for("nowy.prac") is not None


def test_generated_sample_file_imports_cleanly(st):
    import pandas as pd

    data = pd.DataFrame(hr_rows(30)).to_csv(index=False, sep=";").encode("utf-8")
    rep = build_report(read_rows(data, "kadry.csv"), {e.id: e for e in st.directory.all()})
    assert rep.ok and len(rep.added) == 30
    assert {e.sheet for e in rep.employees} == {"A", "B", "C"}  # derived: head of office / manages / others
