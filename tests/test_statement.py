"""Statement of evaluations for the reporting system / inspections: one row per evaluation, deadlines kept or not,
outcome, objection; pseudonyms by default, names for HR only."""
import csv
import io
import json
from datetime import date

from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application.statement import COLUMNS
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)


def drawn_up_state():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: 7 for i in ids}, iprz_conclusions="Szkolenie.")
    st.clock.set(date(2026, 6, 10))
    svc.acknowledge(cid, EMP)
    return st, cid


def rows_of(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=";"))


def test_csv_has_one_row_per_evaluation_and_no_names_by_default():
    st, cid = drawn_up_state()
    r = client.get("/api/reports/zestawienie.csv", headers={"X-User-Id": HR})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = rows_of(r.text)
    assert list(rows[0]) == COLUMNS
    mine = next(x for x in rows if x["id_oceny"] == cid)
    assert mine["pracownik"].startswith("P-") and mine["imie_nazwisko"] == "" and "Wzór" not in r.text
    assert mine["data_sporzadzenia"] == "2026-06-08" and mine["ocena_w_terminie"] == "TAK"
    assert mine["wynik"] == "POZYTYWNA" and mine["srednia"] == "7,00" and mine["sprzeciw"] == "BRAK"
    # the same person keeps the same code (the next cycle opened on its own)
    nxt = next(x for x in rows if x["id_oceny"] != cid and x["pracownik"] == mine["pracownik"])
    assert nxt["status"] == "CYCLE_STARTED"


def test_names_only_for_hr_and_filters():
    st, cid = drawn_up_state()
    assert client.get("/api/reports/zestawienie.csv?dane_osobowe=true",
                      headers={"X-User-Id": BOSS}).status_code == 403
    named = rows_of(client.get("/api/reports/zestawienie.csv?dane_osobowe=true", headers={"X-User-Id": HR}).text)
    assert any(x["imie_nazwisko"] == "Grzegorz Wzór" and x["pracownik"] == EMP for x in named)
    period = rows_of(client.get("/api/reports/zestawienie.csv?od=2026-06-01&do=2026-06-30",
                                headers={"X-User-Id": HR}).text)
    assert [x["id_oceny"] for x in period] == [cid]
    team = rows_of(client.get("/api/reports/zestawienie.csv", headers={"X-User-Id": BOSS}).text)
    assert team and len(team) < len(rows_of(client.get("/api/reports/zestawienie.csv", headers={"X-User-Id": HR}).text))


def test_json_package_for_a_reporting_system():
    st, cid = drawn_up_state()
    st.clock.set(date(2026, 6, 12))
    st.evaluations.file_objection(cid, EMP, "Sprzeciw.")
    st.evaluations.decide_objection(cid, HR, True, "Zasadny.", "ZMIANA_OCENY")
    data = json.loads(client.get("/api/reports/zestawienie.json?od=2026-06-01", headers={"X-User-Id": HR}).text)
    assert data["wersja_formatu"] == "1.0" and data["liczba_ocen"] == len(data["oceny"]) == 1
    row = data["oceny"][0]
    assert row["sprzeciw"] == "UWZGLEDNIONY" and row["rozstrzygniecie_sprzeciwu"] == "ZMIANA_OCENY"
    assert row["data_rozstrzygniecia_sprzeciwu"] == "2026-06-12"
