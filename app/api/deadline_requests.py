"""Change of the evaluation deadline (art. 81 ust. 8, § 8) and planned absences of evaluators.

- POST /api/evaluations/{id}/deadline-changes   the evaluator (or deputy) changes the deadline. Office setting
  `zmiana_terminu.zatwierdza`: OCENIAJACY (default – the evaluator's decision applies at once, as the Act says) or
  KADRY (the office's own procedure: the request waits for HR).
- POST /api/deadline-changes/{id}/decision       HR accepts / rejects a waiting request.
- GET  /api/deadline-changes                     requests the user may see (HR: all), filter `status`.
- GET  /api/deadline-changes/{id}/pdf            the letter to the evaluated person (§ 8) – accepted changes only.
- POST /api/evaluator-absences                   a planned absence of an evaluator -> for each subordinate whose
  deadline falls in it: a deputy already covers it, or a proposed new deadline (+ whether the law allows it).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from app.domain.cycle import EvaluationCycle, Status
from app.domain.deadline_change import REASONS, check_deadline_change, suggested_deadline
from app.domain.errors import NotAuthorized, NotFound, ValidationError

from . import schemas as s
from .access import actor as _actor
from .access import require_evaluator, require_read
from .errors import ApiProblem
from .evaluations import _employee, _osoba
from .state import DeadlineChangeRecord, DemoState, EvaluatorAbsenceRecord, get_state

router = APIRouter(prefix="/api", tags=["nieobecności"])


class DecisionIn(BaseModel):
    status: Literal["ZAAKCEPTOWANY", "ODRZUCONY"]
    komentarz: str = ""


class EvaluatorAbsenceIn(BaseModel):
    oceniajacy_id: int  # the contract's int id of the evaluator
    od: date
    do: date


class AbsenceHint(BaseModel):
    evaluation_id: int
    oceniany: s.OsobaRef
    termin: date  # the deadline that falls inside the absence
    rodzaj_terminu: Literal["OCENA", "KRYTERIA"]
    zastepca: s.OsobaRef | None = None  # a deputy covering the whole absence – nothing else to do
    proponowany_termin: date | None = None
    mozna_zmienic_termin: bool = False
    dlaczego_nie: list[str] = []


class EvaluatorAbsenceOut(BaseModel):
    id: int
    oceniajacy: s.OsobaRef
    od: date
    do: date
    podpowiedzi: list[AbsenceHint]
    komunikat: str


# ---------------------------------------------------------------- helpers

def change_out(st: DemoState, r: DeadlineChangeRecord) -> s.DeadlineChangeOut:
    c = st.evaluations.cycles.get(r.cycle_id)
    emp = st.directory.get(c.employee_id) if c else None
    by = st.directory.get(r.requested_by) if r.requested_by else None
    return s.DeadlineChangeOut(
        id=r.id, powod=s.PowodZmianyTerminu(r.reason), stary_termin=r.old, nowy_termin=r.new,
        status=s.StatusWniosku(r.status), uzasadnienie=r.justification, decyzja_at=r.decided_at,
        evaluation_id=int(r.cycle_id) if r.cycle_id.isdigit() else None, oceniany=_osoba(st, emp) if emp else None,
        zlozyl=_osoba(st, by) if by else None, komentarz_decyzji=r.decision_note or None,
        pismo_pdf=r.status == s.StatusWniosku.ZAAKCEPTOWANY.value and r.reason in REASONS)


def _record(st: DemoState, change_id: int) -> DeadlineChangeRecord:
    r = next((x for x in st.deadline_changes if x.id == change_id), None)
    if r is None:
        raise NotFound(f"Nie ma zmiany terminu o identyfikatorze {change_id}.")
    return r


def _cycle(st: DemoState, evaluation_id: int) -> EvaluationCycle:
    c = st.evaluations.cycles.get(str(evaluation_id))
    if c is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    return c


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- change of the deadline

@router.post("/evaluations/{evaluation_id}/deadline-changes", response_model=s.DeadlineChangeOut, status_code=201)
def request_change(evaluation_id: int, body: s.DeadlineChangeIn, x_user_id: str | None = Header(default=None),
                   st: DemoState = Depends(get_state)) -> s.DeadlineChangeOut:
    who = _actor(st, x_user_id)
    c = _cycle(st, evaluation_id)
    if any(r.cycle_id == c.id and r.status == s.StatusWniosku.ZLOZONY.value for r in st.deadline_changes):
        raise ApiProblem(409, "WNIOSEK_W_TOKU", "Ta ocena ma już wniosek o zmianę terminu czekający na decyzję.")
    if who == c.employee_id:
        return _employee_request(st, c, body)
    require_evaluator(st, who, c, "Termin oceny zmienia oceniający (art. 81 ust. 8) albo jego zastępca.")
    reason, text = body.powod.value, (body.uzasadnienie or "")
    svc = st.evaluations
    immediate = st.settings.deadline_change_approver == "OCENIAJACY"
    if immediate:
        old, new = svc.change_deadline(c.id, who, reason, body.nowy_termin, text)
        st.touch(c.id)
    else:
        old, new = svc.check_deadline_change(c.id, who, reason, body.nowy_termin, text)
    r = DeadlineChangeRecord(
        id=max((x.id for x in st.deadline_changes), default=0) + 1, cycle_id=c.id, reason=reason, old=old, new=new,
        status=(s.StatusWniosku.ZAAKCEPTOWANY if immediate else s.StatusWniosku.ZLOZONY).value,
        justification=text, decided_at=_now() if immediate else None, requested_by=who,
        decided_by=who if immediate else None)
    st.deadline_changes.append(r)
    if immediate:
        register_letter(st, r)
    return change_out(st, r)


def _notify(st: DemoState, recipient: str, kind: str, subject: str, text: str, c: EvaluationCycle, key: str) -> None:
    from app.application.notices import Notice

    st.add_notice(Notice(f"{kind}-{key}", recipient, kind, subject, text, c.id,
                         datetime.combine(st.clock.today(), datetime.min.time().replace(hour=8))))


def _employee_request(st: DemoState, c: EvaluationCycle, body: s.DeadlineChangeIn) -> s.DeadlineChangeOut:
    """The evaluated person asks for another deadline (KPRM use case): a request with a proposed date and the
    reasons; the evaluator decides (art. 81 ust. 8). The date is checked now, and again when it is accepted."""
    if not body.nowy_termin:
        raise ValidationError(["Podaj proponowany termin oceny."])
    if not (body.uzasadnienie or "").strip():
        raise ValidationError(["Napisz, dlaczego prosisz o zmianę terminu."])
    reason, text = s.PowodZmianyTerminu.WNIOSEK_OCENIANEGO.value, body.uzasadnienie.strip()
    old, new = st.evaluations.check_deadline_change(c.id, c.evaluator_id, reason, body.nowy_termin, text)
    r = DeadlineChangeRecord(id=max((x.id for x in st.deadline_changes), default=0) + 1, cycle_id=c.id,
                             reason=reason, old=old, new=new, status=s.StatusWniosku.ZLOZONY.value,
                             justification=text, decided_at=None, requested_by=c.employee_id, decided_by=None)
    st.deadline_changes.append(r)
    who = st.person_name(c.employee_id)
    _notify(st, c.evaluator_id, "WNIOSEK_O_ZMIANE_TERMINU", f"Wniosek o zmianę terminu oceny – {who}",
            f"{who} prosi o zmianę terminu oceny okresowej z {old:%d.%m.%Y} na {new:%d.%m.%Y}. Uzasadnienie: {text} "
            "Decyzję podejmujesz w ocenie (Zmiana terminu oceny).", c, f"{r.id}-zlozony")
    return change_out(st, r)


@router.post("/deadline-changes/{change_id}/decision", response_model=s.DeadlineChangeOut)
def decide(change_id: int, body: DecisionIn, x_user_id: str | None = Header(default=None),
           st: DemoState = Depends(get_state)) -> s.DeadlineChangeOut:
    who = _actor(st, x_user_id)
    r = _record(st, change_id)
    c0 = _cycle(st, int(r.cycle_id))
    from_employee = r.requested_by == c0.employee_id
    # the evaluated person's request: their evaluator decides (art. 81 ust. 8); a request of the evaluator
    # waiting for approval: HR (office setting zmiana_terminu.zatwierdza=KADRY)
    if not st.policy().is_admin(who) and not (from_employee and st.policy().can_act_as_evaluator(
            who, c0.employee_id, c0.evaluator_id)):
        raise NotAuthorized("O wniosku ocenianego decyduje oceniający; o pozostałych wnioskach – dział kadr.")
    if r.status != s.StatusWniosku.ZLOZONY.value:
        raise ApiProblem(409, "WNIOSEK_ROZPATRZONY", "Ten wniosek został już rozpatrzony.")
    if body.status == "ZAAKCEPTOWANY":
        c = _cycle(st, int(r.cycle_id))
        # re-checked today (the situation may have changed since the request); applied as the evaluator's decision
        old, new = st.evaluations.change_deadline(c.id, c.evaluator_id, r.reason, r.new, r.justification)
        r.old, r.new = old, new
        st.touch(c.id)
    r.status, r.decided_at, r.decided_by, r.decision_note = body.status, _now(), who, body.komentarz
    register_letter(st, r)
    if from_employee:
        ok = body.status == "ZAAKCEPTOWANY"
        note = f" Komentarz: {body.komentarz}" if body.komentarz else ""
        _notify(st, c0.employee_id, "DECYZJA_ZMIANA_TERMINU",
                "Wniosek o zmianę terminu oceny " + ("przyjęty" if ok else "odrzucony"),
                (f"Twój wniosek o zmianę terminu oceny został przyjęty: nowy termin {r.new:%d.%m.%Y}." if ok else
                 f"Twój wniosek o zmianę terminu oceny został odrzucony – termin bez zmian ({r.old:%d.%m.%Y}).")
                + note, c0, f"{r.id}-decyzja")
    return change_out(st, r)


@router.get("/deadline-changes", response_model=list[s.DeadlineChangeOut])
def list_changes(status: s.StatusWniosku | None = None, x_user_id: str | None = Header(default=None),
                 st: DemoState = Depends(get_state)) -> list[s.DeadlineChangeOut]:
    who = _actor(st, x_user_id)
    policy = st.policy()
    out = []
    for r in sorted(st.deadline_changes, key=lambda x: x.id, reverse=True):
        c = st.evaluations.cycles.get(r.cycle_id)
        if c is None or (status and r.status != status.value):
            continue
        if policy.can_read(who, c.employee_id, c.evaluator_id):
            out.append(change_out(st, r))
    return out


@router.get("/deadline-changes/{change_id}/pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def notice_pdf(change_id: int, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> Response:
    who = _actor(st, x_user_id)
    r = _record(st, change_id)
    c = _cycle(st, int(r.cycle_id))
    require_read(st, who, c)
    if not _has_letter(r):
        raise ApiProblem(409, "BRAK_PISMA", "Pismo powstaje dla zaakceptowanej zmiany terminu (art. 81 ust. 8).")
    return Response(_letter_pdf(st, r, c), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="zmiana-terminu-{r.id}.pdf"'})


def _has_letter(r: DeadlineChangeRecord) -> bool:
    return r.status == s.StatusWniosku.ZAAKCEPTOWANY.value and r.reason in REASONS and r.new is not None


def _issued(st: DemoState, r: DeadlineChangeRecord) -> date:
    return r.decided_at.date() if r.decided_at else st.clock.today()


def _letter_pdf(st: DemoState, r: DeadlineChangeRecord, c: EvaluationCycle) -> bytes:
    from backend.notice_pdf import DeadlineNotice, render_deadline_notice

    emp, boss = st.directory.get(c.employee_id), st.directory.get(c.evaluator_id)
    return render_deadline_notice(DeadlineNotice(
        office=emp.office, place="", issued_on=_issued(st, r), employee_name=emp.full_name,
        employee_position=emp.position, employee_unit=emp.unit,
        evaluator_name=boss.full_name if boss else c.evaluator_id, evaluator_position=boss.position if boss else "",
        old_deadline=r.old, new_deadline=r.new, legal_basis=REASONS[r.reason], justification=r.justification))


def letter_document_for(st: DemoState, r: DeadlineChangeRecord):
    """The letter as an EZD document (None when there is no letter for this change)."""
    from app.application.ezd_registry import letter_document
    from backend import config

    c = st.evaluations.cycles.get(r.cycle_id)
    if c is None or not _has_letter(r):
        return None
    return letter_document(r.id, c, _letter_pdf(st, r, c), _issued(st, r), config.EZD_JRWA,
                           st.person_name(c.evaluator_id), st.person_name(c.employee_id))


def register_letter(st: DemoState, r: DeadlineChangeRecord) -> None:
    """An accepted change: the letter goes to EZD (when EZD is switched on)."""
    svc = st.ezd()
    doc = letter_document_for(st, r) if svc else None
    if doc is not None:
        svc.register(doc)


# ---------------------------------------------------------------- planned absence of an evaluator

def _hints(st: DemoState, a: EvaluatorAbsenceRecord) -> list[AbsenceHint]:
    svc = st.evaluations
    covering = next((d for d in st.deputy_records if d.evaluator_id == a.evaluator_id and d.od <= a.od
                     and d.do >= a.do), None)
    deputy = st.directory.get(covering.deputy_id) if covering else None
    out = []
    for c in svc.cycles.list_all():
        if c.evaluator_id != a.evaluator_id or c.status in (Status.EVALUATION_DONE, Status.ACKNOWLEDGED,
                                                            Status.OBJECTION):
            continue
        if c.status is Status.CYCLE_STARTED and a.od <= c.criteria_deadline <= a.do:
            due, kind = c.criteria_deadline, "KRYTERIA"
        else:
            due, kind = c.evaluation_deadline(svc.rules, svc.calendar), "OCENA"
            if not a.od <= due <= a.do:
                continue
        emp = st.directory.get(c.employee_id)
        hint = AbsenceHint(evaluation_id=int(c.id), oceniany=_osoba(st, emp), termin=due, rodzaj_terminu=kind,
                           zastepca=_osoba(st, deputy) if deputy else None)
        if kind == "OCENA" and deputy is None:
            proposal = suggested_deadline(a.do, st.settings.deadline_days_after_return, svc.calendar)
            hint.proponowany_termin = proposal
            try:
                check_deadline_change("PRZEWIDYWANA_NIEOBECNOSC_OCENIAJACEGO", c.start_date, due, proposal,
                                      st.clock.today(), svc.rules, svc.calendar, "planowana nieobecność")
                hint.mozna_zmienic_termin = True
            except ValidationError as e:
                hint.dlaczego_nie = list(e.problems)
        out.append(hint)
    return sorted(out, key=lambda h: h.termin)


def _absence_out(st: DemoState, a: EvaluatorAbsenceRecord) -> EvaluatorAbsenceOut:
    hints = _hints(st, a)
    todo = [h for h in hints if h.zastepca is None]
    msg = ("Żaden termin podwładnych nie wypada w tej nieobecności." if not hints else
           "Wszystkie terminy w tej nieobecności obsłuży zastępca." if not todo else
           f"Terminy {len(todo)} podwładnych wypadają w tej nieobecności: wyznacz zastępcę albo zmień termin oceny "
           "(art. 81 ust. 8 pkt 3) – oceniany dostanie pisemne powiadomienie.")
    return EvaluatorAbsenceOut(id=a.id, oceniajacy=_osoba(st, st.directory.get(a.evaluator_id)), od=a.od, do=a.do,
                               podpowiedzi=hints, komunikat=msg)


@router.post("/evaluator-absences", response_model=EvaluatorAbsenceOut, status_code=201)
def register_evaluator_absence(body: EvaluatorAbsenceIn, x_user_id: str | None = Header(default=None),
                               st: DemoState = Depends(get_state)) -> EvaluatorAbsenceOut:
    who = _actor(st, x_user_id)
    boss = _employee(st, body.oceniajacy_id)
    if who != boss.id and not st.policy().is_admin(who):
        raise NotAuthorized("Planowaną nieobecność oceniającego zgłasza on sam albo dział kadr.")
    if body.do < body.od:
        raise ValidationError(["Koniec nieobecności nie może być wcześniejszy niż jej początek."])
    a = EvaluatorAbsenceRecord(id=max((x.id for x in st.evaluator_absences), default=0) + 1, evaluator_id=boss.id,
                               od=body.od, do=body.do, registered_by=who)
    st.evaluator_absences.append(a)
    return _absence_out(st, a)


@router.get("/evaluator-absences", response_model=list[EvaluatorAbsenceOut])
def list_evaluator_absences(x_user_id: str | None = Header(default=None),
                            st: DemoState = Depends(get_state)) -> list[EvaluatorAbsenceOut]:
    who = _actor(st, x_user_id)
    admin = st.policy().is_admin(who)
    return [_absence_out(st, a) for a in st.evaluator_absences if admin or a.evaluator_id == who]


def notifications_for(st: DemoState, who: str) -> list[tuple[str, str, int, datetime]]:
    """In-app notices of accepted deadline changes for the evaluated person: (key, text, evaluation id, when)."""
    out = []
    for r in st.deadline_changes:
        c = st.evaluations.cycles.get(r.cycle_id)
        if (c and c.employee_id == who and r.status == s.StatusWniosku.ZAAKCEPTOWANY.value and r.reason in REASONS
                and r.decided_at and r.new):
            out.append((f"zmiana-terminu-{r.id}",
                        f"Zmieniono termin Twojej oceny okresowej z {r.old:%d.%m.%Y} na {r.new:%d.%m.%Y}. "
                        "Pismo z uzasadnieniem jest w ocenie.", int(r.cycle_id), r.decided_at))
    return out

