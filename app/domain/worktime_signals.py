"""Working-time indicators from the time-recording system (RCP) – spec points 3 and 4: regular overtime,
skipped breaks, activity after hours. Pure functions over days in a window; thresholds are office settings
(config/ustawienia_urzedu.json "rcp"). Only aggregates leave this module – never the raw hours.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Mapping


@dataclass(frozen=True)
class WorkDay:
    employee_id: str
    day: date
    start: time
    end: time
    break_minutes: int = 0
    after_hours: bool = False  # e-mail / system activity after working hours that day

    @property
    def worked_minutes(self) -> int:
        span = datetime.combine(self.day, self.end) - datetime.combine(self.day, self.start)
        return max(0, int(span.total_seconds() // 60) - self.break_minutes)


@dataclass(frozen=True)
class WorkTimeIndicators:
    window_from: date
    window_to: date
    days: int
    overtime_days: int
    short_break_days: int
    average_break: float | None
    after_hours_days: int


DEFAULTS = {"okno_tygodni": 8, "norma_godzin_dziennie": 8, "nadgodziny_od_minut": 30, "prog_dni_z_nadgodzinami": 10,
            "minimalna_przerwa_minut": 15, "prog_dni_bez_przerwy": 10, "prog_dni_aktywnosci_po_godzinach": 5}


def _cfg(cfg: Mapping) -> dict:
    return {**DEFAULTS, **{k: v for k, v in cfg.items() if not k.startswith("_")}}


def indicators(days: Iterable[WorkDay], today: date, cfg: Mapping) -> WorkTimeIndicators:
    c = _cfg(cfg)
    start = today - timedelta(weeks=int(c["okno_tygodni"]))
    window = [d for d in days if start < d.day <= today]
    norm = int(c["norma_godzin_dziennie"]) * 60 + int(c["nadgodziny_od_minut"])
    breaks = [d.break_minutes for d in window]
    return WorkTimeIndicators(
        window_from=start + timedelta(days=1), window_to=today, days=len(window),
        overtime_days=sum(1 for d in window if d.worked_minutes > norm),
        short_break_days=sum(1 for d in window if d.break_minutes < int(c["minimalna_przerwa_minut"])),
        average_break=round(sum(breaks) / len(breaks), 1) if breaks else None,
        after_hours_days=sum(1 for d in window if d.after_hours),
    )


def overload_evidence(ind: WorkTimeIndicators, cfg: Mapping) -> list[str]:
    """Aggregated evidence for the HR partner's PRZECIAZENIE signal; empty below every threshold."""
    c = _cfg(cfg)
    if ind.days == 0:
        return []
    found = []
    if ind.overtime_days >= int(c["prog_dni_z_nadgodzinami"]):
        found.append(f"{ind.overtime_days} dni z nadgodzinami")
    if ind.short_break_days >= int(c["prog_dni_bez_przerwy"]):
        found.append(f"{ind.short_break_days} dni z przerwą krótszą niż {c['minimalna_przerwa_minut']} min"
                     + (f" (średnio {ind.average_break:g} min)" if ind.average_break is not None else ""))
    if ind.after_hours_days >= int(c["prog_dni_aktywnosci_po_godzinach"]):
        found.append(f"{ind.after_hours_days} dni z aktywnością po godzinach pracy")
    if not found:
        return []
    return [f"RCP, ostatnie {c['okno_tygodni']} tyg. ({ind.days} dni pracy): " + "; ".join(found)]
