"""AI suggestion service: every feature with AI off (fallback), with a fake model (validation),
pseudonymisation, and the not-implemented API adapter. No real model is called."""
import json
from datetime import date

import pytest

from app.application.assistant import AiSuggestionService, fill_template
from app.application.ports import AiInvalidOutput, AiUnavailable
from app.application.privacy import Pseudonymizer
from app.application.use_cases import EvaluationService
from app.domain.deadlines import Absence
from app.domain.notes import Note, Sentiment
from app.infrastructure.ai_models import ApiModel, OffModel, OllamaModel, build_ai_model
from app.infrastructure.assistant_factory import build_assistant, kprm_catalog
from app.infrastructure.kprm_adapter import KprmEmployeeDirectory, kprm_rulebook
from app.infrastructure.memory import FixedClock, InMemoryCycleRepository

R = kprm_rulebook()
DIR = KprmEmployeeDirectory()
EMP, BOSS = "grzegorz.wzor", "henryk.pryncypal"
ADDITIONAL = ["orientacja_na_klienta", "kreatywnosc"]
TODAY = date(2026, 6, 15)


class FakeModel:
    """Returns queued answers; records prompts. An Exception in the queue is raised."""

    name = "fake"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def available(self):
        return True

    def _next(self, prompt):
        self.prompts.append(prompt)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    def complete_json(self, system, prompt, schema, task):
        return self._next(prompt)

    def complete_text(self, system, prompt, task):
        return self._next(prompt)

    def stream_text(self, system, prompt, task):
        yield from self._next(prompt)


def service(model=None):
    return AiSuggestionService(R, model or OffModel(), kprm_catalog())


@pytest.fixture
def cycle():
    svc = EvaluationService(R, InMemoryCycleRepository(), DIR, FixedClock(TODAY))
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    svc.confirm_criteria(c.id, EMP)
    svc.record_review_meeting(c.id, BOSS)
    return svc.cycles.get(c.id)


def scored(cycle, values):
    cycle.scores = dict(zip(cycle.criteria_ids(R), values, strict=True))
    return cycle


NOTES = [
    Note("n1", date(2026, 3, 12), "Zamiast zadzwonić do wydziału po brakujący dokument, odrzucił wniosek.",
         criterion_id="wspolpraca", sentiment=Sentiment.NEGATIVE),
    Note("n2", date(2026, 4, 2), "Odpowiedź do interesanta była zawiła, interesant dzwonił z pytaniami.",
         criterion_id="orientacja_na_klienta", sentiment=Sentiment.NEGATIVE),
    Note("n3", date(2026, 5, 5), "Tłumaczenie umowy bez żadnych poprawek merytorycznych.",
         criterion_id="rzetelnosc", sentiment=Sentiment.POSITIVE),
    Note("n4", date(2026, 5, 20), "Grzegorz Wzór znowu siedział po godzinach, żeby nadrobić zaległości."),
    Note("n5", date(2026, 6, 1), "Pracował w weekend nad raportem, wygląda na zmęczonego."),
    Note("n6", date(2026, 6, 3), "Przejął nowe obowiązki po koleżance z referatu."),
]
EMPLOYEE, EVALUATOR = DIR.get(EMP), DIR.get(BOSS)


# ---------------------------------------------------------------- configuration

def test_build_model_by_mode():
    assert isinstance(build_ai_model("off"), OffModel)
    assert isinstance(build_ai_model("local"), OllamaModel)
    assert isinstance(build_ai_model("api"), ApiModel)
    with pytest.raises(ValueError):
        build_ai_model("chmura")


def test_local_model_is_unavailable_in_tests_so_features_fall_back():
    a = build_assistant("local")
    assert a.model.available() is False  # LLM_MOCK=1
    assert a.suggest_criteria(EMPLOYEE).source == "REGULY"


def test_api_adapter_falls_back_in_tests_and_when_the_provider_fails(cycle, monkeypatch):
    from backend import config, llm

    a = service(ApiModel(["anthropic/claude-sonnet-5-5"]))
    assert a.model.available() is False  # LLM_MOCK=1: nothing leaves the machine in tests
    monkeypatch.setattr(config, "LLM_MOCK", False)
    assert a.model.available() is True

    def down(*args, **kwargs):
        raise RuntimeError("Żaden model nie odpowiedział")

    monkeypatch.setattr(llm, "_complete", down)
    assert a.suggest_criteria(EMPLOYEE).source == "REGULY"  # provider down -> the no-AI version, no exception
    assert "".join(a.draft_stream("UZASADNIENIE", cycle, EMPLOYEE, NOTES))  # template in one piece


