"""API routes (docs/api.md). Thin: look up, call the application service, map to the contract schema."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header

from app.domain.cycle import EvaluationCycle, Status
from app.domain.errors import NotAuthorized, NotFound

from . import assistant_mapping as m
from . import schemas as s
from .state import DemoState, get_state

router = APIRouter(prefix="/api")

# AI buttons the UI may show (contract rule 8). True = endpoint implemented; it also works with AI off (templates).
AI_FEATURES = {
    "przygotowanie_rozmowy": True,
    "podpowiedz_kryteriow": False,
    "szkic_uzasadnienia": False,
    "klasyfikacja_notatek": False,
    "hr_partner": False,
}
_BEFORE_CRITERIA_CONFIRMED = {Status.CYCLE_STARTED, Status.CRITERIA_SET}


def _evaluation(st: DemoState, evaluation_id: int) -> EvaluationCycle:
    cycle = st.evaluations.cycles.get(str(evaluation_id))
    if cycle is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    return cycle


@router.get("/meta", response_model=s.MetaOut, tags=["sesja"])
def meta(st: DemoState = Depends(get_state)) -> s.MetaOut:
    rules = st.evaluations.rules
    lowest = float(min(rules.scale))
    bands = {m.level(b.level): (lowest if b.lower_exclusive is None else float(b.lower_exclusive),
                                float(b.upper_inclusive)) for b in rules.level_bands}
    return s.MetaOut(
        dzis=st.clock.today(),
        tryb_ai=s.TrybAI(st.ai_mode.upper()),
        funkcje_ai=dict(AI_FEATURES),
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
    if x_user_id is not None and x_user_id != cycle.evaluator_id:
        raise NotAuthorized("Notatkę na rozmowę widzi tylko oceniający.")
    kind = rodzaj or ("ROZPOCZYNAJACA" if cycle.status in _BEFORE_CRITERIA_CONFIRMED else "OCENIAJACA")
    prep = st.assistant.conversation_prep(
        cycle, st.directory.get(cycle.employee_id), st.directory.get(cycle.evaluator_id),
        notes=[],  # no notes store yet (🟢 POST /api/evaluations/{id}/notes comes later)
        today=st.clock.today(), kind=kind, absences=cycle.absences)
    return m.to_conversation_prep_out(prep)
