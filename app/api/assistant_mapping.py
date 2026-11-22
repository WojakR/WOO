"""Maps AiSuggestionService results (application layer) onto the API schemas (front <-> back contract).

Routers call the service and return `to_*(result)`. Conventions:
- criterion codes go out upper-case (`rzetelnosc` -> `RZETELNOSC`), as in the data model,
- note ids go out as int when numeric (DB ids), otherwise unchanged (in-memory demo ids),
- levels / outcomes are translated from the Polish words in reguly.json to the API enums.
"""
from __future__ import annotations

from app.application.assistant import (
    ConversationPrep,
    CriteriaSuggestions,
    Draft,
    HrReport,
    HrSignal,
    NoteClassification,
)
from app.domain.cycle import PreviousEvaluation
from app.domain.notes import Note

from . import schemas as s

_LEVELS = {
    "znacznie poniżej oczekiwań": s.Poziom.ZNACZNIE_PONIZEJ,
    "poniżej oczekiwań": s.Poziom.PONIZEJ,
    "na poziomie oczekiwań": s.Poziom.NA_POZIOMIE,
    "powyżej oczekiwań": s.Poziom.POWYZEJ,
    "znacznie powyżej oczekiwań": s.Poziom.ZNACZNIE_POWYZEJ,
}
_OUTCOMES = {"pozytywna": s.Wynik.POZYTYWNA, "negatywna": s.Wynik.NEGATYWNA}


def criterion_code(criterion_id: str) -> str:
    return criterion_id.upper()


def criterion_id(code: str) -> str:
    """Inverse of criterion_code, for incoming requests."""
    return code.lower()


def _note_id(note_id: str) -> int | str:
    return int(note_id) if str(note_id).isdigit() else note_id


def level(text: str | None) -> s.Poziom | None:
    return _LEVELS.get((text or "").strip().casefold())


def previous(p: PreviousEvaluation | None) -> s.PoprzedniaOcena | None:
    if p is None:
        return None
    return s.PoprzedniaOcena(zrodlo="SYSTEM", wynik=_OUTCOMES.get((p.outcome or "").casefold(), "BRAK"),
                             poziom=level(p.level), data=p.date)


def to_classification(c: NoteClassification) -> tuple[str, str, list[s.SugestiaKlasyfikacji]]:
    """-> (status_klasyfikacji, zrodlo_sugestii, sugestie_ai) to set on NoteOut."""
    return c.status, ("AI" if c.source == "AI" else "REGULY"), [
        s.SugestiaKlasyfikacji(
            criterion_kod=criterion_code(x.criterion_id), nazwa=x.criterion_name, wskaznik=x.indicator,
            wydzwiek=s.Wydzwiek(x.sentiment.value) if x.sentiment else None,
            pewnosc=x.confidence, fragment=x.quote)
        for x in c.suggestions]


def to_draft_out(d: Draft, stale: bool = False) -> s.DraftOut:
    ids = [_note_id(i) for i in d.note_ids]
    return s.DraftOut(rodzaj=d.kind, tekst=d.text, zrodlo="AI" if d.source == "AI" else "SZABLON",
                      oparte_na_notatkach=[i for i in ids if isinstance(i, int)], nieaktualny=stale)


def to_suggest_criteria_out(c: CriteriaSuggestions) -> s.SuggestCriteriaOut:
    return s.SuggestCriteriaOut(
        sugestie=[s.KryteriumSugestia(kod=criterion_code(i.criterion_id), nazwa=i.name, uzasadnienie=i.reason)
                  for i in c.items],
        zrodlo="AI" if c.source == "AI" else "REGULY")


def to_hr_signal(sig: HrSignal, index: int) -> s.HrSignal:
    return s.HrSignal(id=index, typ=sig.kind, opis=sig.description, dowody=list(sig.evidence),
                      rekomendacje=list(sig.recommendations), dzialania_rozwojowe=list(sig.development))


def to_hr_partner_out(r: HrReport) -> s.HrPartnerOut:
    return s.HrPartnerOut(sygnaly=[to_hr_signal(x, i) for i, x in enumerate(r.signals, 1)],
                          zrodlo_tekstow="AI" if r.source == "AI" else "REGULY")


def _example(n: Note) -> s.PrzykladNotatki:
    return s.PrzykladNotatki(id=_note_id(n.id), data=n.on, tresc=n.text,
                             wydzwiek=s.Wydzwiek(n.sentiment.value) if n.sentiment else None)


def to_conversation_prep_out(p: ConversationPrep) -> s.ConversationPrepOut:
    return s.ConversationPrepOut(
        rodzaj=p.kind,
        cel_rozmowy=p.goal,
        termin_oceny=p.evaluation_deadline,
        dni_do_terminu=p.days_to_deadline,
        poprzednia_ocena=previous(p.previous_evaluation),
        cele=list(p.goals),
        kryteria=[s.PrepKryterium(
            criterion_kod=criterion_code(c.criterion_id), nazwa=c.name, obowiazkowe=c.mandatory,
            plus=c.positive, minus=c.negative, przyklady=[_example(n) for n in c.examples],
            luki=list(c.gaps), pytania=list(c.questions)) for c in p.criteria],
        mocne_strony=list(p.strengths),
        trudne_tematy=list(p.difficult_topics),
        sygnaly_hr=[to_hr_signal(x, i) for i, x in enumerate(p.hr_signals, 1)],
        propozycje_rozwoju=list(p.development),
        plan_minuty=[(name, minutes) for name, minutes in p.plan_minutes],
        zrodlo_tekstow="AI" if p.source == "AI" else "SZABLON",
    )
