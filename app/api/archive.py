"""Archive of closed evaluations and retention review – HR / administrator only (app/application/archive.py).

POST /api/archive/run                    – freeze every closed evaluation not archived yet
GET  /api/archive                        – archived records with their checksums (and whether they still match)
GET  /api/archive/{id}/pdf               – the archived PDF
GET  /api/archive/review                 – records past their retention, for a decision (nothing is deleted)
POST /api/archive/{id}/delete            – delete one record past retention: {"zatwierdzam": true}
POST /api/archive/notes/{cycle}/delete   – delete the working notes of a closed evaluation past their period
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from app.application.archive import ArchiveService, is_closed
from app.domain.errors import InvalidTransition, NotAuthorized, NotFound, ValidationError

from .access import actor as _actor
from .state import HR, DemoState, _codec, get_state

router = APIRouter(prefix="/api/archive", tags=["archiwum"])


class Approval(BaseModel):
    zatwierdzam: bool = False


def _admin(st: DemoState, x_user_id: str | None) -> str:
    who = _actor(st, x_user_id)
    if who != HR:
        raise NotAuthorized("Archiwum ocen obsługuje dział kadr (administrator).")
    return who


def service(st: DemoState) -> ArchiveService:
    from .evaluations import sheet_pdf_bytes

    codec = _codec()
    return ArchiveService(st.archive_store(), codec.dumps, lambda c: sheet_pdf_bytes(st, c), st.settings.archive)


def run(st: DemoState) -> list:
    svc, ev = service(st), st.evaluations
    today = st.clock.today()
    return svc.freeze_closed(
        ev.cycles.list_all(),
        lambda c: is_closed(c, ev.rules_for(c), ev.calendar, today, ev.employee_absences(c.employee_id)), today)


def _name(st: DemoState, employee_id: str) -> str:
    e = st.directory.get(employee_id)
    return e.full_name if e else employee_id


def _out(r, st: DemoState) -> dict:
    return {"id": r.id, "evaluation_id": int(r.cycle_id) if r.cycle_id.isdigit() else r.cycle_id,
            "pracownik_id": r.employee_id, "pracownik": _name(st, r.employee_id), "zamrozono": r.frozen_on.isoformat(), "sha256_pdf": r.pdf_sha256,
            "sha256_dane": r.snapshot_sha256, "zgodny": r.intact(), "rozmiar_pdf": len(r.pdf)}


def _review(st: DemoState):
    cycles = {c.id: c for c in st.evaluations.cycles.list_all()}
    employees = {e.id: e for e in st.directory.all()}
    return service(st).review(employees, cycles, lambda cid: len(st.notes_of(int(cid))) if cid.isdigit() else 0,
                              st.clock.today())


@router.post("/run")
def archive_run(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    return {"zamrozono": [_out(r, st) for r in run(st)]}


@router.get("")
def archive_list(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> list[dict]:
    _admin(st, x_user_id)
    return [_out(r, st) for r in st.archive_store().all()]


@router.get("/review")
def archive_review(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> list[dict]:
    _admin(st, x_user_id)
    return [{"rodzaj": i.kind, "id": i.record_id, "evaluation_id": int(i.cycle_id) if i.cycle_id.isdigit() else None,
             "pracownik_id": i.employee_id, "pracownik": _name(st, i.employee_id), "termin_przechowywania": i.due.isoformat(), "powod": i.reason}
            for i in _review(st)]


@router.get("/{record_id}/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
def archive_pdf(record_id: int, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    _admin(st, x_user_id)
    r = st.archive_store().by_id(record_id)
    if r is None:
        raise NotFound(f"Nie ma rekordu archiwum {record_id}.")
    return Response(r.pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="archiwum-ocena-{r.cycle_id}.pdf"', "X-SHA256": r.pdf_sha256})


@router.post("/{record_id}/delete")
def archive_delete(record_id: int, body: Approval, x_user_id: str | None = Header(default=None),
                   st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    r = service(st).delete(record_id, body.zatwierdzam, _review(st))
    return {"usunieto": _out(r, st)}


@router.post("/notes/{evaluation_id}/delete")
def archive_delete_notes(evaluation_id: int, body: Approval, x_user_id: str | None = Header(default=None),
                         st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    if not any(i.kind == "NOTATKI" and i.cycle_id == str(evaluation_id) for i in _review(st)):
        raise InvalidTransition("Okres przechowywania notatek roboczych tej oceny jeszcze nie minął.")
    if not body.zatwierdzam:
        raise ValidationError(["Usunięcie notatek roboczych wymaga zatwierdzenia przez administratora."])
    ids = [nid for nid, r in st.notes.items() if r.evaluation_id == evaluation_id]
    for nid in ids:
        del st.notes[nid]
    return {"usunieto_notatek": len(ids)}