def test_api_adapter_sends_only_pseudonymised_text_and_parses_json(monkeypatch):
    from backend import config, llm

    monkeypatch.setattr(config, "LLM_MOCK", False)
    sent = []

    def fake(system, prompt, json_mode, temperature):
        sent.append((system, prompt, json_mode))
        return '```json\n{"ok": true}\n```'

    monkeypatch.setattr(llm, "_complete", fake)
    m = ApiModel(["openai/gpt-4o-mini"])
    assert m.complete_json("System.", "Ocena: Grzegorz Wzór, grzegorz@urzad.example", {"type": "object"},
                           "draft") == {"ok": True}
    system, prompt, json_mode = sent[0]
    assert json_mode and '"type": "object"' in system  # the schema goes with the request
    assert "Grzegorz" not in prompt and "Wzór" not in prompt and "@" not in prompt
    monkeypatch.setattr(llm, "_complete", lambda *a: "to nie jest JSON")
    from app.application.ports import AiInvalidOutput
    with pytest.raises(AiInvalidOutput):
        m.complete_json("S", "P", {}, "draft")


# ---------------------------------------------------------------- pseudonymisation

def test_pseudonymizer_masks_inflected_names_pesel_email_and_restores():
    p = Pseudonymizer([("Grzegorz", "Wzór"), ("Henryk", "Pryncypał")])
    masked = p.mask("Rozmowa Henryka Pryncypała z Grzegorzem Wzorem, PESEL 85010112345, grzegorz@urzad.gov.pl")
    assert "Grzeg" not in masked and "Henryk" not in masked and "85010112345" not in masked and "@" not in masked
    assert "[OSOBA_1]" in masked and "[OSOBA_2]" in masked and "[PESEL]" in masked
    assert p.unmask("[OSOBA_1] rozmawiał z [OSOBA_2]") == "Grzegorz Wzór rozmawiał z Henryk Pryncypał"


def test_model_never_sees_the_name(cycle):
    model = FakeModel(AiUnavailable("down"))
    service(model).draft("UZASADNIENIE", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE, NOTES)
    assert "Grzegorz" not in model.prompts[0] and "Wzór" not in model.prompts[0]


# ---------------------------------------------------------------- 1. note classification

def test_classification_with_valid_model_answer():
    model = FakeModel({"etykiety": [
        {"kryterium": "wspolpraca", "wskaznik": 2, "wydzwiek": "NEGATYWNY", "pewnosc": 0.9,
         "cytat": "Zamiast zadzwonić do wydziału"},
        {"kryterium": "nieistniejace", "wskaznik": 1, "wydzwiek": "NEGATYWNY", "pewnosc": 0.99, "cytat": "odrzucił"},
        {"kryterium": "komunikacja", "wskaznik": 1, "wydzwiek": "NEGATYWNY", "pewnosc": 0.7,
         "cytat": "tego zdania nie ma w notatce"},
    ]})
    out = service(model).classify_note(NOTES[0], "C", ADDITIONAL)
    assert out.source == "AI" and out.status == "SUGESTIA"
    assert [s.criterion_id for s in out.suggestions] == ["wspolpraca"]  # bad label and invented quote dropped
    s = out.suggestions[0]
    assert s.sentiment is Sentiment.NEGATIVE and s.indicator == R.criteria["wspolpraca"].indicators[1]


def test_low_confidence_goes_to_manual_assignment():
    model = FakeModel({"etykiety": [{"kryterium": "wspolpraca", "wskaznik": 0, "wydzwiek": "NEGATYWNY",
                                     "pewnosc": 0.3, "cytat": "odrzucił wniosek"}]})
    out = service(model).classify_note(NOTES[0], "C", ADDITIONAL)
    assert out.status == "DO_PRZYPISANIA" and out.source == "AI"


@pytest.mark.parametrize("answer", [
    {"etykiety": [{"kryterium": "spoza_listy", "wskaznik": 1, "wydzwiek": "NEGATYWNY", "pewnosc": 1, "cytat": "odrzucił"}]},
    {"cos_innego": []},
    {"etykiety": ["tekst zamiast obiektu"]},
    AiInvalidOutput("zły JSON"),
    AiUnavailable("ollama nie działa"),
])
def test_invalid_or_missing_answer_falls_back_to_similarity(answer):
    a = service(FakeModel(answer))
    out = a.classify_note(NOTES[0], "C", ADDITIONAL)
    assert out.source == "REGULY" and out.status == "DO_PRZYPISANIA"
    assert len(a.calls) == 1 and a.calls[0].ok is False


