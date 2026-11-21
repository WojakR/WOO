"""Working-time (RCP) import: CSV/XLSX, bad rows reported, indicators in a window, the signal reaches the HR
partner as an aggregate (no raw hours)."""
import io
from datetime import date, time, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.worktime_signals import WorkDay, indicators, overload_evidence
from app.infrastructure.rcp_import import import_file, import_rows
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)
CFG = {"okno_tygodni": 8, "norma_godzin_dziennie": 8, "nadgodziny_od_minut": 30, "prog_dni_z_nadgodzinami": 10,
       "minimalna_przerwa_minut": 15, "prog_dni_bez_przerwy": 10, "prog_dni_aktywnosci_po_godzinach": 5}


def heavy_csv(end: date, days: int = 30, who: str = EMP) -> bytes:
    rows = ["id_pracownika;data;wejscie;wyjscie;przerwy_min;aktywnosc_po_godzinach"]
    for i in range(days):
        d = end - timedelta(days=i)
        rows.append(f"{who};{d.isoformat()};07:30;18:30;5;tak")  # 11 h minus 5 min break
    return "\n".join(rows).encode("utf-8")


def resolve(x):
    return x if x in (EMP, BOSS) else None


def test_import_csv_and_bad_rows_are_reported():
    data = ("id_pracownika;data;wejscie;wyjscie;przerwy_min\n"
            f"{EMP};2026-05-04;08:00;16:00;30\n"
            f"{EMP};04.05.2026;08:00;17:00;30\n"  # same day again -> replaces the first one
            "nikt;2026-05-05;08:00;16:00;30\n"
            f"{EMP};2026-05-06;16:00;08:00;30\n"
            f"{EMP};2026-13-01;08:00;16:00;30\n"
            f"{EMP};2026-05-07;8 rano;16:00;30\n").encode()
    r = import_file(data, "rcp.csv", resolve)
    assert len(r.days) == 1 and r.days[0].end == time(17, 0)
    assert [e.line for e in r.errors] == [4, 5, 6, 7]
    assert "nieznany pracownik" in r.errors[0].message


def test_import_xlsx():
    pytest.importorskip("openpyxl")
    buf = io.BytesIO()
    pd.DataFrame([{"id_pracownika": EMP, "data": "2026-05-04", "wejscie": "08:00", "wyjscie": "16:30",
                   "przerwy_min": 20, "aktywnosc_po_godzinach": "nie"}]).to_excel(buf, index=False)
    r = import_file(buf.getvalue(), "rcp.xlsx", resolve)
    assert not r.errors and r.days[0].worked_minutes == 490


def test_missing_columns():
    r = import_rows([{"id_pracownika": EMP, "data": "2026-05-04"}], resolve)
    assert not r.days and "Brak kolumn" in r.errors[0].message


def test_indicators_in_the_window():
    end = date(2026, 5, 25)
    days = [WorkDay(EMP, end - timedelta(days=i), time(7, 30), time(18, 30), 5, i % 2 == 0) for i in range(70)]
    ind = indicators(days, end, CFG)
    assert ind.days == 56  # only the last 8 weeks
    assert ind.overtime_days == 56 and ind.short_break_days == 56 and ind.average_break == 5
    assert ind.after_hours_days == 28
    ev = overload_evidence(ind, CFG)
    assert len(ev) == 1 and "56 dni z nadgodzinami" in ev[0] and "07:30" not in ev[0]
    normal = [WorkDay(EMP, end - timedelta(days=i), time(8), time(16, 15), 20) for i in range(40)]
    assert overload_evidence(indicators(normal, end, CFG), CFG) == []


def test_only_hr_imports():
    reset_state(today=date(2026, 5, 25), ai_mode="off")
    files = {"file": ("rcp.csv", heavy_csv(date(2026, 5, 25)), "text/csv")}
    assert client.post("/api/admin/rcp/import", headers={"X-User-Id": BOSS}, files=files).status_code == 403


def test_signal_appears_in_the_hr_partner():
    st = reset_state(today=date(2026, 5, 25), ai_mode="off")
    cid = st.evaluations.cycles.find_open_for(EMP).id
    url = f"/api/evaluations/{cid}/hr-partner"
    assert "PRZECIAZENIE" not in [s["typ"] for s in client.get(url, headers={"X-User-Id": BOSS}).json()["sygnaly"]]
    files = {"file": ("rcp.csv", heavy_csv(date(2026, 5, 25)), "text/csv")}
    r = client.post("/api/admin/rcp/import", headers={"X-User-Id": HR}, files=files)
    assert r.status_code == 200 and r.json()["zaimportowano"] == 30 and r.json()["bledy"] == []
    sig = next(s for s in client.get(url, headers={"X-User-Id": BOSS}).json()["sygnaly"] if s["typ"] == "PRZECIAZENIE")
    assert sig["dowody"][0].startswith("RCP") and "18:30" not in " ".join(sig["dowody"])
    summary = client.get("/api/admin/rcp/summary", headers={"X-User-Id": HR}).json()
    assert summary[0]["sygnal"] is True


def test_imported_days_survive_a_restart():
    from app.api.state import restore, snapshot

    st = reset_state(today=date(2026, 5, 25), ai_mode="off")
    st.worktime.add([WorkDay(EMP, date(2026, 5, 4), time(8), time(16), 30)])
    st.wellbeing.clear()
    again = restore(snapshot(st), ai_mode="off")
    assert again.worktime.days_for(EMP, date(2026, 5, 1), date(2026, 5, 31))[0].end == time(16)


def test_fake_data_generator_produces_importable_rows():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("gen", Path(__file__).parent.parent / "scripts" / "gen_fake_data.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    rows = gen.rcp_rows([EMP, BOSS], "2026-05-25", 9, EMP)
    r = import_rows(rows, resolve)
    assert not r.errors
    assert overload_evidence(indicators([d for d in r.days if d.employee_id == EMP], date(2026, 5, 25), CFG), CFG)
    assert not overload_evidence(indicators([d for d in r.days if d.employee_id == BOSS], date(2026, 5, 25), CFG), CFG)
