"""Notes endpoints and their effect: tagged notes are the evidence for the conversation prep and the drafts."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import schemas as s
from app.api.state import reset_state
from backend.main import app

client = TestClient(app)
EMP, BOSS, OTHER = "grzegorz.wzor", "henryk.pryncypal", "adam.wzor"
AS_BOSS = {"X-User-Id": BOSS}


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


def _eid(st) -> int:
    return int(st.evaluations.cycles.find_open_for(EMP).id)


def _add(eid, **fields):
    body = {"data": "2026-06-10", "tresc": "Notatka z obserwacji.", **fields}
    return client.post(f"/api/evaluations/{eid}/notes", json=body, headers=AS_BOSS)


def test_tagged_note_is_saved_as_manual(st):
    r = _add(_eid(st), tresc="Pismo do wydziału było jasne.", criterion_kod="KOMUNIKACJA", wydzwiek="POZYTYWNY")
    assert r.status_code == 201
    n = s.NoteOut.model_validate(r.json())
    assert n.criterion_kod == "KOMUNIKACJA" and n.wydzwiek is s.Wydzwiek.POZYTYWNY and n.status_klasyfikacji == "RECZNA"
    assert n.autor.imie == "Henryk" and n.autor.id > 0


def test_untagged_note_gets_suggestions_in_the_background_but_no_criterion(st):
    eid = _eid(st)
    r = _add(eid, tresc="Obsługa interesanta przy okienku trwała zbyt długo.")
    assert r.status_code == 201 and r.json()["status_klasyfikacji"] == "W_TOKU"
    n = client.get(f"/api/evaluations/{eid}/notes", headers=AS_BOSS).json()[0]
    assert n["status_klasyfikacji"] in ("SUGESTIA", "DO_PRZYPISANIA") and n["zrodlo_sugestii"] == "REGULY"
    assert n["sugestie_ai"] and n["criterion_kod"] is None  # AI only suggests


def test_accepting_a_suggestion_makes_the_note_evidence(st):
    eid = _eid(st)
    note_id = _add(eid, tresc="Obsługa interesanta przy okienku trwała zbyt długo.").json()["id"]
    # the no-AI fallback has no sentiment -> the evaluator must give it
    assert client.patch(f"/api/notes/{note_id}", json={"zaakceptuj_sugestie": True}, headers=AS_BOSS).status_code == 422
    r = client.patch(f"/api/notes/{note_id}", json={"zaakceptuj_sugestie": True, "wydzwiek": "NEGATYWNY"},
                     headers=AS_BOSS)
    assert r.status_code == 200
    n = r.json()
    assert n["status_klasyfikacji"] == "ZATWIERDZONA" and n["criterion_kod"] and n["wydzwiek"] == "NEGATYWNY"


def test_manual_tagging_and_unknown_criterion(st):
    eid = _eid(st)
    note_id = _add(eid).json()["id"]
    r = client.patch(f"/api/notes/{note_id}", json={"criterion_kod": "RZETELNOSC", "wydzwiek": "NEUTRALNY"},
                     headers=AS_BOSS)
    assert r.status_code == 200 and r.json()["status_klasyfikacji"] == "RECZNA"
    bad = _add(eid, criterion_kod="ZARZADZANIE_STRATEGICZNE")  # not in sheet C
    assert bad.status_code == 422 and "nie należy do tej oceny" in bad.json()["walidacje"][0]["komunikat"]


def test_who_sees_which_notes(st):
    eid = _eid(st)
    _add(eid, tresc="Widoczna.", widoczna_dla_ocenianego=True)
    _add(eid, tresc="Robocza.")
    assert len(client.get(f"/api/evaluations/{eid}/notes", headers=AS_BOSS).json()) == 2
    own = client.get(f"/api/evaluations/{eid}/notes", headers={"X-User-Id": EMP}).json()
    assert [n["tresc"] for n in own] == ["Widoczna."]
    assert client.get(f"/api/evaluations/{eid}/notes", headers={"X-User-Id": OTHER}).status_code == 403


def test_only_the_evaluator_writes_notes(st):
    eid = _eid(st)
    r = client.post(f"/api/evaluations/{eid}/notes", json={"data": "2026-06-10", "tresc": "x"},
                    headers={"X-User-Id": EMP})
    assert r.status_code == 403 and r.json()["kod"] == "BRAK_UPRAWNIEN"


def test_delete_and_404(st):
    eid = _eid(st)
    note_id = _add(eid).json()["id"]
    assert client.delete(f"/api/notes/{note_id}", headers=AS_BOSS).status_code == 204
    assert client.get(f"/api/evaluations/{eid}/notes").json() == []
    r = client.patch(f"/api/notes/{note_id}", json={"tresc": "x"})
    assert r.status_code == 404 and r.json()["kod"] == "NIE_ZNALEZIONO"


def test_empty_text_is_422(st):
    assert _add(_eid(st), tresc="").status_code == 422


# ---------------------------------------------------------------- notes reach the AI features

NEGATIVE = "Nie przekazał informacji zespołowi o zmianie terminu, przez co sprawa się opóźniła."


def test_tagged_notes_are_evidence_in_the_conversation_prep(st):
    eid = _eid(st)
    _add(eid, tresc=NEGATIVE, criterion_kod="WSPOLPRACA", wydzwiek="NEGATYWNY")
    _add(eid, tresc="Bez przypisania – nie liczy się jako dowód.")
    prep = client.post(f"/api/evaluations/{eid}/ai/conversation-prep", params={"rodzaj": "OCENIAJACA"}).json()
    by_code = {k["criterion_kod"]: k for k in prep["kryteria"]}
    assert by_code["WSPOLPRACA"]["minus"] == 1 and NEGATIVE in [p["tresc"] for p in by_code["WSPOLPRACA"]["przyklady"]]
    assert sum(k["plus"] + k["minus"] for k in prep["kryteria"]) == 1  # the untagged note is not evidence


def test_tagged_notes_are_quoted_in_the_justification_draft(st):
    eid = _eid(st)
    _add(eid, tresc=NEGATIVE, criterion_kod="WSPOLPRACA", wydzwiek="NEGATYWNY")
    cid = str(eid)
    st.evaluations.set_criteria(cid, BOSS, [])
    st.evaluations.confirm_criteria(cid, EMP)
    st.evaluations.record_review_meeting(cid, BOSS)
    ids = st.evaluations.cycles.get(cid).criteria_ids(st.evaluations.rules)
    st.evaluations.edit(cid, BOSS, scores={c: (1 if c == "wspolpraca" else 5) for c in ids})
    d = client.post(f"/api/evaluations/{eid}/ai/draft", json={"rodzaj": "UZASADNIENIE"}).json()
    assert NEGATIVE in d["tekst"] and d["oparte_na_notatkach"]
