"""T22: closed evaluations are frozen once (immutable snapshot + PDF with SHA-256), records past their retention
are listed for HR, and nothing is deleted without the administrator's approval."""
import dataclasses
import hashlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application.archive import Frozen, is_closed, records_retention_end
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
ADMIN = {"X-User-Id": HR}
client = TestClient(app)


@pytest.fixture
def st():
    """Grzegorz's evaluation acknowledged on Wed 10.06.2026: objection period until 17.06.2026."""
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: 5 for i in ids}, iprz_conclusions="Szkolenie.")
    st.clock.set(date(2026, 6, 10))
    svc.acknowledge(cid, EMP)
    st.cid = cid
    return st


def run():
    return client.post("/api/archive/run", headers=ADMIN)


def test_only_closed_evaluations_are_frozen(st):
    svc = st.evaluations
    c = svc.cycles.get(st.cid)
    assert not is_closed(c, svc.rules, svc.calendar, date(2026, 6, 17))  # objection still possible
    assert run().json()["zamrozono"] == []
    st.clock.set(date(2026, 6, 18))
    assert is_closed(c, svc.rules, svc.calendar, date(2026, 6, 18))
    frozen = run().json()["zamrozono"]
    assert [f["evaluation_id"] for f in frozen] == [int(st.cid)] and frozen[0]["zgodny"] is True
    assert client.post("/api/archive/run", headers={"X-User-Id": BOSS}).status_code == 403


def test_objection_not_upheld_closes_it(st):
    st.clock.set(date(2026, 6, 12))
    st.evaluations.file_objection(st.cid, EMP, "Nie zgadzam się.")
    assert run().json()["zamrozono"] == []
    st.evaluations.decide_objection(st.cid, HR, False, "Ocena rzetelna.")
    assert len(run().json()["zamrozono"]) == 1


def test_snapshot_is_immutable(st):
    st.clock.set(date(2026, 6, 18))
    first = run().json()["zamrozono"][0]
    record = st.archive_store().get(st.cid)
    c = st.evaluations.cycles.get(st.cid)
    c.justification = "zmienione po archiwizacji"
    st.evaluations.cycles.save(c)
    assert run().json()["zamrozono"] == []  # already archived: never frozen again
    again = st.archive_store().get(st.cid)
    assert again == record and "zmienione po archiwizacji" not in again.snapshot
    assert not hasattr(st.archive_store(), "update")
    assert client.get("/api/archive", headers=ADMIN).json()[0]["sha256_dane"] == first["sha256_dane"]


def test_pdf_checksum_matches(st):
    st.clock.set(date(2026, 6, 18))
    rec = run().json()["zamrozono"][0]
    r = client.get(f"/api/archive/{rec['id']}/pdf", headers=ADMIN)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert hashlib.sha256(r.content).hexdigest() == rec["sha256_pdf"] == r.headers["x-sha256"]
    stored = st.archive_store().by_id(rec["id"])
    assert stored.intact() and not dataclasses.replace(stored, pdf=stored.pdf + b" ").intact()


def test_retention_period():
    assert records_retention_end(date(2015, 3, 31), 10) == date(2025, 12, 31)


def test_review_lists_records_past_retention_and_old_notes(st):
    st.clock.set(date(2026, 6, 18))
    rec = run().json()["zamrozono"][0]
    assert client.get("/api/archive/review", headers=ADMIN).json() == []  # still employed, notes still kept
    emp = dataclasses.replace(st.directory.get(EMP), employment_end=date(2015, 3, 31))
    st.directory._by_id[EMP] = emp
    items = client.get("/api/archive/review", headers=ADMIN).json()
    assert [(i["rodzaj"], i["id"], i["termin_przechowywania"]) for i in items] == [("AKTA", rec["id"], "2025-12-31")]
    assert "art. 94 pkt 9b" in items[0]["powod"]
    assert items[0]["pracownik"] == rec["pracownik"] == st.directory.get(EMP).full_name  # names for the HR view
    st.directory._by_id[EMP] = dataclasses.replace(emp, employment_end=None)
    from app.domain.notes import Note

    st.add_note(int(st.cid), Note("x", date(2026, 5, 1), "Notatka robocza.", BOSS))
    st.clock.set(date(2027, 6, 11))
    items = client.get("/api/archive/review", headers=ADMIN).json()
    assert [(i["rodzaj"], i["evaluation_id"]) for i in items] == [("NOTATKI", int(st.cid))]
    assert "12 mies." in items[0]["powod"]


def test_nothing_is_deleted_without_approval(st):
    st.clock.set(date(2026, 6, 18))
    rec = run().json()["zamrozono"][0]
    url = f"/api/archive/{rec['id']}/delete"
    assert client.post(url, headers=ADMIN, json={"zatwierdzam": True}).status_code == 409  # retention not over
    st.directory._by_id[EMP] = dataclasses.replace(st.directory.get(EMP), employment_end=date(2015, 3, 31))
    assert client.post(url, headers={"X-User-Id": BOSS}, json={"zatwierdzam": True}).status_code == 403
    assert client.post(url, headers=ADMIN, json={}).status_code == 422
    assert st.archive_store().by_id(rec["id"]) is not None
    assert client.post(url, headers=ADMIN, json={"zatwierdzam": True}).status_code == 200
    assert st.archive_store().by_id(rec["id"]) is None


def test_working_notes_deleted_only_after_their_period_and_with_approval(st):
    from app.domain.notes import Note

    st.add_note(int(st.cid), Note("x", date(2026, 5, 1), "Notatka robocza.", BOSS))
    st.clock.set(date(2026, 6, 18))
    run()
    url = f"/api/archive/notes/{st.cid}/delete"
    assert client.post(url, headers=ADMIN, json={"zatwierdzam": True}).status_code == 409
    st.clock.set(date(2027, 6, 11))
    assert client.post(url, headers=ADMIN, json={}).status_code == 422
    assert client.post(url, headers=ADMIN, json={"zatwierdzam": True}).json() == {"usunieto_notatek": 1}
    assert st.notes_of(int(st.cid)) == []


def test_frozen_record_detects_tampering():
    f = Frozen(1, "1", "x", date(2026, 1, 1), "{}", hashlib.sha256(b"{}").hexdigest(), b"%PDF",
               hashlib.sha256(b"%PDF").hexdigest())
    assert f.intact() and not dataclasses.replace(f, snapshot='{"a": 1}').intact()
