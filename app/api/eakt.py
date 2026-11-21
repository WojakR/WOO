"""e-Akt export: status is shown to HR in GET /api/evaluations/{id} (`eksport_eakt`); failed exports retry here.

POST /api/admin/eakt/retry – HR: export again every evaluation whose last export failed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from app.domain.errors import NotAuthorized

from .access import actor as _actor
from .state import HR, DemoState, get_state

router = APIRouter(prefix="/api/admin/eakt", tags=["e-akt"])


@router.post("/retry")
def retry(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> dict:
    if _actor(st, x_user_id) != HR:
        raise NotAuthorized("Eksport do e-Akt ponawia dział kadr.")
    svc = st.eakt()
    if svc is None:
        return {"tryb": "off", "ponowiono": []}
    done = svc.retry_failed(st.evaluations.cycles.get)
    return {"ponowiono": [{"evaluation_id": int(x.cycle_id) if x.cycle_id.isdigit() else x.cycle_id,
                           "status": x.status, "proby": x.attempts, "blad": x.error} for x in done]}
