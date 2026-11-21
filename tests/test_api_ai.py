"""Contract endpoints (docs/api.md): GET /api/meta, POST /api/evaluations/{id}/ai/conversation-prep."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import schemas as s
from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


def _eval_id(st, employee_id=EMP) -> int:
    return int(st.evaluations.cycles.find_open_for(employee_id).id)


def test_meta_from_server_clock_and_rules(st):
    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = s.MetaOut.model_validate(r.json())
    assert meta.dzis == date(2026, 6, 15) and meta.tryb_ai is s.TrybAI.OFF
    assert meta.funkcje_ai["przygotowanie_rozmowy"] is True and meta.funkcje_ai["szkic_uzasadnienia"] is False
    assert meta.skala_punktow == [1, 3, 5, 7, 9] and meta.maks_kryteriow_dodatkowych == 3
    assert meta.progi_poziomow[s.Poziom.ZNACZNIE_PONIZEJ] == (1.0, 2.0)  # § 11 ust. 1 pkt 2
    assert meta.progi_poziomow[s.Poziom.NA_POZIOMIE] == (4.0, 6.0)


def test_conversation_prep_matches_contract_and_defaults_to_starting_conversation(st):
    r = client.post(f"/api/evaluations/{_eval_id(st)}/ai/conversation-prep")
    assert r.status_code == 200
    prep = s.ConversationPrepOut.model_validate(r.json())
    assert prep.rodzaj == "ROZPOCZYNAJACA"  # criteria not confirmed yet
    assert prep.zrodlo_tekstow == "SZABLON"  # AI off -> templates, still useful
    assert len(prep.kryteria) == 5 and all(k.pytania for k in prep.kryteria)
    assert not {"punkty", "srednia", "poziom", "wynik"} & set(r.json())  # never scores in the note


def test_conversation_prep_kind_can_be_chosen(st):
    r = client.post(f"/api/evaluations/{_eval_id(st)}/ai/conversation-prep", params={"rodzaj": "OCENIAJACA"})
    assert r.status_code == 200 and r.json()["rodzaj"] == "OCENIAJACA"


def test_conversation_prep_after_criteria_confirmed_is_evaluating(st):
    cid = st.evaluations.cycles.find_open_for(EMP).id
    st.evaluations.set_criteria(cid, BOSS, [])
    st.evaluations.confirm_criteria(cid, EMP)
    assert client.post(f"/api/evaluations/{cid}/ai/conversation-prep").json()["rodzaj"] == "OCENIAJACA"


def test_only_the_evaluator_sees_the_prep_note(st):
    url = f"/api/evaluations/{_eval_id(st)}/ai/conversation-prep"
    assert client.post(url, headers={"X-User-Id": BOSS}).status_code == 200
    r = client.post(url, headers={"X-User-Id": EMP})
    assert r.status_code == 403
    err = s.ApiError.model_validate(r.json())
    assert err.kod == "BRAK_UPRAWNIEN" and "oceniający" in err.komunikat


def test_unknown_evaluation_is_404_in_api_error_shape(st):
    r = client.post("/api/evaluations/999/ai/conversation-prep")
    assert r.status_code == 404
    err = s.ApiError.model_validate(r.json())
    assert err.kod == "NIE_ZNALEZIONO" and "999" in err.komunikat


def test_bad_query_value_is_422_in_api_error_shape(st):
    r = client.post(f"/api/evaluations/{_eval_id(st)}/ai/conversation-prep", params={"rodzaj": "INNA"})
    assert r.status_code == 422
    err = s.ApiError.model_validate(r.json())
    assert err.kod == "BLEDNE_ZAPYTANIE" and err.walidacje[0].pole == "rodzaj" and err.walidacje[0].waga is s.Waga.BLAD


def test_evaluation_ids_are_numbers(st):
    assert all(c.id.isdigit() for c in st.evaluations.cycles.list_all())


def test_openapi_lists_the_new_endpoints():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/meta" in paths and "/api/evaluations/{evaluation_id}/ai/conversation-prep" in paths
