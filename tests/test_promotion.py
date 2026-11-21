"""T11: request for the next grade (part III, art. 89 ust. 1) – employee: n/a, negative: blocked, grade 9: none,
obligatory grade (art. 89 ust. 2) shown, part III in the PDF."""
import io
from datetime import date

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.domain.promotion import check_request, promotion_view
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend.main import app
from conseq_helpers import BOSS, EMP, prepare_meeting, state

client = TestClient(app)
R = kprm_rulebook()
AS_BOSS = {"X-User-Id": BOSS}


def scores(cid, value, low=None):
    ev = client.get(f"/api/evaluations/{cid}", headers=AS_BOSS).json()
    codes = [k["criterion_kod"] for k in ev["kryteria"]]
    client.put(f"/api/evaluations/{cid}/scores", headers=AS_BOSS,
               json={"punkty": {k: (low if low is not None and i == 0 else value) for i, k in enumerate(codes)}})
    return client.get(f"/api/evaluations/{cid}", headers=AS_BOSS).json()


def patch(cid, **body):
    ev = client.get(f"/api/evaluations/{cid}", headers=AS_BOSS).json()
    return client.patch(f"/api/evaluations/{cid}", headers=AS_BOSS, json={"updated_at": ev["updated_at"], **body})


def test_rule():
    assert promotion_view(False, None, True, False, False, R).applies == "NIE_DOTYCZY"
    assert promotion_view(True, 9, True, False, False, R).requested_grade is None
    assert "najwyższy możliwy" in promotion_view(True, 9, True, False, False, R).blocked_reason
    assert promotion_view(True, 4, True, True, False, R).requested_grade == 5
    assert check_request(True, 4, False, True, R)  # negative blocks


def test_employee_is_not_applicable():
    st = state(civil_servant=False, grade=None)
    cid = prepare_meeting(st)
    ev = scores(cid, 7)
    assert ev["czesc_ii"]["wniosek_o_stopien"] == "NIE_DOTYCZY" and ev["czesc_iii"] is None
    assert "wniosek_o_stopien" not in ev["edytowalne_pola"]
    assert patch(cid, wniosek_o_stopien="TAK").status_code == 409


def test_civil_servant_request_needs_motivation_and_goes_into_the_pdf():
    st = state(civil_servant=True, grade=4)
    cid = prepare_meeting(st)
    ev = scores(cid, 7)
    assert {"wniosek_o_stopien", "umotywowanie_wniosku", "posiadany_stopien"} <= set(ev["edytowalne_pola"])
    ev = patch(cid, wniosek_o_stopien="TAK", wnioski_iprz="Szkolenie.").json()
    assert ev["czesc_ii"]["wniosek_o_stopien"] == "TAK" and ev["czesc_iii"]["wnioskowany_stopien"] == 5
    assert {w["kod"] for w in ev["walidacje"]} == {"UMOTYWOWANIE_WYMAGANE"}
    assert client.post(f"/api/evaluations/{cid}/actions/ZATWIERDZ_OCENE", headers=AS_BOSS, json={}).status_code == 422
    patch(cid, umotywowanie_wniosku="Wyróżniające wyniki w przekładach.")
    assert client.post(f"/api/evaluations/{cid}/actions/ZATWIERDZ_OCENE", headers=AS_BOSS, json={}).status_code == 200
    pdf = client.get(f"/api/evaluations/{cid}/pdf", headers=AS_BOSS).content
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "CZĘŚĆ III" in text and "Wyróżniające wyniki" in text and "Wnioskowany stopień" in text


def test_negative_blocks_the_request():
    st = state(civil_servant=True, grade=4)
    cid = prepare_meeting(st)
    scores(cid, 5, low=1)
    r = patch(cid, wniosek_o_stopien="TAK")
    assert r.status_code == 422 and "negatywnej" in r.json()["walidacje"][0]["komunikat"]


def test_highest_grade_no_request():
    st = state(civil_servant=True, grade=9)
    cid = prepare_meeting(st)
    scores(cid, 9)
    r = patch(cid, wniosek_o_stopien="TAK")
    assert r.status_code == 422 and "najwyższy możliwy" in r.json()["walidacje"][0]["komunikat"]


def test_obligatory_grade_is_shown_while_drawing_up():
    st = state(civil_servant=True, grade=4, previous=("pozytywna", "znacznie powyżej oczekiwań", date(2024, 6, 12)))
    cid = prepare_meeting(st)
    ev = scores(cid, 7)  # powyżej oczekiwań -> second top evaluation since the last grade
    assert ev["czesc_iii"]["stopien_obligatoryjny"] is True and ev["czesc_iii"]["wnioskowany_stopien"] == 5
    ev = scores(cid, 5)
    assert ev["czesc_iii"]["stopien_obligatoryjny"] is False


def test_pdf_without_request_for_an_employee_says_not_applicable():
    st = state(civil_servant=False, grade=None)
    cid = prepare_meeting(st)
    scores(cid, 7)
    pdf = client.get(f"/api/evaluations/{cid}/pdf", headers=AS_BOSS).content
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "CZĘŚĆ III" not in text and "NIE DOTYCZY" in text
    assert EMP
