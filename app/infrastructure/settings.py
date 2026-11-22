"""Office settings (decisions of the office, editable by its administrator) – kept apart from the rules of law
in server/data/kprm/reguly.json. Read from config/ustawienia_urzedu.json (or the file in USTAWIENIA_URZEDU)."""
from __future__ import annotations

import json
import os
import dataclasses
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from app.domain.access import VisibilityScope
from app.domain.errors import ValidationError
from app.domain.objection import HeadMode, ObjectionPolicy, Route
from app.domain.reminder_schedule import ReminderRule, ReminderSchedule, RuleKind, Stage, WorkingHours

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "ustawienia_urzedu.json"

DEFAULT_SCHEDULE = ReminderSchedule(
    rules={
        Stage.CRITERIA: (ReminderRule(RuleKind.EVERY_DAYS, 7),),
        Stage.PERIOD: (ReminderRule(RuleKind.PERCENT, 50), ReminderRule(RuleKind.PERCENT, 75),
                       ReminderRule(RuleKind.MONTHS_BEFORE, 2), ReminderRule(RuleKind.WEEKS_BEFORE, 2)),
        Stage.ACKNOWLEDGEMENT: (ReminderRule(RuleKind.EVERY_DAYS, 3),),
        Stage.OBJECTION_REVIEW: (ReminderRule(RuleKind.DAYS_BEFORE, 7), ReminderRule(RuleKind.DAYS_BEFORE, 2)),
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
    # who decides objections (art. 83 ust. 1: the director general); "kadry" = the HR/administrator identity
    objection_reviewer: str = "kadry"
    # art. 81 ust. 8: OCENIAJACY = the evaluator's decision applies at once; KADRY = HR approves it first
    deadline_change_approver: str = "OCENIAJACY"
    deadline_days_after_return: int = 14  # proposed new deadline after an absence
    objection: ObjectionPolicy = field(default_factory=ObjectionPolicy)  # edge cases (app/domain/objection.py)
    # wellbeing checklist: this many "często" answers raise the HR partner's overload signal
    wellbeing_often_threshold: int = 3
    # working-time (RCP) indicators: window and thresholds (app/domain/worktime_signals.py)
    rcp: dict = field(default_factory=dict)
    # reports: groups smaller than this are hidden (no identifying individuals)
    report_min_group: int = 5
    # training needs: a partial score below this counts as a need
    training_score_below: int = 5
    # archive: retention periods (app/application/archive.py)
    archive: dict = field(default_factory=dict)
    # personalised conversation prep / development from the person's history (app/domain/career_profile.py)
    employee_profile: dict = field(default_factory=dict)

    def with_objection_route(self, route: Route) -> OfficeSettings:
        return dataclasses.replace(self, objection=dataclasses.replace(self.objection, route=route))

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
        objection_raw = raw.get("sprzeciw") or {}
        reviewer = str(objection_raw.get("rozpatruje") or "kadry").strip()
        head = objection_raw.get("gdy_oceniany_jest_kierownikiem_urzedu") or {}
        try:
            mode = HeadMode(head.get("tryb", HeadMode.SUPERIOR_BODY.value))
        except ValueError:
            raise ValidationError([f"Ustawienia urzędu: nieznany tryb sprzeciwu kierownika urzędu „{head.get('tryb')}” "
                                   f"(dozwolone: {', '.join(m.value for m in HeadMode)})."]) from None
        try:
            route = Route(objection_raw.get("tryb", Route.DIRECTOR_GENERAL.value))
        except ValueError:
            raise ValidationError([f"Ustawienia urzędu: nieznany sprzeciw.tryb „{objection_raw.get('tryb')}” "
                                   f"(dozwolone: {', '.join(r.value for r in Route)})."]) from None
        objection = ObjectionPolicy(reviewer, bool(objection_raw.get("urzad_ma_dyrektora_generalnego", True)), mode,
                                    str(head.get("rozpatruje") or reviewer), route)
        wellbeing = raw.get("dobrostan") or {}
        reports = raw.get("raporty") or {}
        training = raw.get("szkolenia") or {}
        dc = raw.get("zmiana_terminu") or {}
        approver = str(dc.get("zatwierdza") or "OCENIAJACY").upper()
        if approver not in ("OCENIAJACY", "KADRY"):
            raise ValidationError([f"Ustawienia urzędu: zmiana_terminu.zatwierdza „{approver}” – dozwolone OCENIAJACY, KADRY."])
        return cls(visibility_scope=visibility, working_hours=hours, reminders=schedule, objection_reviewer=reviewer,
                   deadline_change_approver=approver,
                   deadline_days_after_return=int(dc.get("propozycja_dni_po_powrocie", 14)),
                   objection=objection, wellbeing_often_threshold=int(wellbeing.get("prog_odpowiedzi_czesto", 3)),
                   rcp=dict(raw.get("rcp") or {}), report_min_group=int(reports.get("minimalna_grupa", 5)),
                   training_score_below=int(training.get("ocena_czastkowa_ponizej", 5)),
                   archive=dict(raw.get("archiwum") or {}),
                   employee_profile=dict(raw.get("profil_pracownika") or {}))


def load_office_settings(path: str | Path | None = None) -> OfficeSettings:
    p = Path(path or os.getenv("USTAWIENIA_URZEDU") or DEFAULT_PATH)
    if not p.exists():
        return OfficeSettings()
    return OfficeSettings.from_dict(json.loads(p.read_text(encoding="utf-8")))
