"""T4: daily e-mail job – exactly once, the right recipient, only inside working hours, opt-out respected."""
from dataclasses import replace
from datetime import date, datetime, time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.api.state import reset_state
from app.application import notify_job
from app.infrastructure.notifier import OutboxNotifier, SmtpNotifier
from backend.main import app

client = TestClient(app)
BOSS = "bartlomiej.przelozony"  # evaluates adam.wzor, criteria reminders from 8.06.2026


@pytest.fixture
def st():
    st = reset_state(today=date(2026, 6, 1), ai_mode="off")
    boss = st.directory.get(BOSS)
    st.directory._by_id[BOSS] = replace(boss, email="bartlomiej@urzad.example")
    return st


def email_of(st):
    return lambda uid: st.directory.get(uid).email if st.directory.get(uid) else None


def due_reminders(st, now):
    svc = st.evaluations
    return [r for c in svc.cycles.list_all() for r in svc.reminder_plan(c, st.schedule_for) if r.when <= now]


def run(st, now, notifier=None):
    notifier = notifier or OutboxNotifier()
    return notifier, notify_job.run(st, notifier, now, st.settings.working_hours, email_of(st))


def test_sends_each_due_reminder_exactly_once_to_the_right_address(st):
    now = datetime(2026, 6, 8, 12, 0)  # criteria reminder "co 7 dni" from 1.06 -> Mon 8.06 at 11:00
    assert any(r.recipient_id == BOSS for r in due_reminders(st, now))
    outbox, result = run(st, now)
    assert outbox.sent and all(to == "bartlomiej@urzad.example" for to, _, _ in outbox.sent)
    assert all(rid == BOSS for rid, _ in result.sent)
    assert result.skipped_no_email > 0  # other evaluators have no address -> in-app only
    again, result2 = run(st, now)
    assert again.sent == [] and result2.sent == []


def test_nothing_goes_out_outside_working_hours(st):
    outbox, result = run(st, datetime(2026, 6, 8, 17, 30))
    assert result.outside_hours and outbox.sent == []
    assert st.notify_last_run is None  # the next run inside hours still sends them
    outbox, _ = run(st, datetime(2026, 6, 9, 9, 0))
    assert outbox.sent


def test_reminder_before_its_hour_waits(st):
    outbox, _ = run(st, datetime(2026, 6, 8, 9, 0))  # reminders are at 11:00
    assert outbox.sent == []


def test_user_can_switch_emails_off(st):
    r = client.put("/api/me/przypomnienia", headers={"X-User-Id": BOSS}, json={"email": False})
    assert r.status_code == 200 and r.json()["email"] is False and r.json()["wlasne"] is False
    outbox, result = run(st, datetime(2026, 6, 8, 12, 0))
    assert outbox.sent == [] and result.skipped_opted_out > 0
    assert client.get("/api/me/przypomnienia", headers={"X-User-Id": BOSS}).json()["adres_email"] == \
        "bartlomiej@urzad.example"


def test_sent_keys_survive_a_restart(st):
    import app.api.state as state_mod

    run(st, datetime(2026, 6, 8, 12, 0))
    restored = state_mod.restore(state_mod.snapshot(st), ai_mode="off")
    assert restored.sent_email_keys == st.sent_email_keys and restored.notify_last_run == date(2026, 6, 8)


def test_smtp_adapter_builds_and_sends_the_message():
    with mock.patch("smtplib.SMTP") as smtp:
        SmtpNotifier("smtp.urzad.example", 587, "user", "pw", "oceny@urzad.example").send(
            "a@urzad.example", "Temat", "Treść")
    conn = smtp.return_value.__enter__.return_value
    conn.starttls.assert_called_once()
    conn.login.assert_called_once_with("user", "pw")
    msg = conn.send_message.call_args[0][0]
    assert msg["To"] == "a@urzad.example" and msg["From"] == "oceny@urzad.example"


def test_working_hours_boundary(st):
    assert st.settings.working_hours.contains(time(8, 0)) and not st.settings.working_hours.contains(time(16, 0))
