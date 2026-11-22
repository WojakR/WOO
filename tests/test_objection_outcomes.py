"""Upheld objection, art. 83 ust. 4 + KPRM use cases: "zmiana oceny" vs "ponowne sporządzenie oceny", each with its
notice. Both are carried out by the evaluator after the DG's decision and may not make the evaluation worse."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.cycle import CHANGE, REDO, Status
from app.domain.errors import ValidationError
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)


@pytest.fixture
def st():
    """Negative evaluation drawn up 8.06.2026 (first criterion 1, the rest 5), acknowledged 10.06, objected 12.06."""
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
    st.clock.set(date(2026, 6, 12))
    svc.file_objection(cid, EMP, "Błędy dotyczyły zadań spoza opisu stanowiska.")
    st.cid, st.ids = cid, ids
    return st


def notices(st, who, kind=None):
    return [n for n in st.notices if n.recipient_id == who and (kind is None or n.kind == kind)]


def test_upheld_needs_the_choice_of_change_or_redo(st):
    with pytest.raises(ValidationError, match="zmiana oceny albo ponowne sporządzenie"):
        st.evaluations.decide_objection(st.cid, HR, True, "Zasadny.")
    r = client.post(f"/api/evaluations/{st.cid}/actions/ROZPATRZ_SPRZECIW", headers={"X-User-Id": HR},
                    json={"uwzglednij": True, "komentarz": "Zasadny."})
    assert r.status_code == 422


def test_change_keeps_the_evaluation_acknowledged_and_restarts_the_next_cycle(st):
    svc = st.evaluations
    old_next = svc.cycles.find_open_for(EMP)
    c = svc.decide_objection(st.cid, HR, True, "Kryterium 1 oceniono za zadania spoza opisu stanowiska.", CHANGE)
    assert c.status is Status.MEETING_HELD and c.objection_order_pending and c.result is None
    assert svc.cycles.get(old_next.id) is None  # computed from the old result
    # the DG's order reaches the evaluator, the evaluated person learns it was upheld
    assert "zmień ocenę" in notices(st, BOSS, "POLECENIE_ZMIANY_OCENY")[0].text
    assert notices(st, EMP, "SPRZECIW_UWZGLEDNIONY")
    with pytest.raises(ValidationError, match="nic nie zostało zmienione"):
        svc.submit_evaluation(st.cid, BOSS)
    st.clock.set(date(2026, 6, 15))
    svc.submit_evaluation(st.cid, BOSS, scores={i: 5 for i in st.ids})
    c = svc.cycles.get(st.cid)
    # the same evaluation: drawn up 8.06, acknowledged 10.06 – no new acknowledgement and no new objection
    assert c.status is Status.ACKNOWLEDGED and c.evaluated_on == date(2026, 6, 8)
    assert c.acknowledged_on == date(2026, 6, 10) and c.objection_executed_on == date(2026, 6, 15)
    assert c.result.outcome.value == "pozytywna" and c.superseded[-1].result.outcome.value == "negatywna"
    nxt = svc.cycles.find_open_for(EMP)
    assert nxt.previous_evaluation.outcome == "pozytywna" and nxt.start_date == date(2026, 6, 8)
    assert "zmieniona w wyniku uwzględnienia sprzeciwu" in notices(st, EMP, "OCENA_ZMIENIONA")[0].text
    assert notices(st, HR, "OCENA_ZMIENIONA")


def test_redo_annuls_the_evaluation_and_the_second_one_may_be_objected_to(st):
    svc = st.evaluations
    c = svc.decide_objection(st.cid, HR, True, "Sprzeciw ogólny – ocena do sporządzenia po raz drugi.", REDO)
    assert c.status is Status.MEETING_HELD and c.evaluated_on is None and c.acknowledged_on is None
    assert c.superseded[-1].kind == REDO and c.superseded[-1].evaluated_on == date(2026, 6, 8)
    assert "anulowana" in notices(st, EMP, "SPRZECIW_UWZGLEDNIONY")[0].text
    assert notices(st, BOSS, "POLECENIE_PONOWNEGO_SPORZADZENIA")
    st.clock.set(date(2026, 6, 16))
    svc.submit_evaluation(st.cid, BOSS, scores={i: (3 if i == st.ids[0] else 5) for i in st.ids},
                          justification="Ocena sporządzona po raz drugi.")
    c = svc.cycles.get(st.cid)
    assert c.status is Status.EVALUATION_DONE and c.evaluated_on == date(2026, 6, 16)
    assert "po raz drugi" in notices(st, EMP, "OCENA_SPORZADZONA_PONOWNIE")[0].text
    svc.acknowledge(st.cid, EMP)
    assert svc.file_objection(st.cid, EMP, "Ponowny sprzeciw.").status is Status.OBJECTION


def test_upholding_never_lowers_a_partial_score(st):
    svc = st.evaluations
    svc.decide_objection(st.cid, HR, True, "Zasadny.", REDO)
    lower = {i: (1 if i == st.ids[0] else 3) for i in st.ids}
    with pytest.raises(ValidationError, match="nie może być niższa niż przed sprzeciwem"):
        svc.submit_evaluation(st.cid, BOSS, scores=lower, justification="x")
    svc.edit(st.cid, BOSS, scores=lower)
    ev = client.get(f"/api/evaluations/{st.cid}", headers={"X-User-Id": BOSS}).json()
    codes = {w["kod"] for w in ev["walidacje"]}
    assert "SPRZECIW_OBNIZENIE" in codes


def test_the_evaluated_person_is_told_the_evaluation_waits_for_them(st):
    [n] = notices(st, EMP, "OCENA_DO_ZAPOZNANIA")
    assert "zapoznaj się" in n.text.casefold() and "7 dni na sprzeciw" in n.text


def test_not_upheld_notifies_about_the_labour_court(st):
    st.evaluations.decide_objection(st.cid, HR, False, "Ocena oparta na udokumentowanych błędach.")
    text = notices(st, EMP, "SPRZECIW_NIEUWZGLEDNIONY")[0].text
    assert "sądu pracy do" in text and notices(st, BOSS, "SPRZECIW_NIEUWZGLEDNIONY")


def test_api_shows_the_order_and_the_evaluation_before_it(st):
    r = client.post(f"/api/evaluations/{st.cid}/actions/ROZPATRZ_SPRZECIW", headers={"X-User-Id": HR},
                    json={"uwzglednij": True, "tryb": "ZMIANA_OCENY", "komentarz": "Zmienić ocenę kryterium 1."})
    assert r.status_code == 200
    o = r.json()["sprzeciw"]
    assert o["tryb"] == "ZMIANA_OCENY" and o["termin_wykonania"] == "2026-06-26" and o["wykonano"] is None
    assert o["przed_sprzeciwem"]["wynik"] == "NEGATYWNA" and not o["przed_sprzeciwem"]["anulowana"]
    mine = client.get("/api/notifications", headers={"X-User-Id": BOSS}).json()
    assert any(n["typ"] == "POLECENIE_ZMIANY_OCENY" for n in mine)
    assert any(n["typ"] == "SPRZECIW_UWZGLEDNIONY"
               for n in client.get("/api/notifications", headers={"X-User-Id": EMP}).json())


def test_notices_are_mailed_once(st):
    from datetime import datetime

    from app.application import notify_job
    from app.infrastructure.notifier import OutboxNotifier

    st.evaluations.decide_objection(st.cid, HR, True, "Zasadny.", REDO)
    out = OutboxNotifier()
    mails = {BOSS: "henryk@urzad.example", EMP: "grzegorz@urzad.example"}
    notify_job.run(st, out, datetime(2026, 6, 12, 10, 0), st.settings.working_hours, mails.get)
    subjects = {(to, subj) for to, subj, _ in out.sent}
    assert ("henryk@urzad.example", "Polecenie ponownego sporządzenia oceny – Grzegorz Wzór") in subjects
    assert any(to == "grzegorz@urzad.example" and "uwzględniony" in subj for to, subj in subjects)
    again = OutboxNotifier()
    notify_job.run(st, again, datetime(2026, 6, 12, 11, 0), st.settings.working_hours, mails.get)
    assert not [m for m in again.sent if "sprzeciw" in m[1].lower() or "Polecenie" in m[1]]
