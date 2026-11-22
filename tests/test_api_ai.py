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
    assert meta.funkcje_ai["przygotowanie_rozmowy"] is True and meta.funkcje_ai["hr_partner"] is True
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
    assert "/api/evaluations/{evaluation_id}/ai/draft" in paths


# ---------------------------------------------------------------- POST /api/evaluations/{id}/ai/draft

def _after_meeting(st, scores=None) -> str:
    cid = st.evaluations.cycles.find_open_for(EMP).id
    st.evaluations.set_criteria(cid, BOSS, [])
    st.evaluations.confirm_criteria(cid, EMP)
    st.evaluations.record_review_meeting(cid, BOSS)
    if scores:
        ids = st.evaluations.cycles.get(cid).criteria_ids(st.evaluations.rules)
        st.evaluations.edit(cid, BOSS, scores=dict(zip(ids, scores, strict=True)))
    return cid


def _draft(cid, rodzaj, **kw):
    return client.post(f"/api/evaluations/{cid}/ai/draft", json={"rodzaj": rodzaj}, **kw)


@pytest.mark.parametrize("rodzaj", ["UZASADNIENIE", "IPRZ"])
def test_draft_after_the_review_meeting(st, rodzaj):
    cid = _after_meeting(st, [3, 3, 5, 1, 3])  # one criterion at 1 pt -> negative
    r = _draft(cid, rodzaj, headers={"X-User-Id": BOSS})
    assert r.status_code == 200
    d = s.DraftOut.model_validate(r.json())
    assert d.rodzaj == rodzaj and d.zrodlo == "SZABLON" and len(d.tekst) > 30


def test_draft_is_never_saved_into_the_evaluation(st):
    cid = _after_meeting(st, [3, 3, 5, 1, 3])
    before = st.evaluations.cycles.get(cid)
    _draft(cid, "UZASADNIENIE")
    after = st.evaluations.cycles.get(cid)
    assert (after.justification, after.iprz_conclusions, after.scores, after.status) == \
           (before.justification, before.iprz_conclusions, before.scores, before.status)


def test_draft_before_the_review_meeting_is_409(st):
    cid = st.evaluations.cycles.find_open_for(EMP).id  # cycle just started
    r = _draft(cid, "UZASADNIENIE")
    assert r.status_code == 409
    err = s.ApiError.model_validate(r.json())
    assert err.kod == "POLE_ZABLOKOWANE" and "po rozmowie oceniającej" in err.komunikat


def test_grade_motivation_only_with_positive_evaluation(st):
    cid = _after_meeting(st, [3, 3, 5, 1, 3])  # negative
    r = _draft(cid, "UMOTYWOWANIE_STOPNIA")
    assert r.status_code == 409 and "pozytywnej" in r.json()["komunikat"]


def test_grade_motivation_needs_all_scores(st):
    cid = _after_meeting(st)  # no scores yet
    assert _draft(cid, "UMOTYWOWANIE_STOPNIA").status_code == 409


def test_grade_motivation_with_positive_evaluation(st):
    cid = _after_meeting(st, [7, 7, 9, 7, 7])
    r = _draft(cid, "UMOTYWOWANIE_STOPNIA")
    assert r.status_code == 200 and r.json()["rodzaj"] == "UMOTYWOWANIE_STOPNIA"


def test_only_the_evaluator_gets_a_draft(st):
    cid = _after_meeting(st, [3, 3, 5, 1, 3])
    r = _draft(cid, "UZASADNIENIE", headers={"X-User-Id": EMP})
    assert r.status_code == 403 and r.json()["kod"] == "BRAK_UPRAWNIEN"


def test_draft_unknown_kind_is_422(st):
    cid = _after_meeting(st)
    r = _draft(cid, "LIST_MOTYWACYJNY")
    assert r.status_code == 422 and r.json()["kod"] == "BLEDNE_ZAPYTANIE"


def test_meta_shows_the_draft_button(st):
    assert client.get("/api/meta").json()["funkcje_ai"]["szkic_uzasadnienia"] is True


def test_suggest_criteria_matches_contract_and_sets_nothing(st):
    eid = _eval_id(st)
    before = client.get(f"/api/evaluations/{eid}", headers={"X-User-Id": BOSS}).json()["kryteria"]
    r = client.post(f"/api/evaluations/{eid}/ai/suggest-criteria", headers={"X-User-Id": BOSS},
                    json={"opis": "Obsługa interesantów i korespondencja z klientami"})
    assert r.status_code == 200
    out = s.SuggestCriteriaOut.model_validate(r.json())
    assert out.zrodlo == "REGULY" and 1 <= len(out.sugestie) <= 3  # AI off -> keywords, still useful
    assert all(x.uzasadnienie for x in out.sugestie)
    after = client.get(f"/api/evaluations/{eid}", headers={"X-User-Id": BOSS}).json()["kryteria"]
    assert after == before  # never applied automatically


def test_suggest_criteria_body_is_optional_and_evaluator_only(st):
    url = f"/api/evaluations/{_eval_id(st)}/ai/suggest-criteria"
    assert client.post(url, headers={"X-User-Id": BOSS}).status_code == 200
    assert client.post(url, headers={"X-User-Id": EMP}).status_code == 403
