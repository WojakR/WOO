"""Import of working-time records (RCP) – HR / administrator only.

POST /api/admin/rcp/import (multipart file: CSV or XLSX) -> how many days were imported, row errors.
GET  /api/admin/rcp/summary -> per person: days in the window and the aggregated indicators (no raw hours).
The indicators reach the HR partner as aggregates (app/domain/worktime_signals.py).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Header, UploadFile

from app.domain.errors import NotAuthorized
from app.domain.worktime_signals import indicators, overload_evidence
from app.infrastructure.rcp_import import import_file

from .access import actor as _actor
from .state import HR, DemoState, get_state

router = APIRouter(prefix="/api/admin/rcp", tags=["rcp"])


def _require_hr(who: str) -> None:
    if who != HR:
        raise NotAuthorized("Dane z rejestracji czasu pracy importuje dział kadr (administrator).")


def _resolver(st: DemoState):
    def resolve(raw: str) -> str | None:
        if st.directory.get(raw):
            return raw
        if raw.isdigit() and (e := st.employee_by_number(int(raw))):
            return e.id
        return None
    return resolve


@router.post("/import")
async def import_rcp(file: UploadFile = File(...), x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)) -> dict:
    _require_hr(_actor(st, x_user_id))
    result = import_file(await file.read(), file.filename or "rcp.csv", _resolver(st))
    st.worktime.add(result.days)
    st.hr_reports.clear()
    return {"zaimportowano": len(result.days), "pracownicy": len({d.employee_id for d in result.days}),
            "bledy": [{"wiersz": e.line, "komunikat": e.message} for e in result.errors]}


@router.get("/summary")
def summary(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> list[dict]:
    _require_hr(_actor(st, x_user_id))
    today = st.clock.today()
    out = []
    for e in st.directory.all():
        ind = indicators(st.worktime.days_for(e.id, today - timedelta(days=366), today), today, st.settings.rcp)
        if ind.days:
            out.append({"pracownik": e.full_name, "dni": ind.days, "dni_nadgodziny": ind.overtime_days,
                        "dni_krotka_przerwa": ind.short_break_days, "srednia_przerwa_min": ind.average_break,
                        "dni_po_godzinach": ind.after_hours_days,
                        "sygnal": bool(overload_evidence(ind, st.settings.rcp))})
    return out
