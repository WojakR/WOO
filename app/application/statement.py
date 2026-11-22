"""Statement of evaluations for the reporting system and for inspections (KPRM use-case diagram: "generowanie
statystyk", actor "system sprawozdawczy").

One row per evaluation cycle in scope (reports.Scope: who the user may see, year of the deadline, unit), with
every date and outcome a report or an inspection asks about: deadlines and whether they were kept, acknowledgement
(also by refusal to sign), result, objection and its outcome, request for the next grade.

Personal data only on request: by default the person is a stable pseudonym (the same person = the same code in
every export, so a reporting system can count people and follow them between periods, but cannot name them).
Deadlines come from the timeline the evaluation shows (app/domain/timeline.py), never computed again here.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, fields
from datetime import date
from typing import Callable

from app.domain.cycle import STATUS_LABELS, EvaluationCycle
from app.domain.employee import Employee
from app.domain.scoring import Outcome
from app.domain.timeline import deadlines_of

from .reports import Scope

FORMAT_VERSION = "1.0"


@dataclass(frozen=True)
class StatementRow:
    id_oceny: str
    pracownik: str  # pseudonym, or the id when personal data was asked for
    imie_nazwisko: str  # empty without personal data
    urzad: str
    komorka: str
    stanowisko: str
    korpus: str  # URZEDNIK (mianowany) | PRACOWNIK
    arkusz: str
    status: str
    status_opis: str
    rozpoczecie_cyklu: date
    po_ocenie_negatywnej: bool
    termin_wyznaczenia_kryteriow: date
    data_wyznaczenia_kryteriow: date | None
    kryteria_w_terminie: bool | None
    termin_oceny: date | None
    data_sporzadzenia: date | None
    ocena_w_terminie: bool | None
    data_zapoznania: date | None
    fikcja_zapoznania: bool
    srednia: float | None
    poziom: str | None
    wynik: str | None  # POZYTYWNA | NEGATYWNA
    sprzeciw: str  # BRAK | ZLOZONY | UWZGLEDNIONY | NIEUWZGLEDNIONY
    rozstrzygniecie_sprzeciwu: str | None  # ZMIANA_OCENY | PONOWNE_SPORZADZENIE (upheld)
    data_rozstrzygniecia_sprzeciwu: date | None
    wniosek_o_stopien: bool
    zaimportowana: bool  # an old evaluation imported from a PDF


def _kept(done: date | None, due: date | None) -> bool | None:
    return None if done is None or due is None else done <= due


def _row(c: EvaluationCycle, e: Employee | None, scope: Scope, person: str, with_names: bool) -> StatementRow:
    rules = scope.rules_for(c)
    items = {i.kind: i for i in deadlines_of(c, rules, scope.calendar, scope.today)}
    crit, ev = items.get("KRYTERIA"), items.get("OCENA")
    r = c.result
    objection = c.objection_decision or ("ZLOZONY" if c.objection_filed_on else "BRAK")
    return StatementRow(
        id_oceny=c.id, pracownik=person, imie_nazwisko=e.full_name if (e and with_names) else "",
        urzad=e.office if e else "", komorka=e.unit if e else "", stanowisko=e.position if e else "",
        korpus="URZEDNIK" if e and e.civil_servant else "PRACOWNIK", arkusz=c.sheet, status=c.status.name,
        status_opis=STATUS_LABELS[c.status], rozpoczecie_cyklu=c.start_date, po_ocenie_negatywnej=c.after_negative,
        termin_wyznaczenia_kryteriow=c.criteria_deadline, data_wyznaczenia_kryteriow=c.criteria_set_on,
        kryteria_w_terminie=_kept(c.criteria_set_on, crit.due if crit else c.criteria_deadline),
        termin_oceny=ev.due if ev else None, data_sporzadzenia=c.evaluated_on,
        ocena_w_terminie=_kept(c.evaluated_on, ev.due if ev else None), data_zapoznania=c.acknowledged_on,
        fikcja_zapoznania=c.acknowledgement_refused, srednia=r.average_display if r else None,
        poziom=r.level if r else None,
        wynik=None if r is None else ("POZYTYWNA" if r.outcome is Outcome.POSITIVE else "NEGATYWNA"),
        sprzeciw=objection, rozstrzygniecie_sprzeciwu=c.objection_outcome,
        data_rozstrzygniecia_sprzeciwu=c.objection_decided_on, wniosek_o_stopien=c.promotion_request,
        zaimportowana=c.imported)


def statement(scope: Scope, pseudonym: Callable[[str], str], with_names: bool = False,
              drawn_up_from: date | None = None, drawn_up_to: date | None = None) -> list[StatementRow]:
    """Rows of the statement. `drawn_up_from/to` keep only evaluations drawn up in that period (inclusive)."""
    people = {e.id: e for e in scope.people()}
    out = []
    imported = [c for c in scope.cycles if c.imported and c.employee_id in people]
    for c in [*scope.in_scope(), *imported]:
        if drawn_up_from and (c.evaluated_on is None or c.evaluated_on < drawn_up_from):
            continue
        if drawn_up_to and (c.evaluated_on is None or c.evaluated_on > drawn_up_to):
            continue
        person = c.employee_id if with_names else pseudonym(c.employee_id)
        out.append(_row(c, people.get(c.employee_id), scope, person, with_names))
    return sorted(out, key=lambda r: (r.komorka, r.pracownik, r.rozpoczecie_cyklu, r.id_oceny))


COLUMNS = [f.name for f in fields(StatementRow)]


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TAK" if v else "NIE"
    if isinstance(v, float):
        return f"{v:.2f}".replace(".", ",")  # Polish Excel
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def to_csv(rows: list[StatementRow]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([_cell(getattr(r, c)) for c in COLUMNS])
    return buf.getvalue()


def to_json(rows: list[StatementRow], meta: dict) -> str:
    """Machine-readable package: version of the format, what the statement covers, the rows."""
    def conv(v):
        return v.isoformat() if isinstance(v, date) else v

    return json.dumps({"wersja_formatu": FORMAT_VERSION, **meta, "liczba_ocen": len(rows),
                       "kolumny": COLUMNS, "oceny": [{k: conv(v) for k, v in asdict(r).items()} for r in rows]},
                      ensure_ascii=False, indent=2)
