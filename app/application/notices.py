"""Notices about events of the process ("wysłanie powiadomienia" in the KPRM use cases).

Reminders about deadlines are computed from the schedule (use_cases.reminder_plan); these are the one-off notices
that something has happened:
- the objection decided: not upheld / upheld with a change of the evaluation / upheld with drawing it up again
  (art. 83 ust. 4) – to the evaluated person and the evaluator,
- the evaluation changed, or drawn up a second time, as the director general ordered – to the evaluated person
  and HR,
- the request for the next grade (part III, art. 89 ust. 1) submitted with the evaluation – to HR,
- an invitation to a meeting (with an .ics file for the calendar, app/application/invitations.py).

They are shown in the app (GET /api/notifications) and mailed by the e-mail job (notify_job.py), once each.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable

from app.domain.calendar import WorkingCalendar
from app.domain.cycle import CHANGE, REDO, EvaluationCycle
from app.domain.employee import Employee
from app.domain.rulebook import RuleBook
from app.domain.scoring import Outcome

from .use_cases import ProcessEvent

HR = "kadry"


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str  # e.g. "text/calendar; method=REQUEST"
    content: str


@dataclass(frozen=True)
class Notice:
    key: str  # stable: never stored or mailed twice
    recipient_id: str
    kind: str  # e.g. SPRZECIW_UWZGLEDNIONY, OCENA_ZMIENIONA, WNIOSEK_O_STOPIEN, ZAPROSZENIE
    subject: str  # e-mail subject
    text: str  # Polish, shown in the app and as the e-mail body
    cycle_id: str | None
    when: datetime
    attachment: Attachment | None = None


def _d(day: date | None) -> str:
    return f"{day:%d.%m.%Y}" if day else "—"


def _result(c: EvaluationCycle) -> str:
    r = c.result
    if r is None:
        return "—"
    outcome = "pozytywna" if r.outcome is Outcome.POSITIVE else "negatywna"
    return f"{outcome}, {r.level}, średnia {r.average_display}"


def notices_for(event: ProcessEvent, employee: Employee | None, name_of: Callable[[str], str], rules: RuleBook,
                cal: WorkingCalendar, now: time = time(8, 0)) -> list[Notice]:
    """The notices one event gives (may be none)."""
    c, day = event.cycle, event.on
    when = datetime.combine(day, now)
    who = employee.full_name if employee else name_of(c.employee_id)
    out: list[Notice] = []

    def add(recipient: str | None, kind: str, subject: str, text: str) -> None:
        if recipient:
            out.append(Notice(f"{kind}-{c.id}-{recipient}-{day.isoformat()}-{len(c.history)}", recipient, kind,
                              subject, text, c.id, when))

    if event.kind == "SPRZECIW_ROZPATRZONY":
        reason = f" Uzasadnienie: {c.objection_reason}" if c.objection_reason else ""
        if c.objection_decision == "NIEUWZGLEDNIONY":
            court = c.labour_court_deadline(rules, cal)
            add(c.employee_id, "SPRZECIW_NIEUWZGLEDNIONY", "Sprzeciw od oceny okresowej nie został uwzględniony",
                f"Twój sprzeciw od oceny okresowej nie został uwzględniony ({_d(c.objection_decided_on)}).{reason} "
                f"Możesz odwołać się do sądu pracy do {_d(court)} (art. 83 ust. 5 ustawy o służbie cywilnej).")
            add(c.evaluator_id, "SPRZECIW_NIEUWZGLEDNIONY", f"Sprzeciw od oceny – {who}: nieuwzględniony",
                f"Sprzeciw {who} od sporządzonej przez Ciebie oceny nie został uwzględniony – ocena pozostaje bez "
                f"zmian.{reason}")
            return out
        due = c.objection_review_deadline(rules, cal)
        if c.objection_outcome == CHANGE:
            add(c.employee_id, "SPRZECIW_UWZGLEDNIONY", "Sprzeciw od oceny okresowej został uwzględniony",
                f"Twój sprzeciw od oceny okresowej został uwzględniony ({_d(c.objection_decided_on)}): ocena "
                f"zostanie zmieniona przez oceniającego.{reason} O zmianie dostaniesz powiadomienie.")
            add(c.evaluator_id, "POLECENIE_ZMIANY_OCENY", f"Polecenie zmiany oceny – {who}",
                f"Sprzeciw {who} został uwzględniony: zmień ocenę okresową (zastąp kwestionowane fragmenty, np. "
                f"oceny cząstkowe, nowymi; ocena nie może być niższa niż przed sprzeciwem). Termin: {_d(due)} "
                f"(14 dni od wniesienia sprzeciwu, art. 83 ust. 3).{reason}")
        elif c.objection_outcome == REDO:
            add(c.employee_id, "SPRZECIW_UWZGLEDNIONY", "Sprzeciw od oceny okresowej został uwzględniony",
                f"Twój sprzeciw od oceny okresowej został uwzględniony ({_d(c.objection_decided_on)}): ocena została "
                f"anulowana i zostanie sporządzona po raz drugi. Proces wraca do etapu „rozmowa oceniająca i "
                f"dokonanie oceny”.{reason}")
            add(c.evaluator_id, "POLECENIE_PONOWNEGO_SPORZADZENIA", f"Polecenie ponownego sporządzenia oceny – {who}",
                f"Sprzeciw {who} został uwzględniony: ocena została anulowana – sporządź ją po raz drugi (rozmowa "
                f"oceniająca i dokonanie oceny). Termin: {_d(due)} (14 dni od wniesienia sprzeciwu, art. 83 ust. 3)."
                f"{reason}")
        return out

    if event.kind == "OCENA_ZMIENIONA":
        text = (f"Ocena okresowa {who} została zmieniona w wyniku uwzględnienia sprzeciwu ({_d(day)}). "
                f"Wynik po zmianie: {_result(c)}.")
        add(c.employee_id, "OCENA_ZMIENIONA", "Ocena okresowa została zmieniona po sprzeciwie",
            f"Twoja ocena okresowa została zmieniona w wyniku uwzględnienia sprzeciwu ({_d(day)}). "
            f"Wynik po zmianie: {_result(c)}. Arkusz po zmianie jest dostępny w systemie.")
        add(HR, "OCENA_ZMIENIONA", f"Ocena zmieniona po sprzeciwie – {who}", text)
    elif event.kind == "OCENA_SPORZADZONA_PONOWNIE":
        add(c.employee_id, "OCENA_SPORZADZONA_PONOWNIE", "Ocena okresowa sporządzona po raz drugi",
            f"Twoja ocena okresowa została sporządzona po raz drugi ({_d(day)}) po uwzględnieniu sprzeciwu – "
            f"zapoznaj się z nią. Od tej oceny przysługuje ponowny sprzeciw (art. 83 ust. 4).")
        add(HR, "OCENA_SPORZADZONA_PONOWNIE", f"Ocena sporządzona po raz drugi – {who}",
            f"Ocena okresowa {who} została sporządzona po raz drugi ({_d(day)}) po uwzględnieniu sprzeciwu. "
            f"Wynik: {_result(c)}.")
    if event.kind in ("OCENA_SPORZADZONA", "OCENA_SPORZADZONA_PONOWNIE", "OCENA_ZMIENIONA") and c.promotion_request \
            and c.result is not None and c.result.outcome is Outcome.POSITIVE:
        held = c.held_grade if c.held_grade is not None else (employee.grade if employee else None)
        grades = f" (stopień {held} → {held + 1})" if held is not None else ""
        add(HR, "WNIOSEK_O_STOPIEN", f"Wniosek o kolejny stopień służbowy – {who}",
            f"{name_of(c.evaluator_id)} złożył(a) wniosek o przyznanie {who} kolejnego stopnia służbowego"
            f"{grades} w ocenie okresowej sporządzonej {_d(c.evaluated_on)} (część III arkusza, art. 89 ust. 1 "
            f"ustawy o służbie cywilnej). Ocena: {_result(c)}."
            + (f" Umotywowanie: {c.promotion_motivation}" if c.promotion_motivation else ""))
    return out
