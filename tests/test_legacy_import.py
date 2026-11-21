"""T23: import of old evaluations – the filled KPRM sample sheets (server/data/kprm/przyklady/) are read back to
the reference values (average, level, outcome, people), a deliberately broken average is caught, HR corrects
fields and approves; the evaluation joins the history as an imported finished cycle with the original file."""
from datetime import date
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app.api import state as state_mod
from app.api.state import get_state, reset_state
from app.application import legacy_import as li
from app.domain.cycle import Status
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from backend import kprm
from backend.main import app

ADMIN = {"X-User-Id": "kadry"}
client = TestClient(app)
RULES = kprm_rulebook()
SAMPLES = dict(kprm.example_evaluations())

# reference values: what the sample sheets declare (pracownicy.json "scenariusz_demo" + the form itself)
REFERENCE = {
    "1-arkusz-oceny-a-glw.md": ("A", "janina.kowalska", "adam.nowak", Fraction(11, 2), "na poziomie oczekiwań", "pozytywna"),
    "2-arkusz-oceny-b-naczelnik.md": ("B", "janina.nowak", "romuald.gut", Fraction(27, 4), "powyżej oczekiwań", "pozytywna"),
    "5-arkusz-oceny-c-radca.md": ("C", "roman.kowal", "iwona.kladka", Fraction(63, 10), "powyżej oczekiwań", "pozytywna"),
    "09-arkusz-oceny-c-gł-specjalista-neg.md": ("C", "adam.wzor", "bartlomiej.przelozony", Fraction(33, 10),
                                                "poniżej oczekiwań", "negatywna"),
    "10-arkusz-oceny-c-archiwista.md": ("C", "celina.przykladowa", "dorota.oceniajaca", Fraction(5), "na poziomie oczekiwań",
                                        "pozytywna"),
    "11-arkusz-oceny-c-główny-analityk.md": ("C", "ewelina.probka", "franciszek.szef", Fraction(7), "powyżej oczekiwań",
                                             "pozytywna"),
    "12-arkusz-oceny-c-specjalista-negatywna.md": ("C", "grzegorz.wzor", "henryk.pryncypal", Fraction(19, 5),
                                                   "poniżej oczekiwań", "negatywna"),
}


def parse(name, text=None):
    return li.match_people(li.parse_sheet(text or SAMPLES[name], RULES), KprmEmployeeDirectory().all())


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_sample_sheets_match_the_reference(name):
    s = parse(name)
    assert (s.sheet, s.employee_id, s.evaluator_id, s.declared_average, s.level, s.outcome) == REFERENCE[name]
    assert s.evaluated_on is not None and set(RULES.mandatory(s.sheet)) <= set(s.scores)
    assert not li.blocking(li.check(s, RULES))


def test_scores_read_from_the_form_and_the_justification():
    radca = parse("5-arkusz-oceny-c-radca.md")
    assert radca.scores == {"wykorzystywanie_wiedzy": 5, "rzetelnosc": 7, "organizacja_pracy": 7, "wspolpraca": 7,
                            "komunikacja": 7, "myslenie_analityczne": 5}
    assert li.result_of(radca, RULES).average_display == 6.33  # declared 6,3 – the same within rounding
    assert radca.meeting_date == date(2026, 9, 10) and radca.period_from == date(2024, 9, 11)
    assert radca.justification.startswith("Pan Roman Kowal") and radca.iprz.startswith("Rekomenduję")
    neg = parse("09-arkusz-oceny-c-gł-specjalista-neg.md")
    assert neg.scores["rzetelnosc"] == 1 and neg.scores["wspolpraca"] == 1  # X in the first column = 1 point


def test_missing_average_is_flagged():
    problems = li.check(parse("4-arkusz-oceny-c-główny-spec-neg.md"), RULES)
    assert "BRAK_SREDNIEJ" in {p.code for p in li.blocking(problems)}


