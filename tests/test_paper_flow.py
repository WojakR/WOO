"""Paper flow (use case "Pani X"): the evaluator prints the form, the employee signs it by hand, the system takes
the dates and counts the objection period from the signature – or from the return to work when the employee was
away that day; refusal to sign = fikcja zapoznania; who decides the objection in the edge cases."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.cycle import Status
from app.domain.deadlines import Absence
from app.domain.errors import ValidationError
from app.domain.objection import HeadMode, ObjectionPolicy, objection_reviewer
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)


@pytest.fixture
def st():
    """Grzegorz's evaluation drawn up on Mon 8.06.2026, waiting for the acknowledgement."""
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    st.clock.set(date(2026, 6, 8))
    svc.record_review_meeting(cid, BOSS)
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, BOSS, scores={i: 5 for i in ids}, iprz_conclusions="Szkolenie z redakcji.")
    st.cid = cid
    return st


def paper(st, who=BOSS, **body):
    return client.put(f"/api/evaluations/{st.cid}/paper", headers={"X-User-Id": who}, json=body)


def test_signature_date_is_the_acknowledgement_and_starts_the_objection_period(st):
    st.clock.set(date(2026, 6, 12))
    r = paper(st, data_wydruku="2026-06-09", data_podpisu="2026-06-10")
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["status"] == "ZAKONCZONA"
    assert ev["czesc_ii"]["data_wydruku"] == "2026-06-09" and ev["czesc_ii"]["data_podpisu"] == "2026-06-10"
    assert ev["czesc_ii"]["termin_sprzeciwu"] == "2026-06-17"  # 10.06 + 7
    c = st.evaluations.cycles.get(st.cid)
    assert c.acknowledged_on == date(2026, 6, 10) and c.signed_on == date(2026, 6, 10)
    assert st.evaluations.cycles.find_open_for(EMP) is not None  # the next cycle started by itself


def test_print_date_alone_does_not_acknowledge(st):
    st.clock.set(date(2026, 6, 9))
    ev = paper(st, data_wydruku="2026-06-09").json()
    assert ev["status"] == "OCENA_DO_ZAPOZNANIA" and ev["czesc_ii"]["termin_sprzeciwu"] is None
    ev = paper(st, data_podpisu="2026-06-09").json()  # print date kept from before
    assert ev["status"] == "ZAKONCZONA"


def test_deadline_on_a_day_off_moves_to_the_next_working_day(st):
    st.clock.set(date(2026, 6, 15))
    ev = paper(st, data_wydruku="2026-06-12", data_podpisu="2026-06-13").json()  # signed on Saturday
    assert ev["czesc_ii"]["termin_sprzeciwu"] == "2026-06-22"  # 20.06 is a Saturday -> Monday


def test_absence_on_the_delivery_day_counts_from_the_return_to_work(st):
    st.clock.set(date(2026, 6, 10))
    paper(st, data_wydruku="2026-06-10", data_podpisu="2026-06-10")
    # sick leave 9.06–19.06 registered afterwards (on the next, open cycle): back at work on Mon 22.06
    nxt = st.evaluations.cycles.find_open_for(EMP)
    st.evaluations.register_absence(nxt.id, Absence(date(2026, 6, 9), date(2026, 6, 19), "zwolnienie lekarskie"))
    assert st.evaluations.objection_deadline(st.cid) == date(2026, 6, 29)  # 22.06 + 7
    ev = client.get(f"/api/evaluations/{st.cid}", headers={"X-User-Id": EMP}).json()
    sprzeciw = next(t for t in ev["terminy"] if t["rodzaj"] == "SPRZECIW")
    assert sprzeciw["data"] == "2026-06-29" and "powrotu do pracy 22.06.2026" in sprzeciw["opis"]
    st.clock.set(date(2026, 6, 26))  # after 17.06, but within the period counted from the return
    assert st.evaluations.file_objection(st.cid, EMP, "Nie zgadzam się.").status is Status.OBJECTION


def test_an_absence_that_ended_before_the_delivery_changes_nothing(st):
    st.clock.set(date(2026, 6, 10))
    paper(st, data_wydruku="2026-06-10", data_podpisu="2026-06-10")
    nxt = st.evaluations.cycles.find_open_for(EMP)
    st.evaluations.register_absence(nxt.id, Absence(date(2026, 6, 1), date(2026, 6, 5), "urlop"))
    assert st.evaluations.objection_deadline(st.cid) == date(2026, 6, 17)