def test_fallback_similarity_finds_plausible_criteria():
    out = service().classify_note(Note("x", TODAY, "Interesant złożył skargę na obsługę i brak reakcji na jego potrzeby."),
                                  "C", ADDITIONAL)
    assert out.source == "REGULY" and out.suggestions
    assert "orientacja_na_klienta" in [s.criterion_id for s in out.suggestions]


# ---------------------------------------------------------------- 2. drafts

def test_draft_template_negative(cycle):
    d = service().draft("UZASADNIENIE", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE, NOTES)
    assert d.source == "SZABLON" and "ocenę negatywną" in d.text and "Grzegorz Wzór" in d.text
    assert "n1" in d.note_ids


def test_draft_iprz_template_uses_development_catalog(cycle):
    d = service().draft("IPRZ", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE, NOTES)
    assert d.source == "SZABLON" and "–" in d.text


def test_draft_from_model_restores_name_and_filters_ids(cycle):
    model = FakeModel({"tekst": "W okresie oceny [OSOBA_1] nie konsultował spraw z innymi wydziałami, co wydłużało postępowania.",
                       "notatki": ["n1", "n99"]})
    a = service(model)
    d = a.draft("UZASADNIENIE", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE, NOTES)
    assert d.source == "AI" and d.text.startswith("W okresie oceny Grzegorz Wzór") and d.note_ids == ("n1",)
    # cached: same inputs -> no second call
    assert a.draft("UZASADNIENIE", cycle, EMPLOYEE, NOTES) is d and len(model.prompts) == 1


def test_draft_with_unknown_token_is_rejected(cycle):
    model = FakeModel({"tekst": "Pracownik [OSOBA_7] wykonywał zadania poprawnie przez cały okres oceny.", "notatki": []})
    d = service(model).draft("UZASADNIENIE", scored(cycle, [5, 5, 5, 5, 5, 5, 5]), EMPLOYEE, NOTES)
    assert d.source == "SZABLON"


def test_draft_key_changes_with_scores(cycle):
    a = service()
    k1 = a.draft("UZASADNIENIE", scored(cycle, [5, 5, 5, 5, 5, 5, 5]), EMPLOYEE, NOTES).key
    k2 = a.draft("UZASADNIENIE", scored(cycle, [5, 5, 5, 5, 5, 5, 3]), EMPLOYEE, NOTES).key
    assert k1 != k2


def test_draft_stream_restores_split_tokens(cycle):
    model = FakeModel(["Ocena: [OSO", "BA_1] nie dzwonił ", "do wydziałów."])
    text = "".join(service(model).draft_stream("UZASADNIENIE", cycle, EMPLOYEE, NOTES))
    assert text == "Ocena: Grzegorz Wzór nie dzwonił do wydziałów."


def test_draft_stream_falls_back_to_template(cycle):
    text = "".join(service().draft_stream("IPRZ", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE, NOTES))
    assert text.startswith("Proponuję")


# ---------------------------------------------------------------- 3. conversation prep

def test_conversation_prep_without_ai(cycle):
    p = service().conversation_prep(cycle, EMPLOYEE, EVALUATOR, NOTES, TODAY)
    assert p.source == "SZABLON" and p.sheet == "C" and len(p.criteria) == 7
    by_id = {c.criterion_id: c for c in p.criteria}
    assert by_id["wspolpraca"].negative == 1 and by_id["wspolpraca"].questions
    assert by_id["komunikacja"].gaps == R.criteria["komunikacja"].indicators  # no observations -> ask about all
    assert "współpraca" in p.goal and p.plan_minutes[0][0].startswith("Otwarcie")
    assert {s.kind for s in p.hr_signals} >= {"PRZECIAZENIE", "ZMIANA_OBOWIAZKOW"}


def test_conversation_prep_with_ai_texts(cycle):
    model = FakeModel({"cel_rozmowy": "Omówić współpracę z [OSOBA_1] i ustalić plan poprawy.",
                       "mocne_strony": ["rzetelne tłumaczenia"], "trudne_tematy": ["brak kontaktu z wydziałami"],
                       "pytania": {"wspolpraca": ["Co utrudnia kontakt z wydziałami?"]},
                       "propozycje_rozwoju": ["mentoring"]})
    p = service(model).conversation_prep(cycle, EMPLOYEE, EVALUATOR, NOTES, TODAY)
    assert p.source == "AI" and "Grzegorz Wzór" in p.goal
    assert {c.criterion_id: c for c in p.criteria}["wspolpraca"].questions == ("Co utrudnia kontakt z wydziałami?",)


