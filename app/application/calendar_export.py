"""Deadlines as a calendar file (.ics) – for an office without e-mail reminders, or as a second channel.

Each evaluation is one all-day event on the deadline of its current step, with reminders 7 days and 1 day
before. The UID is stable per evaluation, so importing a newer file moves the event to the new step / date
instead of adding a second one (SEQUENCE grows with the time of export). No scores or notes in the file:
only whose evaluation, what is next and until when.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .invitations import UID_DOMAIN, _fold, _text


@dataclass(frozen=True)
class DeadlineEvent:
    key: str          # stable per evaluation, e.g. "12" – the UID is built from it
    day: date         # the deadline (all-day event)
    summary: str
    description: str = ""


def deadlines_ics(events: list[DeadlineEvent], now: datetime | None = None,
                  calendar_name: str = "Oceny okresowe – terminy") -> str:
    """VCALENDAR (METHOD:PUBLISH) with one all-day VEVENT per deadline."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    sequence = int(now.timestamp()) // 60  # newer export = higher SEQUENCE, so calendars take the update
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cyfrowy Asystent Ocen Okresowych//PL",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_text(calendar_name)}"]
    for e in sorted(events, key=lambda x: (x.day, x.key)):
        lines += [
            "BEGIN:VEVENT", f"UID:termin-{e.key}@{UID_DOMAIN}", f"SEQUENCE:{sequence}", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{e.day:%Y%m%d}", f"DTEND;VALUE=DATE:{e.day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_text(e.summary)}",
            *([f"DESCRIPTION:{_text(e.description)}"] if e.description else []),
            "TRANSP:TRANSPARENT",
            *(x for before in ("-P7D", "-P1D") for x in (
                "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{before}", f"DESCRIPTION:{_text(e.summary)}",
                "END:VALARM")),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
