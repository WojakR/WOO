"""Burnout checklist (8 symptoms) at the review meeting: saved with the cycle, only for the evaluator / deputy /
HR, never in the PDF nor for the evaluated person; enough "często" answers raise the HR partner's signal."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.domain.errors import ValidationError
from app.domain.wellbeing import Frequency, WellbeingCheck, SymptomAnswer, overload_evidence, parse_answers
from backend import kprm
from backend.main import app

EMP, BOSS, HR = "grzegorz.wzor", "henryk.pryncypal", "kadry"
client = TestClient(app)
IDS = [x["id"] for x in kprm.wellbeing()["objawy"]]


@pytest.fixture
def st():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    svc.set_criteria(cid, BOSS, [])
    svc.confirm_criteria(cid, EMP)
    svc.record_review_meeting(cid, BOSS)
    st.cid = cid
    return st


def put(st, who, answers):
    return client.put(f"/api/evaluations/{st.cid}/wellbeing", headers={"X-User-Id": who}, json={"odpowiedzi": answers})


HEAVY = {"zmeczenie": {"odpowiedz": "CZESTO", "komentarz": "Grzegorz mówi, że nie odpoczywa w weekendy."},
         "regeneracja": {"odpowiedz": "CZESTO"}, "motywacja": {"odpowiedz": "CZESTO"},
         "emocje": {"odpowiedz": "CZASAMI"}}


def test_the_list_is_data_with_eight_areas():
    data = client.get("/api/wellbeing/checklist").json()
    assert [x["id"] for x in data["objawy"]] == ["zmeczenie", "koncentracja", "emocje", "motywacja", "nastawienie",
                                                 "efektywnosc", "regeneracja", "zachowanie"]
    assert data["instrukcja"] and len(data["odpowiedzi"]) == 3


def test_saving_and_reading_back(st):
    r = put(st, BOSS, HEAVY)
    assert r.status_code == 200, r.text
    body = client.get(f"/api/evaluations/{st.cid}/wellbeing", headers={"X-User-Id": BOSS}).json()
    assert body["odpowiedzi"]["zmeczenie"]["odpowiedz"] == "CZESTO"
    assert body["liczba_czesto"] == 3 and body["sygnal_przeciazenia"] is True
    assert st.wellbeing[st.cid].updated_by == BOSS


def test_wrong_answers_are_rejected(st):
    assert put(st, BOSS, {"zmeczenie": {"odpowiedz": "ZAWSZE"}}).status_code == 422
    assert put(st, BOSS, {"glowa": {"odpowiedz": "CZESTO"}}).status_code == 422
    with pytest.raises(ValidationError):
        parse_answers({"zmeczenie": {"odpowiedz": "CZESTO", "komentarz": "x" * 501}}, IDS)


def test_only_evaluator_deputy_and_hr(st):
    put(st, BOSS, HEAVY)
    url = f"/api/evaluations/{st.cid}/wellbeing"
    assert client.get(url, headers={"X-User-Id": EMP}).status_code == 403  # never the evaluated person
    assert client.get(url, headers={"X-User-Id": HR}).status_code == 200  # HR partner
    assert put(st, EMP, HEAVY).status_code == 403
    assert put(st, HR, HEAVY).status_code == 403  # HR reads, the evaluator fills it in


def test_never_in_the_pdf(st, monkeypatch):
    put(st, BOSS, HEAVY)
    import backend.sheet_pdf as sheet_pdf

    captured = {}
    real = sheet_pdf.render_sheet_pdf
    monkeypatch.setattr(sheet_pdf, "render_sheet_pdf", lambda data: captured.setdefault("data", data) and real(data))
    r = client.get(f"/api/evaluations/{st.cid}/pdf", headers={"X-User-Id": BOSS})
    assert r.status_code == 200
    text = repr(captured["data"])
    assert "weekendy" not in text and "CZESTO" not in text and "dobrostan" not in text.casefold()


def test_hr_partner_gets_the_overload_signal(st):
    url = f"/api/evaluations/{st.cid}/hr-partner"
    assert "PRZECIAZENIE" not in [s["typ"] for s in client.get(url, headers={"X-User-Id": BOSS}).json()["sygnaly"]]
    put(st, BOSS, HEAVY)
    sig = next(s for s in client.get(url, headers={"X-User-Id": BOSS}).json()["sygnaly"] if s["typ"] == "PRZECIAZENIE")
    assert "3 z 8" in sig["dowody"][0]


def test_below_the_threshold_no_signal():
    check = WellbeingCheck("1", {"zmeczenie": SymptomAnswer(Frequency.OFTEN)}, date(2026, 6, 1))
    assert overload_evidence(check, {"zmeczenie": "Zmęczenie"}, 3) == []
    assert overload_evidence(None, {}, 1) == []


def test_comments_are_pseudonymised_before_the_model():
    """With a model on, the evidence (incl. checklist comments) goes into the prompt masked."""
    from app.application.ports import AiUnavailable
    from app.infrastructure.assistant_factory import build_assistant

    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for(EMP).id
    prompts = []

    class Spy:
        name = "spy"

        def available(self):
            return True

        def complete_json(self, system, prompt, schema, task):
            prompts.append(prompt)
            raise AiUnavailable("test")

    assistant = build_assistant("off")
    assistant.model = Spy()
    check = WellbeingCheck(cid, {k: SymptomAnswer(Frequency.OFTEN, "Grzegorz Wzór pracuje nocami.")
                                 for k in ("zmeczenie", "regeneracja", "motywacja")}, date(2026, 6, 1))
    st.wellbeing[cid] = check
    report = assistant.hr_partner(svc.cycles.get(cid), st.directory.get(EMP), [], [], date(2026, 6, 1),
                                  extra=st.hr_extra_evidence(svc.cycles.get(cid)))
    assert report.source == "REGULY" and prompts
    assert "Grzegorz" not in prompts[0] and "Wzór" not in prompts[0]