def test_conversation_prep_rejects_questions_for_unknown_criteria(cycle):
    model = FakeModel({"cel_rozmowy": "Cel rozmowy jest opisany tutaj.", "mocne_strony": [], "trudne_tematy": [],
                       "pytania": {"zarzadzanie_strategiczne": ["?"]}, "propozycje_rozwoju": []})
    assert service(model).conversation_prep(cycle, EMPLOYEE, EVALUATOR, NOTES, TODAY).source == "SZABLON"


def _start_cycle(**kw):
    svc = EvaluationService(R, InMemoryCycleRepository(), DIR, FixedClock(TODAY))
    c = svc.start_cycle(EMP, **kw)
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    return svc.cycles.get(c.id)


def test_start_conversation_prep_follows_par_5_without_ai():
    p = service().conversation_prep(_start_cycle(), EMPLOYEE, EVALUATOR, [], TODAY, kind="ROZPOCZYNAJACA")
    assert p.kind == "ROZPOCZYNAJACA" and p.source == "SZABLON"
    # § 5 ust. 1: duties from the job description, criteria and expectations, goals
    assert [name for name, _ in p.plan_minutes] == [
        "Obowiązki z opisu stanowiska", "Kryteria i oczekiwania", "Cele na okres oceny", "Pytania pracownika"]
    assert p.evaluation_deadline.strftime("%d.%m.%Y") in p.goal and "24 miesiące" not in p.goal
    for c in p.criteria:  # the period only starts: questions look ahead, not back
        assert len(c.questions) == 2
        assert not any("ostatni" in q or "Opowiedz o sytuacji" in q for q in c.questions)
    komunikacja = {c.criterion_id: c for c in p.criteria}["komunikacja"]
    assert "koncentrowanie się na wypowiedzi rozmówcy" in komunikacja.questions[0]  # its 1st behavioural indicator


def test_start_conversation_after_negative_names_the_six_month_deadline():
    c = _start_cycle(start_date=date(2026, 6, 10), after_negative=True)
    p = service().conversation_prep(c, EMPLOYEE, EVALUATOR, [], TODAY, kind="ROZPOCZYNAJACA")
    assert p.evaluation_deadline == date(2026, 12, 11) and "11.12.2026" in p.goal  # art. 81 ust. 9, not 24 months


@pytest.mark.parametrize("kind, wanted, unwanted", [
    ("ROZPOCZYNAJACA", "§ 5 ust. 1", "§ 10"),
    ("OCENIAJACA", "§ 10", "§ 5 ust. 1"),
])
def test_prep_prompt_quotes_the_paragraph_for_its_conversation(cycle, kind, wanted, unwanted):
    model = FakeModel(AiUnavailable("down"))
    service(model).conversation_prep(cycle, EMPLOYEE, EVALUATOR, NOTES, TODAY, kind=kind)
    assert wanted in model.prompts[0] and unwanted not in model.prompts[0]
    assert ("nie pytaj o przeszłe sytuacje" in model.prompts[0]) is (kind == "ROZPOCZYNAJACA")


# ---------------------------------------------------------------- 4. additional criteria

def test_suggest_criteria_rules_from_position():
    out = service().suggest_criteria(EMPLOYEE, description="Obsługa interesantów i korespondencja z klientami")
    assert out.source == "REGULY" and out.items[0].criterion_id == "orientacja_na_klienta"
    assert len(out.items) <= R.max_additional_criteria
    assert all(i.criterion_id not in R.mandatory("C") for i in out.items)


def test_suggest_criteria_ai_rejects_mandatory_and_duplicates():
    model = FakeModel({"propozycje": [
        {"kryterium": "rzetelnosc", "uzasadnienie": "obowiązkowe – nie wolno"},
        {"kryterium": "kreatywnosc", "uzasadnienie": "Stanowisko wymaga usprawniania szablonów przekładów."},
        {"kryterium": "kreatywnosc", "uzasadnienie": "duplikat duplikat"},
    ]})
    out = service(model).suggest_criteria(EMPLOYEE)
    assert out.source == "AI" and [i.criterion_id for i in out.items] == ["kreatywnosc"]


