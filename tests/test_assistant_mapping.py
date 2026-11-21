"""Assistant results map onto the API schemas (no AI: fallback results)."""
from datetime import date

from app.api import assistant_mapping as m
from app.api import schemas as s
from app.domain.cycle import PreviousEvaluation
from app.domain.notes import Note, Sentiment
from tests.test_assistant import ADDITIONAL, EMPLOYEE, EVALUATOR, NOTES, TODAY, cycle, scored, service  # noqa: F401


def test_levels_and_previous_evaluation():
    assert m.level("Powyżej oczekiwań") is s.Poziom.POWYZEJ
    assert m.level("nieznany") is None
    p = m.previous(PreviousEvaluation("pozytywna", "na poziomie oczekiwań", date(2024, 6, 12)))
    assert p.wynik is s.Wynik.POZYTYWNA and p.poziom is s.Poziom.NA_POZIOMIE and p.zrodlo == "SYSTEM"
    assert m.previous(PreviousEvaluation(None, None, None)).wynik == "BRAK"


def test_classification_maps_fallback_without_sentiment():
    status, source, sugg = m.to_classification(service().classify_note(NOTES[0], "C", ADDITIONAL))
    assert status == "DO_PRZYPISANIA" and source == "REGULY" and sugg
    assert all(x.criterion_kod.isupper() and x.wydzwiek is None for x in sugg)
    s.NoteOut(id=1, evaluation_id=1, autor=s.OsobaRef(id=1, imie="H", nazwisko="P"), data=TODAY,
              typ=s.TypNotatki.OBSERWACJA, tresc="x", widoczna_dla_ocenianego=False,
              status_klasyfikacji=status, zrodlo_sugestii=source, sugestie_ai=sugg)


def test_draft_keeps_only_numeric_note_ids(cycle):  # noqa: F811
    d = service().draft("UZASADNIENIE", scored(cycle, [3, 3, 5, 1, 3, 3, 5]), EMPLOYEE,
                        [*NOTES, Note("42", date(2026, 5, 1), "Odrzucił wniosek bez kontaktu z wydziałem.",
                                      criterion_id="wspolpraca", sentiment=Sentiment.NEGATIVE)])
    out = m.to_draft_out(d)
    assert out.zrodlo == "SZABLON" and 42 in out.oparte_na_notatkach
    assert all(isinstance(i, int) for i in out.oparte_na_notatkach)


def test_conversation_prep_and_hr_partner_validate_against_schemas(cycle):  # noqa: F811
    prep = m.to_conversation_prep_out(service().conversation_prep(cycle, EMPLOYEE, EVALUATOR, NOTES, TODAY))
    assert prep.zrodlo_tekstow == "SZABLON" and len(prep.kryteria) == 7
    assert prep.kryteria[0].criterion_kod == "WYKORZYSTYWANIE_WIEDZY" and prep.poprzednia_ocena.wynik is s.Wynik.POZYTYWNA
    assert {x.typ for x in prep.sygnaly_hr} >= {"PRZECIAZENIE"}
    hr = m.to_hr_partner_out(service().hr_partner(cycle, EMPLOYEE, NOTES, [], TODAY))
    assert hr.zrodlo_tekstow == "REGULY" and [x.id for x in hr.sygnaly] == list(range(1, len(hr.sygnaly) + 1))
    s.ConversationPrepOut.model_validate(prep.model_dump())


def test_suggest_criteria_codes_roundtrip():
    out = m.to_suggest_criteria_out(service().suggest_criteria(EMPLOYEE, description="obsługa interesantów"))
    assert out.zrodlo == "REGULY" and out.sugestie[0].kod == "ORIENTACJA_NA_KLIENTA"
    assert m.criterion_id(out.sugestie[0].kod) == "orientacja_na_klienta"
