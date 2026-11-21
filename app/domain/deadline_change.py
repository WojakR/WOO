"""Optional change of the evaluation deadline – art. 81 ust. 8 ustawy o służbie cywilnej, § 8 rozporządzenia.

The evaluator may change the deadline (art. 81 ust. 4) in one of four cases:
  1) a change on the evaluator's post during the evaluated period,
  2) a planned, longer, justified absence of the evaluated person that may make the evaluation impossible,
  3) a planned, longer, justified absence of the evaluator that may make it difficult,
  4) the evaluated person's request,
– only if more than 6 months (reguly.json) passed since the last evaluation was drawn up, or – for a first
evaluation – the evaluated period is longer than 6 months. The evaluated person is informed IN WRITING of the new
deadline; a copy of the letter is attached to the sheet (§ 8).
"""
from __future__ import annotations

from datetime import date, timedelta

from .calendar import WorkingCalendar, add_months
from .errors import ValidationError
from .rulebook import RuleBook

# reason (PowodZmianyTerminu) -> point of art. 81 ust. 8
REASONS = {
    "ZMIANA_OCENIAJACEGO": "art. 81 ust. 8 pkt 1 – zmiana na stanowisku oceniającego",
    "PRZEWIDYWANA_NIEOBECNOSC_OCENIANEGO": "art. 81 ust. 8 pkt 2 – przewidywana dłuższa usprawiedliwiona "
                                           "nieobecność ocenianego",
    "PRZEWIDYWANA_NIEOBECNOSC_OCENIAJACEGO": "art. 81 ust. 8 pkt 3 – przewidywana dłuższa usprawiedliwiona "
                                             "nieobecność oceniającego",
    "WNIOSEK_OCENIANEGO": "art. 81 ust. 8 pkt 4 – wniosek ocenianego",
}


def check_deadline_change(reason: str, start: date, current_deadline: date, new_deadline: date | None, today: date,
                          rules: RuleBook, cal: WorkingCalendar, justification: str = "") -> date:
    """The new deadline (moved to a working day) or ValidationError with every reason it is not allowed.
    `start` = the day the last evaluation was drawn up, or the start of the first evaluated period."""
    problems = []
    if reason not in REASONS:
        problems.append("Zmiana terminu jest możliwa tylko w przypadkach z art. 81 ust. 8 ustawy "
                        "(zmiana oceniającego, przewidywana nieobecność ocenianego lub oceniającego, wniosek ocenianego).")
    months = rules.deadline_change_after_months
    if add_months(start, months) >= today:
        problems.append(f"Termin można zmienić dopiero, gdy od ostatniej oceny (albo początku okresu oceny) minęło "
                        f"więcej niż {months} mies. – tj. od {add_months(start, months) + timedelta(days=1):%d.%m.%Y}.")
    if new_deadline is None:
        problems.append("Podaj nowy termin oceny.")
    elif new_deadline <= today:
        problems.append("Nowy termin musi być późniejszy niż dzisiejsza data.")
    elif new_deadline == current_deadline:
        problems.append("Nowy termin jest taki sam jak obecny.")
    if not justification.strip():
        problems.append("Podaj uzasadnienie zmiany terminu (trafi do pisma do ocenianego).")
    if problems:
        raise ValidationError(problems)
    return cal.next_working_day(new_deadline)


def suggested_deadline(absence_end: date, days_after_return: int, cal: WorkingCalendar) -> date:
    """A proposal after an absence: `days_after_return` days after it ends, on a working day."""
    return cal.next_working_day(absence_end + timedelta(days=days_after_return))
