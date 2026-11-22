"""T12: two consecutive evaluations on one of the two top levels since the last grade -> the next grade
(art. 89 ust. 2 – with it the higher allowance); a different evaluation in between breaks it; employees excluded."""
from datetime import date

from fastapi.testclient import TestClient

from app.domain.consequences import FinishedEvaluation, mandatory_grade
from app.infrastructure.kprm_adapter import kprm_rulebook
from backend.main import app
from conseq_helpers import HR, finish, state

client = TestClient(app)
R = kprm_rulebook()
TOP = lambda d, lvl="powyżej oczekiwań": FinishedEvaluation(d, "pozytywna", lvl, acknowledged=d, evaluation_id="1")  # noqa: E731


def tasks():
    return [t for t in client.get("/api/kadry/zadania", headers={"X-User-Id": HR}).json()
            if t["rodzaj"] == "STOPIEN_OBLIGATORYJNY"]


def test_rule_levels_and_counting_from_the_last_grade():
    two = [TOP(date(2024, 1, 10)), TOP(date(2026, 1, 10), "znacznie powyżej oczekiwań")]
    sig = mandatory_grade(two, True, 3, None, R)
    assert sig and sig.due == date(2026, 2, 9) and "art. 89 ust. 2" in sig.basis  # 30 days from acknowledgement
    assert mandatory_grade(two, True, 3, date(2025, 1, 1), R) is None  # only one since the last grade
    assert mandatory_grade(two, True, 9, None, R) is None  # the highest grade already
    assert mandatory_grade(two, False, None, None, R) is None  # not a civil servant
    mid = [two[0], FinishedEvaluation(date(2025, 1, 1), "pozytywna", "na poziomie oczekiwań"), two[1]]
    assert mandatory_grade(mid, True, 3, None, R) is None


def test_after_two_top_evaluations_hr_gets_the_task():
    st = state(previous=("pozytywna", "znacznie powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 7)
    [task] = tasks()
    assert task["termin"] and "kolejny stopień" in task["tresc"]


def test_another_evaluation_in_between_breaks_it():
    st = state(previous=("pozytywna", "powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 5)  # na poziomie oczekiwań
    finish(st, 7)
    assert tasks() == []


def test_not_for_civil_service_employees():
    st = state(civil_servant=False, grade=None, previous=("pozytywna", "powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 9)
    assert tasks() == []


def hr_notes():
    return [n for n in client.get("/api/notifications", headers={"X-User-Id": HR}).json()
            if n["typ"].endswith("STOPIEN_OBLIGATORYJNY")]


def test_hr_is_reminded_before_the_deadline_of_the_obligatory_grade_until_it_is_granted():
    from dataclasses import replace
    from datetime import datetime

    from app.application import notify_job
    from app.infrastructure.notifier import OutboxNotifier
    from conseq_helpers import EMP

    st = state(previous=("pozytywna", "znacznie powyżej oczekiwań", date(2024, 6, 12)))
    finish(st, 7)  # acknowledged 1.06.2026 -> the grade by 1.07.2026 (30 days)
    st.clock.set(date(2026, 6, 25))
    kinds = sorted(n["typ"] for n in hr_notes())
    assert kinds == ["PRZYPOMNIENIE_STOPIEN_OBLIGATORYJNY", "SKUTEK_STOPIEN_OBLIGATORYJNY"]  # 24.06 yes, 30.06 not yet
    [rem] = [n for n in hr_notes() if n["typ"].startswith("PRZYPOMNIENIE")]
    assert "01.07.2026" in rem["tresc"] and "zostało 7 dni" in rem["tresc"] and "art. 89 ust. 2" in rem["tresc"]
    st.clock.set(date(2026, 7, 1))
    assert len(hr_notes()) == 3  # + 30.06 (1 day before)

    outbox = OutboxNotifier()  # the e-mail job sends them to HR_EMAIL, once
    mail = lambda uid: "kadry@urzad.example" if uid == HR else None  # noqa: E731
    notify_job.run(st, outbox, datetime(2026, 7, 1, 9, 0), st.settings.working_hours, mail)
    grade_mails = [m for m in outbox.sent if m[0] == "kadry@urzad.example" and "stopnia służbowego" in m[1]]
    assert len(grade_mails) == 3
    again = OutboxNotifier()
    notify_job.run(st, again, datetime(2026, 7, 1, 10, 0), st.settings.working_hours, mail)
    assert not [m for m in again.sent if "stopnia służbowego" in m[1]]

    g = st.directory.get(EMP)  # HR records the new grade -> no more task, no more reminders
    st.directory._by_id[EMP] = replace(g, grade=4, grade_since=date(2026, 6, 20))
    assert tasks() == [] and hr_notes() == []


def test_reminder_moved_to_the_working_day_before_a_day_off():
    from app.api.history import consequence_notices

    st = state(previous=("pozytywna", "znacznie powyżej oczekiwań", date(2024, 6, 12)))
    st.clock.set(date(2026, 6, 3))
    finish(st, 7)  # acknowledged 3.06.2026 -> due 3.07.2026 (Fri); 7 days before = Fri 26.06; 1 day before = Thu 2.07
    st.clock.set(date(2026, 6, 6))
    days = {n.key.rsplit("-", 1)[-1]: n.when.date() for n in consequence_notices(st)
                  if n.kind.startswith("PRZYPOMNIENIE")}
    assert days == {"7": date(2026, 6, 26), "1": date(2026, 7, 2)}
    assert all(not st.evaluations.calendar.is_day_off(d) for d in days.values())
