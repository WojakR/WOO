"""Burnout checklist at the review meeting (spec, point 3) – the evaluator's working material.

GET  /api/wellbeing/checklist            – the 8 areas and the instruction (data/kprm/wellbeing.json)
GET  /api/evaluations/{id}/wellbeing     – answers: evaluator, deputy, HR (never the evaluated person)
PUT  /api/evaluations/{id}/wellbeing     – save answers: evaluator or deputy
Never printed on the sheet (backend/sheet_pdf.py does not get it); feeds the HR partner's overload signal.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.domain.wellbeing import WellbeingCheck, parse_answers
from backend import kprm

from .access import actor as _actor
from .access import require_evaluator, require_working_material
from .evaluations import _cycle
from .state import DemoState, get_state

router = APIRouter(prefix="/api", tags=["dobrostan"])


class WellbeingIn(BaseModel):
    odpowiedzi: dict[str, dict]  # {"zmeczenie": {"odpowiedz": "CZESTO", "komentarz": "..."}}


def _out(st: DemoState, cycle_id: str) -> dict:
    check = st.wellbeing.get(cycle_id)
    answers = check.answers if check else {}
    often = check.often() if check else []
    threshold = st.settings.wellbeing_often_threshold
    return {
        "odpowiedzi": {sid: {"odpowiedz": a.answer.value, "komentarz": a.comment} for sid, a in answers.items()},
        "zaktualizowano": check.updated_on.isoformat() if check and check.updated_on else None,
        "liczba_czesto": len(often), "prog_sygnalu": threshold, "sygnal_przeciazenia": len(often) >= threshold,
    }


@router.get("/wellbeing/checklist")
def checklist() -> dict:
    data = kprm.wellbeing()
    return {"instrukcja": data["instrukcja"], "odpowiedzi": data["odpowiedzi"], "objawy": data["objawy"]}


@router.get("/evaluations/{evaluation_id}/wellbeing")
def get_wellbeing(evaluation_id: int, x_user_id: str | None = Header(default=None),
                  st: DemoState = Depends(get_state)) -> dict:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, who)
    require_working_material(st, who, c, "Listę kontrolną dobrostanu widzi tylko oceniający, jego zastępca i HR.")
    return _out(st, c.id)


@router.put("/evaluations/{evaluation_id}/wellbeing")
def put_wellbeing(evaluation_id: int, body: WellbeingIn, x_user_id: str | None = Header(default=None),
                  st: DemoState = Depends(get_state)) -> dict:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id, who)
    require_evaluator(st, who, c, "Listę kontrolną dobrostanu wypełnia oceniający (lub jego zastępca).")
    ids = [x["id"] for x in kprm.wellbeing()["objawy"]]
    answers = parse_answers(body.odpowiedzi, ids)
    st.wellbeing[c.id] = WellbeingCheck(c.id, answers, st.clock.today(), who)
    st.hr_reports.pop(c.id, None)
    return _out(st, c.id)
