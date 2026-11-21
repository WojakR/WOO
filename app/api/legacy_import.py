"""Import of old evaluations (PDF or text export of the KPRM sheet) – HR only.

POST /api/legacy-import              – upload: the server reads the sheet and lists discrepancies (a draft)
GET  /api/legacy-import              – drafts and approved imports
GET  /api/legacy-import/{id}         – one draft
PUT  /api/legacy-import/{id}         – HR corrects fields; checked again (§ 11)
POST /api/legacy-import/{id}/approve – the draft becomes a finished cycle marked „zaimportowana”
GET  /api/legacy-import/{id}/file    – the original file
"""
from __future__ import annotations

import base64
import dataclasses
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from fastapi import APIRouter, Depends, File, Header, Response, UploadFile
from pydantic import BaseModel

from app.application import legacy_import as li
from app.domain.errors import InvalidTransition, NotAuthorized, NotFound, ValidationError

from . import assistant_mapping as m
from .access import actor as _actor
from .state import HR, DemoState, get_state

router = APIRouter(prefix="/api/legacy-import", tags=["import ocen"])


@dataclass
class LegacyImportRecord:
    id: int
    filename: str
    file_b64: str
    sheet: li.LegacySheet
    status: str = "ROBOCZY"  # ROBOCZY | ZATWIERDZONY
    cycle_id: str | None = None
    uploaded_on: date | None = None


class LegacyFix(BaseModel):
    """Fields HR may correct (all optional; criteria as {code: points or null})."""
    arkusz: str | None = None
    pracownik_id: int | None = None
    data_rozmowy: date | None = None
    okres_od: date | None = None
    okres_do: date | None = None
    data_sporzadzenia: date | None = None
    data_zapoznania: date | None = None
    srednia: float | None = None
    poziom: str | None = None
    wynik: str | None = None
    punkty: dict[str, int | None] | None = None
    uzasadnienie: str | None = None
    wnioski_iprz: str | None = None


class Approve(BaseModel):
    akceptuje_rozbieznosci: bool = False  # approve as in the original despite blocking discrepancies


def _admin(st: DemoState, x_user_id: str | None) -> None:
    if _actor(st, x_user_id) != HR:
        raise NotAuthorized("Stare oceny importuje dział kadr.")


def _text(data: bytes, filename: str) -> str:
    from backend.parsers import parse_file, to_llm_text

    kind, content = parse_file(data, filename)
    return content if kind == "text" else to_llm_text(kind, content, limit=200000)


def _record(st: DemoState, rid: int) -> LegacyImportRecord:
    r = st.legacy_imports.get(rid)
    if r is None:
        raise NotFound(f"Nie ma importu {rid}.")
    return r


def _out(st: DemoState, r: LegacyImportRecord) -> dict:
    rules = st.evaluations.rules
    s = r.sheet
    computed = li.result_of(s, rules)
    emp = st.directory.get(s.employee_id) if s.employee_id else None
    return {
        "id": r.id, "plik": r.filename, "status": r.status, "przeslano": r.uploaded_on.isoformat() if r.uploaded_on else None,
        "evaluation_id": int(r.cycle_id) if r.cycle_id and r.cycle_id.isdigit() else None,
        "pola": {
            "arkusz": s.sheet, "urzad": s.office, "oceniany": " ".join(s.employee_name).strip(),
            "pracownik_id": st.employee_number(emp.id) if emp else None, "pracownik": emp.full_name if emp else None,
            "oceniajacy": " ".join(s.evaluator_name).strip(),
            "data_rozmowy": s.meeting_date, "okres_od": s.period_from, "okres_do": s.period_to,
            "data_sporzadzenia": s.evaluated_on, "data_zapoznania": s.acknowledged_on,
            "srednia": float(s.declared_average) if s.declared_average is not None else None,
            "poziom": s.level, "wynik": s.outcome, "uzasadnienie": s.justification, "wnioski_iprz": s.iprz,
        },
        "kryteria": [{"kod": m.criterion_code(cid), "nazwa": rules.criterion_name(cid), "punkty": pts}
                     for cid, pts in s.scores.items()],
        "wyliczone": {"srednia": computed.average_display, "poziom": computed.level, "wynik": computed.outcome.value}
        if computed else None,
        "rozbieznosci": [{"kod": p.code, "waga": p.severity, "komunikat": p.message} for p in li.check(s, rules)],
        "uwagi": s.notes,
        "poziomy": [b.level for b in rules.level_bands],
    }


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), x_user_id: str | None = Header(default=None),
                 st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    data = await file.read()
    name = file.filename or "arkusz.pdf"
    sheet = li.parse_file(data, name, st.evaluations.rules, st.directory.all(), _text)
    rid = max(st.legacy_imports, default=0) + 1
    st.legacy_imports[rid] = LegacyImportRecord(rid, name, base64.b64encode(data).decode("ascii"), sheet,
                                                uploaded_on=st.clock.today())
    return _out(st, st.legacy_imports[rid])


