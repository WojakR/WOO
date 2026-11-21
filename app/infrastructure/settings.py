"""Office settings (decisions of the office, editable by its administrator) – kept apart from the rules of law
in server/data/kprm/reguly.json. Read from config/ustawienia_urzedu.json (or the file in USTAWIENIA_URZEDU)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from app.domain.access import VisibilityScope
from app.domain.errors import ValidationError
from app.domain.reminder_schedule import ReminderRule, ReminderSchedule, RuleKind, Stage, WorkingHours

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "ustawienia_urzedu.json"

DEFAULT_SCHEDULE = ReminderSchedule(
    rules={
        Stage.CRITERIA: (ReminderRule(RuleKind.EVERY_DAYS, 7),),
        Stage.PERIOD: (ReminderRule(RuleKind.PERCENT, 50), ReminderRule(RuleKind.PERCENT, 75),
                       ReminderRule(RuleKind.MONTHS_BEFORE, 2), ReminderRule(RuleKind.WEEKS_BEFORE, 2)),
        Stage.ACKNOWLEDGEMENT: (ReminderRule(RuleKind.EVERY_DAYS, 3),),
    },
    at=time(11, 0),
)


def parse_time(text: str, what: str) -> time:
    try:
        return time.fromisoformat(text)
    except (TypeError, ValueError):
        raise ValidationError([f"{what}: nieprawidłowa godzina „{text}” (format GG:MM)."]) from None


def parse_schedule(raw: dict, base: ReminderSchedule) -> ReminderSchedule:
    """`raw`: {"godzina": "11:00", "etapy": {"OKRES_OCENY": [{"rodzaj": "PROCENT_OKRESU", "wartosc": 50}], …}}.
    Stages not given keep `base` – so a user may change only one stage."""
    rules = dict(base.rules)
    problems = []
    for stage_name, items in (raw.get("etapy") or {}).items():
        try:
            stage = Stage(stage_name)
        except ValueError:
            problems.append(f"Nieznany etap „{stage_name}” (dozwolone: {', '.join(s.value for s in Stage)}).")
            continue
        parsed = []
        for it in items or []:
            try:
                parsed.append(ReminderRule(RuleKind(it["rodzaj"]), int(it["wartosc"])))
            except (KeyError, TypeError, ValueError):
                problems.append(f"Etap {stage_name}: nieprawidłowe przypomnienie {it!r} "
                                f"(rodzaje: {', '.join(k.value for k in RuleKind)}).")
        rules[stage] = tuple(parsed)
    if problems:
        raise ValidationError(problems)
    at = parse_time(raw["godzina"], "Godzina przypomnień") if raw.get("godzina") else base.at
    return ReminderSchedule(rules=rules, at=at)


@dataclass(frozen=True)
class OfficeSettings:
    visibility_scope: VisibilityScope = VisibilityScope.SUBTREE
    working_hours: WorkingHours = field(default_factory=WorkingHours)
    reminders: ReminderSchedule = DEFAULT_SCHEDULE

    @classmethod
    def from_dict(cls, raw: dict) -> OfficeSettings:
        scope = raw.get("zakres_widocznosci", VisibilityScope.SUBTREE.value)
        try:
            visibility = VisibilityScope(scope)
        except ValueError:
            allowed = ", ".join(v.value for v in VisibilityScope)
            raise ValidationError([f"Ustawienia urzędu: nieznany zakres_widocznosci „{scope}” (dozwolone: {allowed})."]) from None
        rem = raw.get("przypomnienia") or {}
        hours_raw = rem.get("godziny_pracy") or {}
        hours = WorkingHours(parse_time(hours_raw.get("od", "08:00"), "Godziny pracy"),
                             parse_time(hours_raw.get("do", "16:00"), "Godziny pracy"))
        schedule = parse_schedule(rem, DEFAULT_SCHEDULE).validated(hours)
        return cls(visibility_scope=visibility, working_hours=hours, reminders=schedule)


def load_office_settings(path: str | Path | None = None) -> OfficeSettings:
    p = Path(path or os.getenv("USTAWIENIA_URZEDU") or DEFAULT_PATH)
    if not p.exists():
        return OfficeSettings()
    return OfficeSettings.from_dict(json.loads(p.read_text(encoding="utf-8")))
