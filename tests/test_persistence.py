"""The state survives a restart: everything is saved to the database (SQLite in tests) after each change."""
from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.api.state as state_mod
from app.api.state import _codec, get_state, reset_state, store
from app.infrastructure.json_codec import JsonCodec
from app.infrastructure.sql_store import NotatkaRow, OcenaRow
from backend.main import app

client = TestClient(app)
EMP, BOSS, DEPUTY = "grzegorz.wzor", "henryk.pryncypal", "celina.przykladowa"


def restart():
    """What a server restart does: forget the in-memory state, the next request loads it from the database."""
    state_mod._state = None
    return get_state()


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


def test_a_fully_filled_evaluation_round_trips_exactly(st):
    cid = st.evaluations.cycles.find_open_for(EMP).id
    st.evaluations.set_criteria(cid, BOSS, ["kreatywnosc"])
    st.evaluations.confirm_criteria(cid, EMP)
    st.evaluations.record_review_meeting(cid, BOSS)
    ids = st.evaluations.cycles.get(cid).criteria_ids(st.evaluations.rules)
    st.evaluations.submit_evaluation(cid, BOSS, scores={i: 3 for i in ids}, justification="Uzasadnienie oceny.",
                                     iprz_conclusions="Szkolenie.")
    before = st.evaluations.cycles.get(cid)
    codec = _codec()
    after = codec.loads(codec.dumps(before))
    assert after == before  # dates, enums, the exact Fraction average, tuples – all the same types again
    # str-enums compare equal to plain strings, so check the types explicitly
    assert type(after.status) is type(before.status) and type(after.result.outcome) is type(before.result.outcome)
    assert type(after.result.average) is type(before.result.average)
    assert all(type(a) is type(b) for (a, _), (b, _) in zip(after.history, before.history))


def test_codec_rebuilds_only_registered_classes():
    @dataclass
    class Obcy:
        x: int

    with pytest.raises(TypeError):
        JsonCodec([]).dumps(Obcy(1))
    with pytest.raises(ValueError, match="nie jest dozwolona"):
        JsonCodec([]).loads('{"__dc__": "Obcy", "x": 1}')


def test_restart_keeps_notes_deputies_clock_and_counters(st):
    e = int(st.evaluations.cycles.find_open_for(EMP).id)
    note = client.post(f"/api/evaluations/{e}/notes", headers={"X-User-Id": BOSS},
                       json={"data": "2026-06-10", "tresc": "Notatka, która ma przetrwać restart.",
                             "criterion_kod": "KOMUNIKACJA", "wydzwiek": "POZYTYWNY"}).json()
    client.post("/api/zastepstwa", headers={"X-User-Id": "kadry"}, json={
        "oceniajacy_id": st.employee_number(BOSS), "zastepca_id": st.employee_number(DEPUTY),
        "od": "2026-06-01", "do": "2026-06-30"})
    cycles_before = len(st.evaluations.cycles.list_all())

    st2 = restart()
    assert st2 is not st and st2.clock.today() == date(2026, 6, 15)
    notes = client.get(f"/api/evaluations/{e}/notes", headers={"X-User-Id": BOSS}).json()
    assert [n["tresc"] for n in notes] == ["Notatka, która ma przetrwać restart."]
    assert notes[0]["criterion_kod"] == "KOMUNIKACJA"
    assert [z["zastepca"]["imie"] for z in client.get("/api/zastepstwa", headers={"X-User-Id": "kadry"}).json()] == ["Celina"]
    assert len(st2.evaluations.cycles.list_all()) == cycles_before
    # counters continue after the restart instead of reusing ids
    second = client.post(f"/api/evaluations/{e}/notes", headers={"X-User-Id": BOSS},
                         json={"data": "2026-06-11", "tresc": "Druga."}).json()
    assert second["id"] > note["id"]


def test_background_classification_is_saved_too(st):
    e = int(st.evaluations.cycles.find_open_for(EMP).id)
    client.post(f"/api/evaluations/{e}/notes", headers={"X-User-Id": BOSS},
                json={"data": "2026-06-10", "tresc": "Obsługa interesanta trwała zbyt długo."})
    restart()
    n = client.get(f"/api/evaluations/{e}/notes", headers={"X-User-Id": BOSS}).json()[0]
    assert n["status_klasyfikacji"] in ("SUGESTIA", "DO_PRZYPISANIA") and n["sugestie_ai"]


def test_empty_database_gets_the_demo_scenario_and_saves_it():
    store().clear()
    st = restart()
    assert st.clock.today() == state_mod.DEMO_TODAY
    assert not store().is_empty()


def test_demo_reset_replaces_what_is_stored(st):
    e = int(st.evaluations.cycles.find_open_for(EMP).id)
    client.post(f"/api/evaluations/{e}/notes", headers={"X-User-Id": BOSS},
                json={"data": "2026-06-10", "tresc": "Zniknie po resecie demo."})
    assert client.post("/api/demo/reset").status_code == 204
    restart()
    with Session(store().engine) as s:
        texts = [r.dane for r in s.exec(select(NotatkaRow)).all()]
    assert not any("Zniknie po resecie demo." in t for t in texts)


def test_rows_have_searchable_columns(st):
    assert client.post("/api/demo/clock", json={"przesun_dni": 1}).status_code == 200  # any change saves the state
    with Session(store().engine) as s:
        mine = s.exec(select(OcenaRow).where(OcenaRow.oceniajacy_id == BOSS)).all()
    assert [r.oceniany_id for r in mine] == [EMP] and mine[0].status
