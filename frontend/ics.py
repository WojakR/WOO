"""Calendar invitation file (.ics) – opens in Outlook, Thunderbird, Google Calendar. No data is stored."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta


def ics_invite(title: str, start: datetime, minutes: int, description: str) -> bytes:
    fmt = "%Y%m%dT%H%M%S"
    end = start + timedelta(minutes=minutes)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cyfrowy Asystent Ocen Okresowych//PL", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@asystent-ocen", f"DTSTAMP:{datetime.now():{fmt}}",
        f"DTSTART:{start:{fmt}}", f"DTEND:{end:{fmt}}", f"SUMMARY:{title}",
        "DESCRIPTION:" + description.replace("\n", "\n"), "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines).encode("utf-8")
