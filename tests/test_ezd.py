"""EZD (document management): the final evaluation sheet and the letter about a changed deadline are registered
as an import package (PDF + metadane.json); a failed registration is kept and retried; HR sees the status."""
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.infrastructure.ezd import DirectoryRegistry, HttpRegistry, build_registry
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)


@pytest.fixture
def st(tmp_path):
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    st.registry = DirectoryRegistry(tmp_path)
    st.tmp = tmp_path
    return st


def drawn_up(st):
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: 5 for i in ids}, iprz_conclusions="Szkolenie.")
    st.clock.set(date(2026, 6, 10))
    return cid


def test_sheet_registered_after_the_acknowledgement(st):
    cid = drawn_up(st)
    assert not list(st.tmp.rglob("*.pdf"))
    st.evaluations.acknowledge(cid, EMP)
    (pdf,) = st.tmp.rglob("*.pdf")
    assert pdf.parent.parent.name == "2026-06" and pdf.read_bytes().startswith(b"%PDF")
    meta = json.loads((pdf.parent / "metadane.json").read_text(encoding="utf-8"))
    assert meta["rodzaj_dokumentu"] == "ARKUSZ_OCENY_OKRESOWEJ" and meta["data_dokumentu"] == "2026-06-10"
    assert meta["autor"] == "Henryk Pryncypał" and meta["adresat"] == "Grzegorz Wzór"
    assert meta["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    out = client.get("/api/admin/ezd", headers={"X-User-Id": HR}).json()
    assert out["dokumenty"][0]["status"] == "ZAREJESTROWANO" and out["dokumenty"][0]["evaluation_id"] == int(cid)
    assert client.get("/api/admin/ezd", headers={"X-User-Id": BOSS}).status_code == 403


def test_failure_is_kept_and_retried(st):
    cid = drawn_up(st)
    st.registry = HttpRegistry("", "")
    st.evaluations.acknowledge(cid, EMP)
    (status,) = st.ezd_status.values()
    assert status.status == "BLAD" and "NotImplementedError" in status.error and "JRWA" in status.error
    st.registry = DirectoryRegistry(st.tmp)
    r = client.post("/api/admin/ezd/retry", headers={"X-User-Id": HR}).json()
    assert [x["status"] for x in r["ponowiono"]] == ["ZAREJESTROWANO"] and r["ponowiono"][0]["proby"] == 2
    assert len(list(st.tmp.rglob("*.pdf"))) == 1


def test_deadline_letter_is_registered(st):
    st.clock.set(date(2026, 5, 4))  # Grzegorz's deadline 12.06.2026; the evaluator's decision applies at once
    cid = st.evaluations.cycles.find_open_for(EMP).id
    r = client.post(f"/api/evaluations/{cid}/deadline-changes", headers={"X-User-Id": BOSS},
                    json={"powod": "PRZEWIDYWANA_NIEOBECNOSC_OCENIANEGO", "nowy_termin": "2026-09-15",
                          "uzasadnienie": "Planowany urlop rodzicielski ocenianego od 1.06 do 31.08.2026."})
    assert r.status_code == 201, r.text
    (doc,) = [x for x in st.ezd_status.values() if x.kind == "PISMO_ZMIANA_TERMINU_OCENY"]
    assert doc.status == "ZAREJESTROWANO" and doc.key == f"pismo-termin-{r.json()['id']}"
    meta = json.loads((Path(doc.reference).parent / "metadane.json").read_text(encoding="utf-8"))
    assert meta["tytul"].startswith("Informacja o zmianie terminu oceny okresowej")


def test_build_registry():
    assert build_registry("off", None) is None
    with pytest.raises(ValueError):
        build_registry("ftp", None)
