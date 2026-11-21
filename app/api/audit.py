"""Dziennik zmian: every successful change on /api/ (and every PDF download) is written to the append-only
table `dziennik_zmian` (app/infrastructure/audit_log.py) – who, what, when, and for an evaluation each changed
field with its value before and after.

Recorded generically in a middleware (no router has to remember it): the request itself (e.g. AKCJA_ZATWIERDZ_OCENE,
NOTATKA_DODANA) and a field-by-field diff of every evaluation cycle the request changed (also the ones changed
indirectly, e.g. a deadline moved by an absence). Notes are recorded as a fact only – never their text
(a private note is the evaluator's working material). Read by HR / the administrator only (AccessPolicy).
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, Header, Request

from app.domain.cycle import EvaluationCycle
from app.domain.errors import NotAuthorized, NotFound
from app.infrastructure import audit_log

from . import auth
from . import state as state_mod
from .access import actor as _actor
from .schemas import _Out
from .state import HR, DemoState, get_state

router = APIRouter(prefix="/api", tags=["dziennik"])

_CHANGES = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_FIELDS = {"history"}  # the status field already records every transition
# (method, path) -> action; named groups give the evaluation / note id
_ROUTES: list[tuple[str, re.Pattern, str]] = [(m, re.compile(p), a) for m, p, a in [
    ("POST", r"^/api/evaluations$", "OCENA_UTWORZONA"),
    ("PATCH", r"^/api/evaluations/(?P<ev>\d+)$", "EDYCJA_ARKUSZA"),
    ("PUT", r"^/api/evaluations/(?P<ev>\d+)/criteria/additional$", "KRYTERIA_DODATKOWE"),
    ("PUT", r"^/api/evaluations/(?P<ev>\d+)/scores$", "OCENY_CZASTKOWE"),
    ("POST", r"^/api/evaluations/(?P<ev>\d+)/actions/(?P<akcja>\w+)$", "AKCJA"),
    ("POST", r"^/api/evaluations/(?P<ev>\d+)/notes$", "NOTATKA_DODANA"),
    ("PATCH", r"^/api/notes/(?P<note>\d+)$", "NOTATKA_ZMIENIONA"),
    ("DELETE", r"^/api/notes/(?P<note>\d+)$", "NOTATKA_USUNIETA"),
    ("POST", r"^/api/employees/\d+/absences$", "NIEOBECNOSC_ZAREJESTROWANA"),
    ("POST", r"^/api/employees/\d+/position-changes$", "ZMIANA_STANOWISKA"),
    ("POST", r"^/api/employees/\d+/evaluator-change$", "ZMIANA_OCENIAJACEGO"),
    ("POST", r"^/api/notes/(?P<note>\d+)/przekaz$", "NOTATKA_PRZEKAZANA"),
    ("POST", r"^/api/evaluations/(?P<ev>\d+)/deadline-changes$", "ZMIANA_TERMINU"),
    ("GET", r"^/api/evaluations/(?P<ev>\d+)/pdf$", "POBRANIE_PDF"),
    ("PUT", r"^/api/ustawienia/(?P<what>\w+)$", "USTAWIENIA_ZMIENIONE"),
    ("DELETE", r"^/api/ustawienia/(?P<what>\w+)$", "USTAWIENIA_PRZYWROCONE"),
]]
_META_PATHS = ("/api/ustawienia/", "/api/me/", "/api/zastepstwa")  # changes kept in the state's meta


def _plain(x):
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: _plain(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, (list, tuple)):
        return [_plain(i) for i in x]
    if isinstance(x, (set, frozenset)):
        return sorted((_plain(i) for i in x), key=str)
    if isinstance(x, dict):
        return {str(k): _plain(val) for k, val in x.items()}
    return x


def fmt(v) -> str | None:
    """A value as text for the log (plain text stays as it is, anything else is JSON)."""
    if v is None:
        return None
    p = _plain(v)
    return p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, sort_keys=True, default=str)


def cycle_diff(old: EvaluationCycle | None, new: EvaluationCycle) -> list[tuple[str, str | None, str | None]]:
    """(field, before, after) for every field that changed; a new cycle lists its non-empty fields."""
    out = []
    for f in dataclasses.fields(EvaluationCycle):
        if f.name in _SKIP_FIELDS:
            continue
        a, b = (getattr(old, f.name) if old else None), getattr(new, f.name)
        if a != b and not (old is None and b in (None, "", [], {})):
            out.append((f.name, fmt(a), fmt(b)))
    return out


def _who(request: Request) -> str:
    """Like app.api.access.actor, but never raises: a request that succeeded was authorised already."""
    if auth.session_mode():
        return auth.session_employee_id() or "?"
    return request.headers.get("x-user-id") or HR


def _meta(st: DemoState) -> dict:
    m = state_mod.snapshot(st).meta
    m.pop("dzis", None)
    m["zastepstwa"] = list(st.deputy_records)
    return {k: fmt(v) for k, v in m.items()}


def _match(method: str, path: str):
    for m, rx, action in _ROUTES:
        if m == method:
            mt = rx.match(path)
            if mt:
                return action, mt.groupdict()
    return None


async def audit_middleware(request: Request, call_next):
    method, path = request.method, request.url.path
    route = _match(method, path)
    tracked = (path.startswith("/api/") and not path.startswith(("/api/auth/", "/api/demo/"))
               and (method in _CHANGES or route is not None))
    if not tracked:
        return await call_next(request)
    st = state_mod._state or get_state()
    before = {c.id: c for c in st.evaluations.cycles.list_all()} if method in _CHANGES else {}
    meta_before = _meta(st) if path.startswith(_META_PATHS) else None
    note_eval = None
    if route and route[1].get("note"):
        rec = st.notes.get(int(route[1]["note"]))
        note_eval = rec.evaluation_id if rec else None
    response = await call_next(request)
    if response.status_code >= 400 or state_mod._state is not st:
        return response

    who = _who(request)
    changed: list[tuple[EvaluationCycle | None, EvaluationCycle]] = []
    if method in _CHANGES:
        changed = [(before.get(c.id), c) for c in st.evaluations.cycles.list_all() if before.get(c.id) != c]
    if route:
        action, groups = route
        if action == "AKCJA":
            action = f"AKCJA_{groups['akcja']}"
        if groups.get("what"):
            action = f"{action}_{groups['what'].upper()}"
        ev = int(groups["ev"]) if groups.get("ev") else note_eval
        if ev is None and action == "OCENA_UTWORZONA":
            ev = next((int(new.id) for old, new in changed if old is None and new.id.isdigit()), None)
        entries = [{"user_id": who, "evaluation_id": ev, "action": action}]
    else:
        entries = [{"user_id": who, "evaluation_id": None, "action": f"{method} {path}"}]
    for old, new in changed:
        ev = int(new.id) if new.id.isdigit() else None
        for field, a, b in cycle_diff(old, new):
            entries.append({"user_id": who, "evaluation_id": ev, "action": "ZMIANA_POLA", "field": field,
                            "before": a, "after": b})
    if meta_before is not None:
        meta_after = _meta(st)
        for k in sorted(set(meta_before) | set(meta_after)):
            if meta_before.get(k) != meta_after.get(k):
                entries.append({"user_id": who, "evaluation_id": None, "action": "ZMIANA_USTAWIEN", "field": k,
                                "before": meta_before.get(k), "after": meta_after.get(k)})
    now = datetime.now(timezone.utc)
    audit_log.append_many([{**e, "at": now} for e in entries])
    return response


# ---------------------------------------------------------------- reading

class AuditEntryOut(_Out):
    czas: datetime  # UTC
    uzytkownik: str  # id (X-User-Id / the account's employee id)
    uzytkownik_nazwa: str
    akcja: str
    pole: str | None = None
    przed: str | None = None
    po: str | None = None


def _name(st: DemoState, user_id: str) -> str:
    if user_id == HR:
        return "Dział kadr"
    e = st.directory.get(user_id)
    return e.full_name if e else user_id


@router.get("/evaluations/{evaluation_id}/audit", response_model=list[AuditEntryOut])
def evaluation_audit(evaluation_id: int, x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)) -> list[AuditEntryOut]:
    """Historia zmian of one evaluation – HR / administrator only (AccessPolicy.can_read_audit)."""
    who = _actor(st, x_user_id)
    if st.evaluations.cycles.get(str(evaluation_id)) is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    if not st.policy().can_read_audit(who):
        raise NotAuthorized("Historię zmian widzi tylko dział kadr / administrator.")
    return [AuditEntryOut(czas=e.at, uzytkownik=e.user_id, uzytkownik_nazwa=_name(st, e.user_id), akcja=e.action,
                          pole=e.field, przed=e.before, po=e.after)
            for e in audit_log.for_evaluation(evaluation_id)]