def test_deliberately_broken_average_is_detected():
    text = SAMPLES["1-arkusz-oceny-a-glw.md"].replace("kryteria oceny: | 5,5", "kryteria oceny: | 7,5")
    codes = {p.code for p in li.check(parse("1-arkusz-oceny-a-glw.md", text), RULES)}
    assert "POZIOM_NIEZGODNY" in codes  # 7,5 is "powyżej oczekiwań", the form marks "na poziomie"
    text = SAMPLES["5-arkusz-oceny-c-radca.md"].replace("kryteria oceny: | 6,3", "kryteria oceny: | 6,9")
    codes = {p.code for p in li.check(parse("5-arkusz-oceny-c-radca.md", text), RULES)}
    assert "SREDNIA_NIEZGODNA" in codes  # the partial scores give 6,33


def test_outcome_inconsistent_with_a_one_point_score():
    s = parse("09-arkusz-oceny-c-gł-specjalista-neg.md")
    s.outcome = "pozytywna"
    assert "WYNIK_NIEZGODNY" in {p.code for p in li.check(s, RULES)}


def upload(name, text=None):
    data = (text or SAMPLES[name]).encode("utf-8")
    return client.post("/api/legacy-import", headers=ADMIN, files={"file": (name, data, "text/markdown")})


def test_verification_and_approval_through_the_api():
    st = reset_state(today=date(2026, 11, 21), ai_mode="off")
    assert client.post("/api/legacy-import", headers={"X-User-Id": "henryk.pryncypal"},
                       files={"file": ("a.md", b"x", "text/markdown")}).status_code == 403
    draft = upload("4-arkusz-oceny-c-główny-spec-neg.md").json()
    assert draft["status"] == "ROBOCZY" and draft["pola"]["pracownik"] == "Adam Kowalik"
    url = f"/api/legacy-import/{draft['id']}"
    assert client.post(f"{url}/approve", headers=ADMIN, json={}).status_code == 422  # no average yet
    fixed = client.put(url, headers=ADMIN, json={"punkty": {
        "WYKORZYSTYWANIE_WIEDZY": 5, "ORGANIZACJA_PRACY": 5, "WSPOLPRACA": 5, "KOMUNIKACJA": 5}}).json()
    assert fixed["wyliczone"] == {"srednia": 4.2, "poziom": "na poziomie oczekiwań", "wynik": "negatywna"}
    assert not [p for p in fixed["rozbieznosci"] if p["waga"] == "BLAD"]
    done = client.post(f"{url}/approve", headers=ADMIN, json={}).json()
    assert done["status"] == "ZATWIERDZONY" and done["evaluation_id"]
    c = st.evaluations.cycles.get(str(done["evaluation_id"]))
    assert c.imported and c.status is Status.ACKNOWLEDGED and c.result.outcome.value == "negatywna"
    assert c.result.average == Fraction(21, 5) and c.evaluated_on == date(2026, 10, 14)
    assert client.post(f"{url}/approve", headers=ADMIN, json={}).status_code == 409
    original = client.get(f"{url}/file", headers=ADMIN)
    assert original.status_code == 200 and "Adam" in original.text
    # the imported evaluation is history: shown to HR, not counted in the progress report
    assert client.get(f"/api/evaluations/{c.id}", headers=ADMIN).json()["status"] == "ZAKONCZONA"
    progress = client.get("/api/reports/progress", headers=ADMIN).json()
    assert progress["cykle"] == len([x for x in st.evaluations.cycles.list_all() if not x.imported])


def test_discrepancies_block_unless_accepted_and_drafts_survive_a_restart():
    reset_state(today=date(2026, 11, 21), ai_mode="off")
    text = SAMPLES["1-arkusz-oceny-a-glw.md"].replace("kryteria oceny: | 5,5", "kryteria oceny: | 7,5")
    draft = upload("1-arkusz-oceny-a-glw.md", text).json()
    url = f"/api/legacy-import/{draft['id']}"
    assert any(p["kod"] == "POZIOM_NIEZGODNY" for p in draft["rozbieznosci"])
    state_mod.save_state()
    state_mod._state = None
    assert get_state().legacy_imports[draft["id"]].sheet.declared_average == Fraction(15, 2)
    r = client.post(f"{url}/approve", headers=ADMIN, json={})
    assert r.status_code == 422 and "Popraw pola" in r.text
    assert client.post(f"{url}/approve", headers=ADMIN, json={"akceptuje_rozbieznosci": True}).status_code == 200
