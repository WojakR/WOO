"""API routes (docs/api.md). Thin: look up, call the application service, map to the contract schema."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header

from app.domain.cycle import STATUS_LABELS, EvaluationCycle, Status
from app.domain.errors import FieldLocked, NotFound
from app.domain.scoring import Outcome, compute_result

from . import assistant_mapping as m
from . import schemas as s
from .access import actor as _actor
from .access import require_working_material
from .state import DemoState, get_state

router = APIRouter(prefix="/api")

# AI buttons the UI may show (contract rule 8). True = endpoint implemented; it also works with AI off (templates).
AI_FEATURES = {
    "przygotowanie_rozmowy": True,
    "podpowiedz_kryteriow": False,
    "szkic_uzasadnienia": True,
    "klasyfikacja_notatek": True,
    "hr_partner": True,  # GET /api/evaluations/{id}/hr-partner (app/api/evaluations.py)
}
_BEFORE_CRITERIA_CONFIRMED = {Status.CYCLE_STARTED, Status.CRITERIA_SET}


def _evaluation(st: DemoState, evaluation_id: int) -> EvaluationCycle:
    cycle = st.evaluations.cycles.get(str(evaluation_id))
    if cycle is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    return cycle


def _evaluator_only(st: DemoState, cycle: EvaluationCycle, user_id: str | None, what: str) -> None:
    """Evaluator's working material: the evaluator, their active deputy or HR (app/api/access.py)."""
    require_working_material(st, _actor(st, user_id), cycle, f"{what} widzi tylko oceniający (lub jego zastępca).")


# draft kind -> the arkusz field it is a draft for (all of them are part II, editable at the evaluation stage)
_DRAFT_FIELD = {"UZASADNIENIE": "justification", "IPRZ": "iprz_conclusions", "UMOTYWOWANIE_STOPNIA": "justification"}
_DRAFT_LABEL = {"UZASADNIENIE": "uzasadnienia oceny", "IPRZ": "wniosków do IPRZ",
                "UMOTYWOWANIE_STOPNIA": "umotywowania wniosku o stopień"}


@router.get("/meta", response_model=s.MetaOut, tags=["sesja"])
def meta(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> s.MetaOut:
    """Per user: the AI switch (office-wide and own) decides `tryb_ai` and which AI panels the UI shows."""
    who = _actor(st, x_user_id)
    rules = st.evaluations.rules
    ai_on = st.ai_enabled_for(who)
    lowest = float(min(rules.scale))
    bands = {m.level(b.level): (lowest if b.lower_exclusive is None else float(b.lower_exclusive),
                                float(b.upper_inclusive)) for b in rules.level_bands}
    return s.MetaOut(
        dzis=st.clock.today(),
        tryb_ai=s.TrybAI(st.ai_mode.upper()) if ai_on else s.TrybAI.OFF,
        # model_dostepny: is the model answering right now (else every feature uses its template version)
        funkcje_ai={**AI_FEATURES, "hr_partner": AI_FEATURES["hr_partner"] and st.hr_partner_enabled_for(who),
                    "model_dostepny": ai_on and st.model_available()},
        skala_punktow=sorted(rules.scale),
        progi_poziomow=bands,
        maks_kryteriow_dodatkowych=rules.max_additional_criteria,
    )


@router.post("/evaluations/{evaluation_id}/ai/conversation-prep", response_model=s.ConversationPrepOut,
             tags=["asystent"])
def conversation_prep(
    evaluation_id: int,
    rodzaj: Literal["ROZPOCZYNAJACA", "OCENIAJACA"] | None = None,
    x_user_id: str | None = Header(default=None),
    st: DemoState = Depends(get_state),
) -> s.ConversationPrepOut:
    """The evaluator's one-page note before a conversation. No scores in it; works with AI off (templates).
    Without `rodzaj`: a starting conversation until the employee confirms the criteria, an evaluating one after."""
    cycle = _evaluation(st, evaluation_id)
    _evaluator_only(st, cycle, x_user_id, "Notatkę na rozmowę")
    kind = rodzaj or ("ROZPOCZYNAJACA" if cycle.status in _BEFORE_CRITERIA_CONFIRMED else "OCENIAJACA")
    prep = st.assistant_for(_actor(st, x_user_id)).conversation_prep(
        cycle, st.directory.get(cycle.employee_id), st.directory.get(cycle.evaluator_id),
        notes=[r.note for r in st.notes_of(evaluation_id)],
        today=st.clock.today(), kind=kind, absences=cycle.absences)
    return m.to_conversation_prep_out(prep)


@router.post("/evaluations/{evaluation_id}/ai/draft", response_model=s.DraftOut, tags=["asystent"])
def draft(
    evaluation_id: int,
    body: s.DraftIn,
    x_user_id: str | None = Header(default=None),
    st: DemoState = Depends(get_state),
) -> s.DraftOut:
    """A proposal of the justification, IPRZ conclusions or grade motivation for the evaluator to edit.
    Never saved into the evaluation and never sets scores (AI only suggests). JSON only for now (no SSE)."""
    cycle = _evaluation(st, evaluation_id)
    _evaluator_only(st, cycle, x_user_id, "Szkic")
    if not cycle.is_editable(_DRAFT_FIELD[body.rodzaj]):
        raise FieldLocked(
            f"Szkic {_DRAFT_LABEL[body.rodzaj]} można przygotować dopiero po rozmowie oceniającej, "
            f"gdy wpisuje się część II arkusza (teraz: {STATUS_LABELS[cycle.status]}).")
    if body.rodzaj == "UMOTYWOWANIE_STOPNIA":  # § 11 ust. 5: Part III only with a positive evaluation
        ids = cycle.criteria_ids(st.rules_for(cycle))
        result = cycle.result or (compute_result([cycle.scores[c] for c in ids], st.rules_for(cycle))
                                  if ids and all(c in cycle.scores for c in ids) else None)
        if result is None or result.outcome is not Outcome.POSITIVE:
            raise FieldLocked("Wniosek o kolejny stopień służbowy można umotywować tylko przy ocenie pozytywnej "
                              "(§ 11 ust. 5) – najpierw wpisz wszystkie oceny cząstkowe.")
    d = st.assistant_for(_actor(st, x_user_id)).draft(body.rodzaj, cycle, st.directory.get(cycle.employee_id),
                           notes=[r.note for r in st.notes_of(evaluation_id)])
    return m.to_draft_out(d)
