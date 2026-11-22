"""Daily job: sends by e-mail the reminders that fell due since the last run.

    python -m app.application.notify_job        (cron / Harmonogram zadań Windows, e.g. every hour 8–16)

- The same schedules as the in-app notifications (EvaluationService.reminder_plan + the recipient's own schedule).
- Never twice: the keys of sent reminders are kept in the application state (saved in the database).
- Only inside office working hours (config/ustawienia_urzedu.json) – outside them the job sends nothing and the
  reminders wait for the next run.
- No e-mail address, or e-mail switched off by the user (PUT /api/me/przypomnienia `email`) = in-app only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Protocol

from app.application.notices import Notice
from app.application.ports import Notifier
from app.application.use_cases import EvaluationService, PlannedReminder
from app.domain.reminder_schedule import ReminderSchedule, WorkingHours

FIRST_RUN_LOOKBACK_DAYS = 7  # the very first run does not mail the whole history


class NotifyState(Protocol):
    """What the job reads and remembers (DemoState in the app)."""
    evaluations: EvaluationService
    sent_email_keys: set[str]
    email_off_for: set[str]
    notify_last_run: date | None
    notices: list[Notice]  # one-off notices (objection decided, evaluation changed, invitations, ...)

    def schedule_for(self, user_id: str) -> ReminderSchedule: ...


@dataclass
class JobResult:
    sent: list[tuple[str, str]] = field(default_factory=list)  # (recipient id, reminder key)
    skipped_no_email: int = 0
    skipped_opted_out: int = 0
    outside_hours: bool = False


def _subject(r: PlannedReminder) -> str:
    return f"Przypomnienie: ocena okresowa – termin {r.deadline:%d.%m.%Y}"


def run(st: NotifyState, notifier: Notifier, now: datetime, hours: WorkingHours,
        email_of: Callable[[str], str | None]) -> JobResult:
    out = JobResult()
    if not hours.contains(now.time()):
        out.outside_hours = True
        return out
    since = st.notify_last_run or (now.date() - timedelta(days=FIRST_RUN_LOOKBACK_DAYS))
    svc = st.evaluations
    due = sorted((r for c in svc.cycles.list_all() for r in svc.reminder_plan(c, st.schedule_for)
                  if r.when <= now and r.when.date() >= since and r.key not in st.sent_email_keys),
                 key=lambda r: r.when)
    for r in due:
        if r.recipient_id in st.email_off_for:
            out.skipped_opted_out += 1
            continue
        address = email_of(r.recipient_id)
        if not address:
            out.skipped_no_email += 1
            continue
        notifier.send(address, _subject(r), r.message)
        st.sent_email_keys.add(r.key)
        out.sent.append((r.recipient_id, r.key))
    # notices about events: everything not mailed yet (invitations with their .ics; with e-mails switched off the
    # .ics is still in the app: GET /api/evaluations/{id}/zaproszenia/{n}.ics)
    for n in sorted(getattr(st, "notices", []), key=lambda n: n.when):
        key = f"powiadomienie:{n.key}"
        if key in st.sent_email_keys or n.when > now:
            continue
        if n.recipient_id in st.email_off_for:
            out.skipped_opted_out += 1
            continue
        address = email_of(n.recipient_id)
        if not address:
            out.skipped_no_email += 1
            continue
        notifier.send(address, n.subject, n.text, [n.attachment] if n.attachment else [])
        st.sent_email_keys.add(key)
        out.sent.append((n.recipient_id, key))
    st.notify_last_run = now.date()
    return out


def main() -> int:  # composition root: the app's state, SMTP from .env
    from app.api.state import get_state, save_state
    from app.infrastructure.clock import OFFICE_TZ, FixedClock
    from app.infrastructure.notifier import from_config

    st = get_state()
    now = datetime.now(OFFICE_TZ).replace(tzinfo=None)
    if isinstance(st.clock, FixedClock):  # demo: the demo clock's day, the real time of day
        now = datetime.combine(st.clock.today(), now.time())

    result = run(st, from_config(), now, st.settings.working_hours, st.email_of)
    save_state()
    if result.outside_hours:
        print("Poza godzinami pracy urzędu – nic nie wysłano.")
    else:
        print(f"Wysłano: {len(result.sent)}, bez adresu: {result.skipped_no_email}, "
              f"wyłączone e-maile: {result.skipped_opted_out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
