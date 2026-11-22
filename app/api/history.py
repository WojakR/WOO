"""A person's finished evaluations (for the consequences of consecutive evaluations and part III of the sheet).

Finished = drawn up AND acknowledged (an objection still pending keeps the evaluation as it was; an upheld one sends
it back to the evaluator, so it is not finished). The evaluation known from the HR data counts as the first one
when it is older than everything in the system.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.domain.consequences import FinishedEvaluation, Signal, mandatory_grade, two_negatives
from app.domain.cycle import EvaluationCycle, Status
from app.domain.errors import NotAuthorized

from . import schemas as s
from .access import actor as _actor
from .state import HR, DemoState, get_state

router = APIRouter(prefix="/api", tags=["kadry"])
_FINISHED = (Status.ACKNOWLEDGED, Status.OBJECTION)


def history_of(st: DemoState, employee_id: str, exclude_cycle: str | None = None) -> list[FinishedEvaluation]:
    cycles = [c for c in st.evaluations.cycles.list_all() if c.employee_id == employee_id and c.id != exclude_cycle
              and c.status in _FINISHED and c.result is not None and c.evaluated_on]
    out = [FinishedEvaluation(c.evaluated_on, c.result.outcome.value, c.result.level, c.acknowledged_on, c.id)
           for c in cycles]
    e = st.directory.get(employee_id)
    p = e.previous_evaluation if e else None
    for p in [*(e.earlier_evaluations if e else ()), p]:  # from the HR data: only those before the system's own
        if p and p.date and p.outcome and all(p.date < h.drawn_up for h in out if h.evaluation_id):
            out.append(FinishedEvaluation(p.date, p.outcome, p.level, p.acknowledged, None))
    return sorted(out, key=lambda h: h.drawn_up)


def signals_for(st: DemoState, employee_id: str) -> list[Signal]:
    e = st.directory.get(employee_id)
    if e is None:
        return []
    hist = history_of(st, employee_id)
    rules = st.evaluations.rules
    found = [two_negatives(hist, e.civil_servant, rules),
             mandatory_grade(hist, e.civil_servant, e.grade, e.grade_since, rules)]
    # only signals triggered by an evaluation made in the system (the HR data is history, not a new event)
    return [x for x in found if x is not None and x.evaluation_id is not None]


class HrTask(BaseModel):
    rodzaj: str  # DWIE_NEGATYWNE | STOPIEN_OBLIGATORYJNY
    oceniany: s.OsobaRef
    evaluation_id: int | None
    tresc: str
    podstawa: str | None = None
    termin: date | None = None


@router.get("/kadry/zadania", response_model=list[HrTask])
def hr_tasks(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> list[HrTask]:
    """Consequences of consecutive evaluations the HR department must act on (the system decides nothing)."""
    from .evaluations import _osoba

    who = _actor(st, x_user_id)
    if not st.policy().is_admin(who):
        raise NotAuthorized("Zadania działu kadr widzi dział kadr.")
    out = []
    for e in st.directory.all():
        for sig in signals_for(st, e.id):
            out.append(HrTask(rodzaj=sig.kind, oceniany=_osoba(st, e), evaluation_id=int(sig.evaluation_id),
                              tresc=sig.message, podstawa=sig.basis, termin=sig.due))
    out += promotion_requests(st)
    return out


def promotion_requests(st: DemoState) -> list[HrTask]:
    """Requests for the next grade (part III, art. 89 ust. 1) in evaluations drawn up – HR prepares the decision.
    The notice to HR goes out when the evaluation is drawn up (app/application/notices.py)."""
    from app.domain.scoring import Outcome

    from .evaluations import _osoba

    out = []
    for c in st.evaluations.cycles.list_all():
        if not (c.promotion_request and c.result is not None and c.result.outcome is Outcome.POSITIVE
                and c.status in (Status.EVALUATION_DONE, *_FINISHED)):
            continue
        e = st.directory.get(c.employee_id)
        held = c.held_grade if c.held_grade is not None else (e.grade if e else None)
        state = {Status.EVALUATION_DONE: "ocena czeka na zapoznanie", Status.OBJECTION: "od oceny wniesiono sprzeciw",
                 Status.ACKNOWLEDGED: "ocena zapoznana"}[c.status]
        grades = f" (stopień {held} → {held + 1})" if held is not None else ""
        out.append(HrTask(rodzaj="WNIOSEK_O_STOPIEN", oceniany=_osoba(st, e), evaluation_id=int(c.id),
                          tresc=f"Wniosek oceniającego o przyznanie kolejnego stopnia służbowego{grades} w ocenie z "
                                f"{c.evaluated_on:%d.%m.%Y}; {state}.",
                          podstawa="art. 89 ust. 1 ustawy o służbie cywilnej", termin=None))
    return out


GRADE_REMINDER_DAYS_BEFORE = (7, 1)  # reminders to HR before the deadline of the obligatory grade (art. 89 ust. 2)


def consequence_notices(st: DemoState) -> list[Notice]:
    """Notices to HR about the consequences of consecutive evaluations (past and future – callers filter by date):
    one on the day the evaluation was acknowledged, and for the obligatory grade (art. 89 ust. 2) reminders
    GRADE_REMINDER_DAYS_BEFORE days before its deadline (moved to the working day before a day off). They stop
    when HR records the new grade (`grade_since` after the evaluation – the signal disappears)."""
    from datetime import datetime, time, timedelta

    from app.application.notices import Notice

    cal = st.evaluations.calendar
    out: list[Notice] = []
    for e in st.directory.all():
        for sig in signals_for(st, e.id):
            c: EvaluationCycle | None = st.evaluations.cycles.get(sig.evaluation_id)
            day = (c.acknowledged_on if c and c.acknowledged_on else st.clock.today())
            subject = ("Obowiązek przyznania kolejnego stopnia służbowego" if sig.kind == "STOPIEN_OBLIGATORYJNY"
                       else "Dwie kolejne negatywne oceny okresowe") + f" – {e.full_name}"
            out.append(Notice(f"skutek-{sig.kind}-{sig.evaluation_id}", HR, f"SKUTEK_{sig.kind}", subject,
                              f"{e.full_name}: {sig.message}", sig.evaluation_id, datetime.combine(day, time(8, 0))))
            if sig.kind != "STOPIEN_OBLIGATORYJNY" or sig.due is None:
                continue
            for before in GRADE_REMINDER_DAYS_BEFORE:
                when = sig.due - timedelta(days=before)
                while cal.is_day_off(when) and when > day:
                    when -= timedelta(days=1)
                if when <= day:  # nothing to remind of on (or before) the day of the first notice
                    continue
                left = (sig.due - when).days
                out.append(Notice(
                    f"skutek-{sig.kind}-{sig.evaluation_id}-przed-{before}", HR,
                    "PRZYPOMNIENIE_STOPIEN_OBLIGATORYJNY", f"Przypomnienie: {subject}",
                    f"Przypomnienie: {e.full_name} – do {sig.due:%d.%m.%Y} (zostało {left} dni) należy przyznać kolejny "
                    f"stopień służbowy ({sig.basis}). Po przyznaniu wpisz nowy stopień i datę w danych pracownika – "
                    f"przypomnienia ustaną.",
                    sig.evaluation_id, datetime.combine(when, time(8, 0))))
    return out


def notifications_for(st: DemoState, who: str):
    """HR / administrators: the consequence notices that are due (consequence_notices)."""
    if not st.policy().is_admin(who):
        return []
    today = st.clock.today()
    return [(n.key, n.text, int(n.cycle_id), n.when, n.kind) for n in consequence_notices(st) if n.when.date() <= today]

