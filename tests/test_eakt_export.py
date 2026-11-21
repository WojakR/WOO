"""T24: after the acknowledgement (and again after the objection decision) the sheet goes to e-Akt – here to a
directory: PDF + JSON metadata with SHA-256; a failed export is kept and retried; HR sees the status."""
import hashlib
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.infrastructure.eakt import DirectoryExporter, HttpExporter, build_exporter
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)


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


@pytest.fixture
def st(tmp_path):
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    st.exporter = DirectoryExporter(tmp_path)
    st.tmp = tmp_path
    return st


def test_export_to_a_directory_after_the_acknowledgement(st):
    cid = drawn_up(st)
    assert not list(st.tmp.rglob("*.pdf"))  # nothing before the acknowledgement
    st.evaluations.acknowledge(cid, EMP)
    (pdf,) = st.tmp.rglob("*.pdf")
    assert pdf.parent.name == EMP and pdf.read_bytes().startswith(b"%PDF")
    meta = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta == {"id_pracownika": EMP, "id_oceny": cid, "rodzaj_dokumentu": "ocena_okresowa",
                    "data_dokumentu": "2026-06-10", "czesc_akt": "B", "zdarzenie": "ZAPOZNANIE",
                    "plik": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}
    assert st.eakt_status[cid].status == "WYSLANO" and st.eakt_status[cid].attempts == 1


def test_exported_again_after_the_objection_decision(st):
    cid = drawn_up(st)
    st.evaluations.acknowledge(cid, EMP)
    st.clock.set(date(2026, 6, 12))
    st.evaluations.file_objection(cid, EMP, "Nie zgadzam się.")
    st.evaluations.decide_objection(cid, HR, False, "Ocena rzetelna.")
    names = sorted(p.name for p in st.tmp.rglob("*.pdf"))
    assert len(names) == 2 and any("rozpatrzenie_sprzeciwu" in n for n in names)
    assert st.eakt_status[cid].reason == "ROZPATRZENIE_SPRZECIWU"


class Flaky:
    def __init__(self, target, fail=1):
        self.target, self.fail, self.calls = target, fail, 0

    def export(self, doc):
        self.calls += 1
        if self.calls <= self.fail:
            raise ConnectionError("e-Akt nie odpowiada")
        return self.target.export(doc)


def test_failed_export_is_kept_and_retried(st):
    cid = drawn_up(st)
    st.exporter = Flaky(DirectoryExporter(st.tmp))
    st.evaluations.acknowledge(cid, EMP)  # the acknowledgement itself still succeeds
    s = st.eakt_status[cid]
    assert s.status == "BLAD" and "nie odpowiada" in s.error and s.attempts == 1
    ev = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": HR}).json()
    assert ev["eksport_eakt"]["status"] == "BLAD"
    assert client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": BOSS}).json()["eksport_eakt"] is None
    assert client.post("/api/admin/eakt/retry", headers={"X-User-Id": BOSS}).status_code == 403
    r = client.post("/api/admin/eakt/retry", headers={"X-User-Id": HR}).json()
    assert r["ponowiono"][0]["status"] == "WYSLANO" and r["ponowiono"][0]["proby"] == 2
    assert len(list(st.tmp.rglob("*.pdf"))) == 1


def test_http_adapter_is_a_skeleton_that_says_what_is_missing():
    with pytest.raises(NotImplementedError, match="specyfikacji interfejsu"):
        HttpExporter("https://eakt.example", "t").export(None)
    assert build_exporter("off", None) is None
    with pytest.raises(ValueError):
        build_exporter("ftp", None)


def test_unfinished_adapter_does_not_block_the_process(st):
    cid = drawn_up(st)
    st.exporter = HttpExporter("", "")
    st.evaluations.acknowledge(cid, EMP)
    assert st.eakt_status[cid].status == "BLAD" and "NotImplementedError" in st.eakt_status[cid].error