@pytest.mark.parametrize("body, message", [
    ({"data_wydruku": "2026-06-05"}, "wcześniejsza niż data sporządzenia"),
    ({"data_wydruku": "2026-06-11", "data_podpisu": "2026-06-10"}, "wcześniejsza niż data wydruku"),
    ({"data_wydruku": "2026-06-20"}, "z przyszłości"),
    ({"data_podpisu": "2026-06-10"}, "Najpierw wpisz datę wydruku"),
])
def test_date_validations(st, body, message):
    st.clock.set(date(2026, 6, 12))
    r = paper(st, **body)
    assert r.status_code == 422 and message in r.text
    assert st.evaluations.cycles.get(st.cid).status is Status.EVALUATION_DONE


def test_only_the_evaluator_records_paper_dates(st):
    st.clock.set(date(2026, 6, 12))
    assert paper(st, who=EMP, data_wydruku="2026-06-09").status_code == 403


def test_refusal_to_sign_is_a_fikcja_zapoznania(st):
    st.clock.set(date(2026, 6, 11))
    url = f"/api/evaluations/{st.cid}/actions/FIKCJA_ZAPOZNANIA"
    assert "FIKCJA_ZAPOZNANIA" in client.get(f"/api/evaluations/{st.cid}", headers={"X-User-Id": BOSS}).json()["dozwolone_akcje"]
    assert client.post(url, headers={"X-User-Id": BOSS}, json={"komentarz": " "}).status_code == 422
    assert client.post(url, headers={"X-User-Id": EMP}, json={"komentarz": "x"}).status_code == 403
    r = client.post(url, headers={"X-User-Id": BOSS},
                    json={"komentarz": "Odmówił podpisu w obecności K. Nowak.", "data": "2026-06-10"})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["status"] == "ZAKONCZONA" and ev["czesc_ii"]["fikcja_zapoznania"] is True
    assert ev["czesc_ii"]["adnotacja_odmowy"].startswith("Odmówił")
    assert ev["czesc_ii"]["termin_sprzeciwu"] == "2026-06-17"
    assert st.evaluations.cycles.find_open_for(EMP) is not None


def test_refusal_cannot_be_dated_in_the_future(st):
    st.clock.set(date(2026, 6, 10))
    with pytest.raises(ValidationError, match="z przyszłości"):
        st.evaluations.refuse_acknowledgement(st.cid, BOSS, "Odmowa.", date(2026, 6, 11))


# ---------------------------------------------------------------- who decides the objection

def test_reviewer_is_the_director_general_by_default():
    r = objection_reviewer(ObjectionPolicy("dg"), "jan", "szef", False, "kierownik")
    assert r.id == "dg" and "dyrektor generalny" in r.basis


def test_office_head_goes_to_the_superior_body_or_a_re_examination():
    r = objection_reviewer(ObjectionPolicy("dg", superior_body="minister"), "kierownik", "minister.x", True, None)
    assert r.id == "minister" and "organ nadrzędny" in r.basis
    r = objection_reviewer(ObjectionPolicy("dg", when_office_head=HeadMode.RE_EXAMINATION), "kierownik", "ocen",
                           True, None)
    assert r.id == "ocen" and "ponownemu rozpatrzeniu" in r.basis


def test_office_without_a_director_general_goes_to_the_head_of_the_office():
    r = objection_reviewer(ObjectionPolicy("dg", office_has_director_general=False), "jan", "szef", False, "kier")
    assert r.id == "kier" and "przypis 17" in r.basis
    r = objection_reviewer(ObjectionPolicy("dg"), "dg", "kier", False, "kier")  # DG objecting: not to themself
    assert r.id != "dg"


def test_api_shows_the_reviewer_for_the_head_of_an_office():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    head = "janina.kowalska"  # sheet A, kierownik_urzedu in pracownicy.json
    cid = st.evaluations.cycles.find_open_for(head).id
    ev = client.get(f"/api/evaluations/{cid}", headers={"X-User-Id": HR}).json()
    assert "kierownikiem urzędu" in ev["rozpatrujacy_sprzeciw"]["podstawa"]
    ev = client.get(f"/api/evaluations/{st.evaluations.cycles.find_open_for(EMP).id}", headers={"X-User-Id": HR}).json()
    assert ev["rozpatrujacy_sprzeciw"]["id"] == "kadry"