# ---------------------------------------------------------------- 5. HR partner

def test_hr_partner_rules():
    absences = [Absence(date(2026, 1, 5), date(2026, 2, 20), "L4")]
    c = scored_cycle_for_hr()
    rep = service().hr_partner(c, EMPLOYEE, NOTES, absences, TODAY)
    kinds = {s.kind for s in rep.signals}
    assert rep.source == "REGULY"
    assert {"PRZECIAZENIE", "DLUGA_NIEOBECNOSC", "ZMIANA_OBOWIAZKOW", "SPADEK_OCEN"} <= kinds
    assert all(s.recommendations for s in rep.signals)


def test_hr_partner_ai_text_and_guardrail():
    good = FakeModel({"sygnaly": [{"typ": "PRZECIAZENIE", "opis": "W ostatnich tygodniach [OSOBA_1] często pracował po godzinach.",
                                   "rekomendacje": ["porozmawiaj o obciążeniu"]}]})
    rep = service(good).hr_partner(scored_cycle_for_hr(), EMPLOYEE, NOTES, [], TODAY)
    assert rep.source == "AI"
    over = next(s for s in rep.signals if s.kind == "PRZECIAZENIE")
    assert "Grzegorz Wzór" in over.description and over.recommendations == ("porozmawiaj o obciążeniu",)

    diagnosis = FakeModel({"sygnaly": [{"typ": "PRZECIAZENIE", "opis": "Prawdopodobnie ma depresję i trzeba to leczyć.",
                                        "rekomendacje": ["skieruj do psychiatry"]}]})
    assert service(diagnosis).hr_partner(scored_cycle_for_hr(), EMPLOYEE, NOTES, [], TODAY).source == "REGULY"


def scored_cycle_for_hr():
    svc = EvaluationService(R, InMemoryCycleRepository(), DIR, FixedClock(TODAY))
    c = svc.start_cycle(EMP)
    svc.set_criteria(c.id, BOSS, ADDITIONAL)
    c = svc.cycles.get(c.id)
    return scored(c, [3, 3, 5, 1, 3, 3, 5])  # previous: pozytywna / na poziomie -> now negative


def test_ai_calls_are_logged_pseudonymised(cycle):
    model = FakeModel({"etykiety": []})
    a = service(model)
    a.classify_note(NOTES[3], "C", ADDITIONAL, people=[EMPLOYEE])
    assert a.calls[0].ok and "Grzegorz" not in a.calls[0].prompt and json.loads(a.calls[0].response) == {"etykiety": []}


def test_fill_template_drops_the_sentence_of_an_empty_optional_value():
    tpl = "Poziom: {poziom}. Najmocniejsze strony: {mocne}.\n\n{dowody}\n\nJednocześnie należy odnotować: {mocne}.\n\nKoniec."
    text = fill_template(tpl, {"poziom": "na poziomie", "mocne": "", "dowody": "– notatka (01.02.2025)"}, ("mocne",))
    assert text == "Poziom: na poziomie.\n\n– notatka (01.02.2025)\n\nKoniec."
    assert "brak" not in text
    goal = fill_template("Docenić mocne strony ({mocne}) i ustalić kierunki.", {"mocne": ""}, ("mocne",))
    assert goal == "Docenić mocne strony i ustalić kierunki."
    kept = fill_template("Docenić mocne strony ({mocne}).", {"mocne": "rzetelność"}, ("mocne",))
    assert kept == "Docenić mocne strony (rzetelność)."


def test_draft_negative_without_strengths_has_no_empty_sentence(cycle):
    d = service().draft("UZASADNIENIE", scored(cycle, [1, 1, 1, 1, 1, 1, 1]), EMPLOYEE, NOTES)
    assert "ocenę negatywną" in d.text and "należy odnotować: brak" not in d.text


def test_draft_iprz_template_groups_actions_by_weak_criterion(cycle):
    d = service().draft("IPRZ", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE, NOTES)
    weak = [line for line in d.text.splitlines() if line.startswith("– ") and ": " in line]
    assert weak and all(line.split(": ")[0][2:] in {R.criteria[c].name for c in R.criteria} for line in weak)


def test_suggest_criteria_reason_names_whole_words():
    out = service().suggest_criteria(EMPLOYEE, description="Kierownik zespołu, korespondencja z interesantami")
    reasons = " ".join(i.reason for i in out.items)
    assert "kierownik" in reasons and "kierown," not in reasons and "kierown." not in reasons
