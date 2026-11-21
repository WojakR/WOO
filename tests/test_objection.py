"""Objection (sprzeciw, art. 83): 7 days from acknowledging to file it, the director general decides within
14 days; upheld -> back to the evaluator, not upheld -> stays, 14 days for the labour court."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.cycle import Status
from app.domain.errors import InvalidTransition, NotAuthorized, ValidationError
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)


@pytest.fixture
def st():
    """Grzegorz's evaluation drawn up on Mon 8.06.2026 (negative), acknowledged on Wed 10.06.2026."""
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: (1 if i == ids[0] else 5) for i in ids},
                          justification="Rażące błędy w przekładach.", iprz_conclusions="Szkolenie z redakcji.")
    st.clock.set(date(2026, 6, 10))
    svc.acknowledge(cid, EMP)
    st.cid = cid
    return st


def act(st, akcja, who, **body):
    return client.post(f"/api/evaluations/{st.cid}/actions/{akcja}", headers={"X-User-Id": who}, json=body)


# ---------------------------------------------------------------- service

def test_filing_within_7_days_puts_the_evaluation_under_objection(st):
    st.clock.set(date(2026, 6, 17))  # last day: 10.06 + 7
    c = st.evaluations.file_objection(st.cid, EMP, "Nie zgadzam się z oceną rzetelności.")
    assert c.status is Status.OBJECTION and c.objection_filed_on == date(2026, 6, 17)
    assert c.objection_review_deadline(st.evaluations.rules, st.evaluations.calendar) == date(2026, 7, 1)  # +14


def test_too_late_empty_or_by_someone_else_is_refused(st):
    with pytest.raises(ValidationError, match="treść sprzeciwu"):
        st.evaluations.file_objection(st.cid, EMP, "  ")
    with pytest.raises(NotAuthorized):
        st.evaluations.file_objection(st.cid, BOSS, "Sprzeciw.")
    st.clock.set(date(2026, 6, 18))
    with pytest.raises(InvalidTransition, match="Termin na sprzeciw minął 17.06.2026"):
        st.evaluations.file_objection(st.cid, EMP, "Sprzeciw.")


def test_while_under_objection_the_next_cycle_is_the_open_one(st):
    st.evaluations.file_objection(st.cid, EMP, "Sprzeciw.")
    nxt = st.evaluations.cycles.find_open_for(EMP)
    assert nxt.id != st.cid and nxt.status is Status.CYCLE_STARTED


def test_not_upheld_stays_and_opens_14_days_for_the_labour_court(st):
    st.evaluations.file_objection(st.cid, EMP, "Sprzeciw.")
    st.clock.set(date(2026, 6, 15))
    c = st.evaluations.decide_objection(st.cid, HR, False, "Ocena oparta na udokumentowanych błędach.")
    assert c.status is Status.ACKNOWLEDGED and c.objection_decision == "NIEUWZGLEDNIONY"
    assert c.labour_court_deadline(st.evaluations.rules, st.evaluations.calendar) == date(2026, 6, 29)
    with pytest.raises(InvalidTransition, match="już złożony"):
        st.evaluations.file_objection(st.cid, EMP, "Drugi sprzeciw.")


def test_upheld_returns_to_the_evaluator_and_the_next_cycle_restarts_from_the_new_result(st):
    st.evaluations.file_objection(st.cid, EMP, "Sprzeciw.")
    old_next = st.evaluations.cycles.find_open_for(EMP)
    c = st.evaluations.decide_objection(st.cid, HR, True, "Błędy dotyczyły zadań spoza opisu stanowiska.")
    assert c.status is Status.MEETING_HELD and c.acknowledged_on is None and c.is_editable("scores")
    assert st.evaluations.cycles.get(old_next.id) is None  # computed from the old (negative) result -> removed
    ids = c.criteria_ids(st.evaluations.rules)
    st.evaluations.submit_evaluation(st.cid, BOSS, scores={i: 5 for i in ids}, justification="")
    st.clock.set(date(2026, 6, 22))
    st.evaluations.acknowledge(st.cid, EMP)
    nxt = st.evaluations.cycles.find_open_for(EMP)
    assert nxt.previous_evaluation.outcome == "pozytywna" and not nxt.after_negative
    # an evaluation drawn up a second time may be objected to again (art. 83 ust. 4)
    assert st.evaluations.file_objection(st.cid, EMP, "Ponowny sprzeciw.").status is Status.OBJECTION


# ---------------------------------------------------------------- API

def test_api_file_and_decide(st):
    assert "ZLOZ_SPRZECIW" in client.get(f"/api/evaluations/{st.cid}", headers={"X-User-Id": EMP}).json()["dozwolone_akcje"]
    r = act(st, "ZLOZ_SPRZECIW", EMP, komentarz="Nie zgadzam się z oceną rzetelności.")
    assert r.status_code == 200
    ev = r.json()
    assert ev["status"] == "SPRZECIW" and ev["sprzeciw"]["termin_rozpatrzenia"] == "2026-06-24"
    hr = client.get(f"/api/evaluations/{st.cid}", headers={"X-User-Id": HR}).json()
    assert hr["dozwolone_akcje"] == ["ROZPATRZ_SPRZECIW"]
    assert act(st, "ROZPATRZ_SPRZECIW", BOSS, uwzglednij=True, komentarz="x").status_code == 403
    no_choice = act(st, "ROZPATRZ_SPRZECIW", HR, komentarz="Uzasadnienie.")
    assert no_choice.status_code == 422 and "rozstrzygnięcie" in no_choice.json()["walidacje"][0]["komunikat"]
    r = act(st, "ROZPATRZ_SPRZECIW", HR, uwzglednij=False, komentarz="Ocena zasadna.")
    assert r.status_code == 200
    assert r.json()["status"] == "ZAKONCZONA" and r.json()["sprzeciw"]["termin_odwolania_do_sadu"] == "2026-06-24"


def test_api_upheld_gives_the_evaluator_the_sheet_back(st):
    act(st, "ZLOZ_SPRZECIW", EMP, komentarz="Sprzeciw.")
    act(st, "ROZPATRZ_SPRZECIW", HR, uwzglednij=True, komentarz="Do ponownego sporządzenia.")
    ev = client.get(f"/api/evaluations/{st.cid}", headers={"X-User-Id": BOSS}).json()
    assert ev["status"] == "ROZMOWA_OCENIAJACA" and "ZATWIERDZ_OCENE" in ev["dozwolone_akcje"]
    assert ev["sprzeciw"]["decyzja"] == "UWZGLEDNIONY"


def test_reviewer_gets_reminders_and_the_dashboard_shows_the_objection(st):
    act(st, "ZLOZ_SPRZECIW", EMP, komentarz="Sprzeciw.")
    plan = client.get(f"/api/evaluations/{st.cid}/przypomnienia", headers={"X-User-Id": HR}).json()
    assert [p["etap"] for p in plan] == ["ROZPATRZENIE_SPRZECIWU"] * 2
    assert plan[0]["do_kogo"]["nazwisko"] == "kadr" and "rozpatrz sprzeciw" in plan[0]["tresc"]
    rows = [i for i in client.get("/api/dashboard", headers={"X-User-Id": HR}).json()["pozycje"]
            if i["evaluation_id"] == int(st.cid)]
    assert rows[0]["status"] == "SPRZECIW" and rows[0]["kto_dziala"] == "KADRY" and rows[0]["termin"] == "2026-06-24"
