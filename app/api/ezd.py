"""EZD (document management) registrations – HR only (app/application/ezd_registry.py, app/infrastructure/ezd.py).

GET  /api/admin/ezd          mode and the status of every registered document (newest first)
POST /api/admin/ezd/retry    register again every document whose last registration failed
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from app.domain.errors import NotAuthorized
from backend import config

from .access import actor as _actor
from .state import DemoState, get_state

router = APIRouter(prefix="/api/admin/ezd", tags=["ezd"])


def _hr(st: DemoState, x_user_id: str | None) -> None:
    if not st.policy().is_admin(_actor(st, x_user_id)):
        raise NotAuthorized("Rejestrację dokumentów w EZD obsługuje dział kadr.")


def _out(x) -> dict:
    return {"klucz": x.key, "rodzaj": x.kind,
            "evaluation_id": int(x.cycle_id) if x.cycle_id.isdigit() else None, "status": x.status,
            "proby": x.attempts, "ostatnia_proba": x.last_attempt.isoformat(), "miejsce": x.reference,
            "sha256": x.sha256, "blad": x.error}


@router.get("")
def ezd_status(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> dict:
    _hr(st, x_user_id)
    rows = sorted(st.ezd_status.values(), key=lambda x: x.last_attempt, reverse=True)
    return {"tryb": config.EZD_MODE if st.registry is not None else "off", "jrwa": config.EZD_JRWA or None,
            "dokumenty": [_out(x) for x in rows]}


@router.post("/retry")
def ezd_retry(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> dict:
    _hr(st, x_user_id)
    svc = st.ezd()
    if svc is None:
        return {"tryb": "off", "ponowiono": []}
    return {"ponowiono": [_out(x) for x in svc.retry_failed(st.ezd_rebuild)]}
