"""Import of working-time records (RCP) from CSV / XLSX, parsed by backend.parsers.

Columns (header row, case-insensitive): id_pracownika, data (RRRR-MM-DD or DD.MM.RRRR), wejscie (GG:MM),
wyjscie (GG:MM), przerwy_min; optional: aktywnosc_po_godzinach (tak/nie, 1/0). Bad rows are reported with their
line number and skipped – the good ones are imported. A later import of the same person and day replaces it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Iterable, Mapping

from app.domain.worktime_signals import WorkDay

REQUIRED = ("id_pracownika", "data", "wejscie", "wyjscie", "przerwy_min")
OPTIONAL = ("aktywnosc_po_godzinach",)
_TRUE, _FALSE = {"tak", "t", "1", "true", "yes", "x"}, {"nie", "n", "0", "false", "no", ""}


@dataclass(frozen=True)
class RowError:
    line: int  # line in the file (1 = header)
    message: str


@dataclass(frozen=True)
class ImportResult:
    days: list[WorkDay]
    errors: list[RowError]


def _date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    text = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"nieprawidłowa data „{v}”")


def _time(v) -> time:
    if isinstance(v, time):
        return v
    text = str(v).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"nieprawidłowa godzina „{v}”")


def _flag(v) -> bool:
    text = "" if v is None else str(v).strip().casefold()
    if text in ("nan", "none"):
        text = ""
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"aktywnosc_po_godzinach: „{v}” (dozwolone: tak/nie)")


def import_rows(rows: Iterable[Mapping], resolve_employee: Callable[[str], str | None]) -> ImportResult:
    """`resolve_employee`: id from the file -> employee id in the directory (None = unknown person)."""
    days: dict[tuple[str, date], WorkDay] = {}
    errors: list[RowError] = []
    rows = list(rows)
    if rows:
        cols = {str(k).strip().casefold() for k in rows[0]}
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            return ImportResult([], [RowError(1, f"Brak kolumn: {', '.join(missing)}.")])
    for i, raw in enumerate(rows, start=2):
        r = {str(k).strip().casefold(): v for k, v in raw.items()}
        try:
            emp = resolve_employee(str(r["id_pracownika"]).strip())
            if emp is None:
                raise ValueError(f"nieznany pracownik „{r['id_pracownika']}”")
            start, end = _time(r["wejscie"]), _time(r["wyjscie"])
            if end <= start:
                raise ValueError("wyjście nie później niż wejście")
            breaks = int(float(r["przerwy_min"]))
            if breaks < 0:
                raise ValueError("ujemne przerwy")
            day = WorkDay(emp, _date(r["data"]), start, end, breaks, _flag(r.get("aktywnosc_po_godzinach")))
        except (ValueError, TypeError, KeyError) as e:
            errors.append(RowError(i, str(e)))
            continue
        days[(day.employee_id, day.day)] = day
    return ImportResult(list(days.values()), errors)


def import_file(data: bytes, filename: str, resolve_employee: Callable[[str], str | None]) -> ImportResult:
    from backend.parsers import parse_file

    try:
        kind, content = parse_file(data, filename)
    except Exception as e:  # noqa: BLE001 – a broken file is a user error, not a crash
        return ImportResult([], [RowError(1, f"Nie udało się odczytać pliku: {e}")])
    if kind != "table":
        return ImportResult([], [RowError(1, "Plik RCP musi być w formacie CSV albo XLSX.")])
    content = content.astype(object).where(content.notna(), None)
    return import_rows(content.to_dict("records"), resolve_employee)


class InMemoryWorkTimeStore:
    """WorkTimeSource (app/application/ports.py) kept in the application state."""

    def __init__(self, days: Iterable[WorkDay] = ()):
        self._days: dict[tuple[str, date], WorkDay] = {(d.employee_id, d.day): d for d in days}

    def add(self, days: Iterable[WorkDay]) -> None:
        for d in days:
            self._days[(d.employee_id, d.day)] = d

    def days_for(self, employee_id: str, start: date, end: date) -> list[WorkDay]:
        return sorted((d for (e, day), d in self._days.items() if e == employee_id and start <= day <= end),
                      key=lambda d: d.day)

    def all(self) -> list[WorkDay]:
        return list(self._days.values())
