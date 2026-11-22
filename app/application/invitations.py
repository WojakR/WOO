"""Invitation to a meeting of the evaluation (KPRM use cases: "(opcjonalnie) zaproszenie na rozmowę").

Two meetings: the opening one, where the criteria are set (rozmowa rozpoczynająca, § 7), and the review meeting
(rozmowa oceniająca, § 10). The evaluator (or the deputy) sends the invitation; the evaluated person gets a notice
in the app and – by the e-mail job – an e-mail with an .ics file, which every calendar (Outlook, Thunderbird,
Google) opens as a meeting request. Moving the meeting sends the same event again (same UID, next SEQUENCE), so the
calendar updates it instead of adding a second one; cancelling sends METHOD:CANCEL.

Pure Python: the .ics text is built here (RFC 5545), with the office time zone written out (Europe/Warsaw).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.domain.cycle import EvaluationCycle, Status
from app.domain.errors import InvalidTransition, ValidationError

KINDS = {
    "ROZMOWA_KRYTERIA": ("rozmowa rozpoczynająca – wyznaczenie kryteriów oceny",
                         frozenset({Status.CYCLE_STARTED, Status.CRITERIA_SET})),
    "ROZMOWA_OCENIAJACA": ("rozmowa oceniająca", frozenset({Status.CRITERIA_CONFIRMED, Status.MEETING_HELD})),
}
MIN_MINUTES, MAX_MINUTES = 15, 240
UID_DOMAIN = "ocena-okresowa.local"


@dataclass(frozen=True)
class Invitation:
    id: int
    cycle_id: str
    kind: str  # ROZMOWA_KRYTERIA | ROZMOWA_OCENIAJACA
    start: datetime  # office local time (Europe/Warsaw), naive
    minutes: int
    place: str
    note: str
    organizer_id: str  # the evaluator (or the deputy who sent it)
    attendee_id: str  # the evaluated person
    sent_at: datetime  # UTC, naive
    sequence: int = 0  # 0 = first invitation; +1 every time the meeting is moved
    cancelled: bool = False

    @property
    def uid(self) -> str:
        return f"ocena-{self.cycle_id}-{self.kind.lower()}@{UID_DOMAIN}"

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)

    @property
    def title(self) -> str:
        return KINDS[self.kind][0][0].upper() + KINDS[self.kind][0][1:]


def check(c: EvaluationCycle, kind: str, start: datetime, minutes: int, place: str, now: datetime) -> None:
    """Raises when the invitation cannot be sent: unknown kind, wrong stage, past date, odd length, no place."""
    if kind not in KINDS:
        raise ValidationError([f"Nieznany rodzaj rozmowy „{kind}” (ROZMOWA_KRYTERIA albo ROZMOWA_OCENIAJACA)."])
    label, stages = KINDS[kind]
    if c.status not in stages:
        raise InvalidTransition(f"Zaproszenie na {label} można wysłać tylko na tym etapie oceny.")
    problems = []
    if start <= now:
        problems.append("Termin rozmowy musi być w przyszłości.")
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        problems.append(f"Czas rozmowy: od {MIN_MINUTES} do {MAX_MINUTES} minut.")
    if not place.strip():
        problems.append("Podaj miejsce rozmowy (pokój albo link do spotkania).")
    if problems:
        raise ValidationError(problems)


def next_version(previous: Invitation | None, new: Invitation) -> Invitation:
    """A new invitation to the same meeting replaces the previous one in the calendar (same UID)."""
    if previous is None or previous.cancelled:
        return new
    return replace(new, sequence=previous.sequence + 1)


# ---------------------------------------------------------------- iCalendar (RFC 5545)

_VTIMEZONE = (
    "BEGIN:VTIMEZONE", "TZID:Europe/Warsaw",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST", "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET", "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD",
    "END:VTIMEZONE",
)


def _text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _param(value: str) -> str:
    return '"' + value.replace('"', "'") + '"'


def _fold(line: str) -> str:
    """Lines longer than 75 octets are folded (CRLF + space), never inside a UTF-8 character."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def _local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def to_ics(inv: Invitation, organizer: tuple[str, str | None], attendee: tuple[str, str | None],
           description: str = "") -> str:
    """organizer / attendee = (full name, e-mail or None)."""
    method = "CANCEL" if inv.cancelled else "REQUEST"

    def person(prop: str, who: tuple[str, str | None], extra: str = "") -> str:
        name, mail = who
        return f"{prop};CN={_param(name)}{extra}:mailto:{mail or 'brak-adresu@' + UID_DOMAIN}"

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cyfrowy Asystent Ocen Okresowych//PL", "CALSCALE:GREGORIAN",
        f"METHOD:{method}", *_VTIMEZONE,
        "BEGIN:VEVENT", f"UID:{inv.uid}", f"SEQUENCE:{inv.sequence}",
        f"DTSTAMP:{inv.sent_at:%Y%m%dT%H%M%S}Z",
        f"DTSTART;TZID=Europe/Warsaw:{_local(inv.start)}", f"DTEND;TZID=Europe/Warsaw:{_local(inv.end)}",
        f"SUMMARY:{_text('Ocena okresowa: ' + inv.title)}", f"LOCATION:{_text(inv.place)}",
        f"DESCRIPTION:{_text(description)}" if description else None,
        person("ORGANIZER", organizer),
        person("ATTENDEE", attendee, ";ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE"),
        f"STATUS:{'CANCELLED' if inv.cancelled else 'CONFIRMED'}", "TRANSP:OPAQUE",
        *(() if inv.cancelled else ("BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT1H",
                                    f"DESCRIPTION:{_text(inv.title)}", "END:VALARM")),
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(x) for x in lines if x is not None) + "\r\n"


def message(inv: Invitation, organizer_name: str, attendee_name: str) -> tuple[str, str]:
    """(subject, text) of the notice."""
    when = f"{inv.start:%d.%m.%Y}, godz. {inv.start:%H:%M}–{inv.end:%H:%M}"
    if inv.cancelled:
        return (f"Odwołana: {inv.title}",
                f"{organizer_name} odwołał(a) spotkanie „{inv.title}” zaplanowane na {when} ({inv.place}).")
    moved = " (zmiana terminu)" if inv.sequence else ""
    note = f" {inv.note.strip()}" if inv.note.strip() else ""
    return (f"Zaproszenie{moved}: {inv.title} – {when}",
            f"Zaproszenie na spotkanie „{inv.title}”{moved}: {when}, miejsce: {inv.place}. Zaprasza: "
            f"{organizer_name}, uczestnik: {attendee_name}.{note} Plik .ics w załączniku dodaje spotkanie do "
            "kalendarza.")
