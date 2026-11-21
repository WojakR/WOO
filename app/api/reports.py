"""Reports (spec, point 4): progress of the evaluations, outcomes with charts, training needs.

Scope from the access policy: HR / administrator / objection reviewers – the whole office; a manager – the people
whose evaluations they may read (subtree or direct reports, office setting); anyone else – nothing (403).
The logic lives in app/application/reports.py and training_needs.py; this module only shapes JSON.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, Response

from app.application import training_needs as tn
from app.application.reports import Scope, outcomes, progress
from app.domain.cycle import Status
from app.domain.errors import NotAuthorized
from backend import kprm

from .access import actor as _actor
from .evaluations import STATUS_MAP
from .state import DemoState, get_state

router = APIRouter(prefix="/api/reports", tags=["raporty"])


def _scope(st: DemoState, who: str, rok: int | None, komorka: str | None) -> Scope:
    policy = st.policy()
    visible = policy.visible_employees(who)
    if not visible:
        raise NotAuthorized("Raporty są dostępne dla kadr i przełożonych (zakres: osoby, których oceny widzisz).")
    people = [e for e in st.directory.all() if e.id in visible]
    return Scope(people, st.evaluations.cycles.list_all(), st.rules_for, st.evaluations.calendar,
                 st.clock.today(), rok, komorka or None)


def _scope_label(st: DemoState, who: str, komorka: str | None) -> str:
    if komorka:
        return f"komórki „{komorka}”"
    return "całego urzędu" if st.policy().is_admin(who) else "zespołu przełożonego"


@router.get("/progress")
def report_progress(rok: int | None = None, komorka: str | None = None, x_user_id: str | None = Header(default=None),
                    st: DemoState = Depends(get_state)) -> dict:
    """How many people are evaluated, statuses, overdue, on time (%), average stage time, per unit."""
    who = _actor(st, x_user_id)
    scope = _scope(st, who, rok, komorka)
    p = progress(scope)
    status_name = {k.value: STATUS_MAP[k].value for k in Status}
    return {
        "zakres": _scope_label(st, who, komorka), "rok": rok, "komorka": komorka,
        "objeci_ocena": p.people, "cykle": p.cycles, "sporzadzone": p.drawn_up, "w_toku": p.in_progress,
        "oczekuje_na_ocenianego": p.waiting_for_employee, "po_terminie": p.overdue, "w_terminie": p.on_time,
        "w_terminie_proc": p.on_time_percent, "bez_cyklu": p.not_started,
        "statusy": {status_name[k]: v for k, v in sorted(p.statuses.items())},
        "sredni_czas_etapow_dni": {status_name[k]: v for k, v in p.stage_days.items()},
        "komorki": [{"komorka": u.unit, "objeci_ocena": u.people, "cykle": u.cycles, "sporzadzone": u.drawn_up,
                     "w_toku": u.in_progress, "po_terminie": u.overdue, "w_terminie_proc": u.on_time_percent}
                    for u in p.units],
        "po_terminie_oceny": [int(i) for i in p.overdue_cycles if i.isdigit()],
        "dostepne_komorki": sorted({e.unit for e in scope.employees if e.unit}),
    }


@router.get("/outcomes")
def report_outcomes(rok: int | None = None, komorka: str | None = None, poziom: str | None = None,
                    wynik: str | None = None, x_user_id: str | None = Header(default=None),
                    st: DemoState = Depends(get_state)) -> dict:
    """Level distribution, averages per criterion, units compared, trend between cycles, the people behind a bar.
    Groups smaller than the office minimum (config: raporty.minimalna_grupa) are hidden."""
    who = _actor(st, x_user_id)
    scope = _scope(st, who, rok, komorka)
    o = outcomes(scope, st.evaluations.rules, st.settings.report_min_group, poziom, wynik)

    def group(g) -> dict:
        return {"nazwa": g.key, "osoby": g.people, "srednia": g.average, "pozytywne_proc": g.positive_percent,
                "ukryte": g.hidden}

    return {
        "zakres": _scope_label(st, who, komorka), "minimalna_grupa": o.min_group, "ocenieni": o.total,
        "ukryte": o.hidden,
        "poziomy": [{"poziom": lv, "liczba": n} for lv, n in o.levels],
        "kryteria": [group(g) for g in o.criteria], "komorki": [group(g) for g in o.units],
        "trend": [group(g) for g in o.trend],
        "pracownicy": [] if o.hidden and not (poziom or wynik) else [
            {"evaluation_id": int(p.cycle_id) if p.cycle_id.isdigit() else None, "pracownik": p.name,
             "komorka": p.unit, "poziom": p.level, "srednia": p.average, "wynik": p.outcome,
             "data_oceny": p.evaluated_on.isoformat()} for p in o.people],
        "filtr": {"poziom": poziom, "wynik": wynik},
    }


def _areas() -> dict[str, str]:
    return {cid: c.get("obszar_szkoleniowy", c["nazwa"]) for cid, c in kprm.criteria().items()}


def _needs(st: DemoState, who: str, komorka: str | None):
    scope = _scope(st, who, None, komorka)
    return tn.analyse(scope.people(), scope.cycles, st.evaluations.rules, st.settings.training_score_below,
                      _areas(), komorka or None)


@router.get("/training-needs")
def report_training_needs(komorka: str | None = None, x_user_id: str | None = Header(default=None),
                          st: DemoState = Depends(get_state)) -> dict:
    """Low partial scores -> training areas: per person (with IPRZ) and a ranking; recommendation by the assistant
    (aggregates only; AI off switch respected) or by a template."""
    who = _actor(st, x_user_id)
    people, ranking = _needs(st, who, komorka)
    text, source = st.assistant_for(who).training_recommendation(
        ranking, _scope_label(st, who, komorka), tn.template_recommendation(ranking))
    return {
        "zakres": _scope_label(st, who, komorka), "prog": st.settings.training_score_below,
        "ranking": [{"kryterium": r.criterion, "obszar": r.area, "niskie_oceny": r.low_scores,
                     "ocenieni": r.evaluated} for r in ranking],
        "osoby": [{"pracownik": p.name, "komorka": p.unit, "evaluation_id": int(p.cycle_id) if p.cycle_id.isdigit()
                   else None, "potrzeby": [asdict(n) for n in p.needs], "wnioski_iprz": p.iprz} for p in people],
        "rekomendacja": text, "zrodlo": source,
    }


@router.get("/training-needs.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def report_training_needs_csv(komorka: str | None = None, x_user_id: str | None = Header(default=None),
                              st: DemoState = Depends(get_state)) -> Response:
    who = _actor(st, x_user_id)
    people, _ = _needs(st, who, komorka)
    return Response("﻿" + tn.to_csv(people), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="potrzeby-szkoleniowe.csv"'})

