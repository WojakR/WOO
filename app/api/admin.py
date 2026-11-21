"""Administrator: import of employees from the HR system (CSV / XLSX) – preview first, then save.

POST /api/admin/employees/import?podglad=true   -> report only, nothing saved
POST /api/admin/employees/import                -> saved when the file has no errors
`uruchom_cykle=true` also opens an evaluation cycle for everyone with an evaluator who has none (production start).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Header, UploadFile
from pydantic import BaseModel

from app.domain.errors import NotAuthorized
from app.infrastructure.hr_import import build_report, read_rows

from .access import actor as _actor
from .errors import ApiProblem
from .state import DemoState, get_state

router = APIRouter(prefix="/api/admin", tags=["administracja"])
MAX_FILE_BYTES = 5 * 1024 * 1024


class ImportProblem(BaseModel):
    wiersz: int
    id: str | None = None
    komunikat: str


class ImportOut(BaseModel):
    podglad: bool
    zapisano: bool
    liczba_wierszy: int
    dodani: list[str] = []
    zaktualizowani: list[str] = []
    problemy: list[ImportProblem] = []
    uruchomione_cykle: list[str] = []


def require_admin(st: DemoState, who: str) -> None:
    if not st.policy().is_admin(who):
        raise NotAuthorized("Import danych kadrowych wykonuje administrator / dział kadr.")


@router.post("/employees/import", response_model=ImportOut)
async def import_employees(file: UploadFile = File(...), podglad: bool = False, uruchom_cykle: bool = False,
                           x_user_id: str | None = Header(default=None),
                           st: DemoState = Depends(get_state)) -> ImportOut:
    require_admin(st, _actor(st, x_user_id))
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise ApiProblem(413, "PLIK_ZA_DUZY", "Plik jest za duży (najwyżej 5 MB).")
    try:
        rows = read_rows(data, file.filename or "plik.csv")
    except ValueError as e:
        raise ApiProblem(422, "BLEDNY_PLIK", str(e))
    current = {e.id: e for e in st.directory.all()}
    rep = build_report(rows, current)
    out = ImportOut(podglad=podglad, zapisano=False, liczba_wierszy=len(rows), dodani=rep.added,
                    zaktualizowani=rep.updated,
                    problemy=[ImportProblem(wiersz=p.row, id=p.employee_id, komunikat=p.message) for p in rep.problems])
    if podglad or not rep.ok:
        return out
    st.import_employees(rep.employees)
    out.zapisano = True
    if uruchom_cykle:
        for e in rep.employees:
            if e.evaluator_id and st.evaluations.cycles.find_open_for(e.id) is None and not e.employment_end:
                prev = e.previous_evaluation
                start: date | None = prev.date if prev and prev.date else e.employment_start
                st.evaluations.start_cycle(e.id, start_date=start)
                out.uruchomione_cykle.append(e.id)
    return out
