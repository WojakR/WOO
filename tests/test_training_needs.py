"""T19: training needs from low partial scores – per person, ranking, CSV, works with LLM_MOCK and with AI off."""
from datetime import date

from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application import training_needs as tn
from app.infrastructure.assistant_factory import build_assistant
from backend import kprm
from backend.main import app

from report_fixtures import build

client = TestClient(app)
AREAS = {cid: c["obszar_szkoleniowy"] for cid, c in kprm.criteria().items()}


def test_every_criterion_has_a_training_area_in_the_data():
    assert all(c.get("obszar_szkoleniowy") for c in kprm.criteria().values())


def test_person_and_ranking():
    svc, clock, people, ids = build()
    persons, ranking = tn.analyse(people, svc.cycles.list_all(), svc.rules, 5, AREAS)
    assert [p.employee_id for p in persons] == ["a.1", "a.2", "a.3"]
    a1 = persons[0]
    assert [(n.criterion_id, n.score) for n in a1.needs] == [("rzetelnosc", 1), ("komunikacja", 3)]
    assert a1.needs[1].area.startswith("Komunikacja interpersonalna") and a1.iprz == "Szkolenie 1."
    assert [(r.criterion_id, r.low_scores, r.evaluated) for r in ranking] == [("komunikacja", 3, 5), ("rzetelnosc", 1, 5)]
    assert tn.analyse(people, svc.cycles.list_all(), svc.rules, 5, AREAS, unit="Wydział B") == ([], [])


def test_csv():
    svc, clock, people, ids = build()
    persons, _ = tn.analyse(people, svc.cycles.list_all(), svc.rules, 5, AREAS)
    lines = tn.to_csv(persons).strip().splitlines()
    assert lines[0].startswith("pracownik;komorka;kryterium") and len(lines) == 5
    assert "Rzetelność;1;" in lines[1]


def test_recommendation_with_ai_off_and_with_the_mock():
    svc, clock, people, ids = build()
    _, ranking = tn.analyse(people, svc.cycles.list_all(), svc.rules, 5, AREAS)
    fallback = tn.template_recommendation(ranking)
    assert "Komunikacja interpersonalna" in fallback and "3 osoby" in fallback
    for mode in ("off", "local"):  # local: no model running in tests (LLM_MOCK=1) -> the template
        text, source = build_assistant(mode).training_recommendation(ranking, "urzędu", fallback)
        assert source == "SZABLON" and text == fallback


def test_api_and_csv_export():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    svc = st.evaluations
    cid = svc.cycles.find_open_for("grzegorz.wzor").id
    svc.set_criteria(cid, "henryk.pryncypal", [])
    svc.confirm_criteria(cid, "grzegorz.wzor")
    svc.record_review_meeting(cid, "henryk.pryncypal")
    ids = svc.cycles.get(cid).criteria_ids(svc.rules)
    svc.submit_evaluation(cid, "henryk.pryncypal", scores={i: (3 if i == "rzetelnosc" else 7) for i in ids},
                          iprz_conclusions="Kurs redakcji tekstów.")
    r = client.get("/api/reports/training-needs", headers={"X-User-Id": "henryk.pryncypal"}).json()
    assert r["ranking"][0]["kryterium"] == "Rzetelność" and r["zrodlo"] == "SZABLON"
    assert r["osoby"][0]["wnioski_iprz"] == "Kurs redakcji tekstów."
    st.ai_office = False  # AI switched off for the office: still the template
    assert client.get("/api/reports/training-needs", headers={"X-User-Id": "kadry"}).json()["zrodlo"] == "SZABLON"
    csv = client.get("/api/reports/training-needs.csv", headers={"X-User-Id": "kadry"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "Grzegorz Wzór;Referat Przekładów;Rzetelność;3;" in csv.text
    assert client.get("/api/reports/training-needs", headers={"X-User-Id": "grzegorz.wzor"}).status_code == 403