@router.get("")
def list_imports(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> list[dict]:
    _admin(st, x_user_id)
    return [_out(st, r) for r in sorted(st.legacy_imports.values(), key=lambda r: -r.id)]


@router.get("/{rid}")
def get_import(rid: int, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    return _out(st, _record(st, rid))


@router.put("/{rid}")
def fix_import(rid: int, body: LegacyFix, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    r = _record(st, rid)
    if r.status != "ROBOCZY":
        raise InvalidTransition("Import został już zatwierdzony.")
    s = r.sheet
    got = body.model_dump(exclude_unset=True)
    changes: dict = {}
    if "pracownik_id" in got:
        emp = st.employee_by_number(got["pracownik_id"] or 0)
        if emp is None:
            raise ValidationError([f"Nie ma pracownika {got['pracownik_id']}."])
        changes["employee_id"] = emp.id
    simple = {"arkusz": "sheet", "data_rozmowy": "meeting_date", "okres_od": "period_from", "okres_do": "period_to",
              "data_sporzadzenia": "evaluated_on", "data_zapoznania": "acknowledged_on", "poziom": "level",
              "wynik": "outcome", "uzasadnienie": "justification", "wnioski_iprz": "iprz"}
    for api_name, field in simple.items():
        if api_name in got:
            changes[field] = got[api_name]
    if "srednia" in got:
        changes["declared_average"] = None if got["srednia"] is None else Fraction(str(got["srednia"]))
    if got.get("punkty") is not None:
        scores = dict(s.scores)
        for code, pts in got["punkty"].items():
            cid = m.criterion_id(code)
            if cid not in st.evaluations.rules.criteria:
                raise ValidationError([f"Nieznane kryterium: {code}."])
            if pts is not None and pts not in st.evaluations.rules.scale:
                raise ValidationError([f"Niedozwolona ocena cząstkowa {pts}."])
            scores[cid] = pts
        changes["scores"] = scores
    if changes.get("level") and changes["level"] not in st.evaluations.rules.scale.values():
        raise ValidationError([f"Nieznany poziom „{changes['level']}”."])
    if changes.get("outcome") and changes["outcome"] not in ("pozytywna", "negatywna"):
        raise ValidationError(["Wynik: pozytywna albo negatywna."])
    r.sheet = dataclasses.replace(s, **changes)
    return _out(st, r)


@router.post("/{rid}/approve")
def approve(rid: int, body: Approve, x_user_id: str | None = Header(default=None),
            st: DemoState = Depends(get_state)) -> dict:
    _admin(st, x_user_id)
    r = _record(st, rid)
    if r.status != "ROBOCZY":
        raise InvalidTransition("Import został już zatwierdzony.")
    rules = st.evaluations.rules
    problems = li.check(r.sheet, rules)
    must = [p for p in li.blocking(problems) if p.code.startswith("BRAK_")]  # cannot build a cycle without these
    wrong = [p for p in li.blocking(problems) if not p.code.startswith("BRAK_")]
    if must or (wrong and not body.akceptuje_rozbieznosci):
        raise ValidationError([p.message for p in must + wrong]
                              + ([] if must else ["Popraw pola albo zatwierdź z akceptacją rozbieżności."]))
    emp = st.directory.get(r.sheet.employee_id)
    evaluator = r.sheet.evaluator_id or emp.evaluator_id or HR
    cid = st.evaluations._new_id()
    c = li.to_cycle(r.sheet, cid, evaluator, st.clock.today(), rules)
    st.evaluations.cycles.save(c)
    st.touch(c.id)
    r.status, r.cycle_id = "ZATWIERDZONY", c.id
    return _out(st, r)


@router.get("/{rid}/file", response_class=Response)
def original(rid: int, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    _admin(st, x_user_id)
    r = _record(st, rid)
    from urllib.parse import quote

    media = "application/pdf" if r.filename.lower().endswith(".pdf") else "text/plain; charset=utf-8"
    ascii_name = r.filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return Response(base64.b64decode(r.file_b64), media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(r.filename)}"})
