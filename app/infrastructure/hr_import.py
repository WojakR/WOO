"""Import of employees from the HR system (CSV / XLSX export) – with a report per row and a preview mode.

Columns (header row; Polish names, case and spaces ignored):
  id, imie, nazwisko, urzad, komorka, stanowisko, opis_stanowiska, id_przelozonego, arkusz,
  urzednik_mianowany, stopien_sluzbowy, kieruje_zespolem, kierownik_urzedu, email,
  data_zatrudnienia, data_zakonczenia_zatrudnienia, data_ostatniej_oceny, data_przyznania_stopnia
Required: id, imie, nazwisko, stanowisko. `id_przelozonego` = who evaluates the person (empty = nobody, e.g. the
head of the office). Rows update people with the same id; people not in the file stay as they are.

Checks: missing columns / values, duplicate id, unknown supervisor (neither in the file nor in the directory),
a cycle in the supervisor structure, values out of range (stopień 1–9, arkusz A/B/C, dates).
A file with any error imports nothing (the report says what to fix).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime

from app.domain.cycle import PreviousEvaluation
from app.domain.employee import Employee
from backend.parsers import parse_table

REQUIRED = ("id", "imie", "nazwisko", "stanowisko")
COLUMNS = REQUIRED + ("urzad", "komorka", "opis_stanowiska", "id_przelozonego", "arkusz", "urzednik_mianowany",
                      "stopien_sluzbowy", "kieruje_zespolem", "kierownik_urzedu", "email", "data_zatrudnienia",
                      "data_zakonczenia_zatrudnienia", "data_ostatniej_oceny", "data_przyznania_stopnia")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TRUE = {"tak", "t", "1", "true", "prawda", "x", "y", "yes"}
_FALSE = {"nie", "n", "0", "false", "falsz", "fałsz", "no", ""}


@dataclass
class RowProblem:
    row: int  # 1 = first data row (the header is row 0)
    employee_id: str | None
    message: str


@dataclass
class ImportReport:
    employees: list[Employee] = field(default_factory=list)  # valid rows, as they would be saved
    problems: list[RowProblem] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _norm(col: str) -> str:
    c = str(col).strip().lower().replace(" ", "_").replace("-", "_")
    return c.translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))


def _cell(raw: dict, key: str) -> str:
    v = raw.get(key)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _bool(text: str) -> bool | None:
    t = text.lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    raise ValueError(f"„{text}” – oczekiwano TAK / NIE")


def _date(text: str) -> date | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"„{text}” – oczekiwano daty RRRR-MM-DD lub DD.MM.RRRR")


def _sheet(text: str, head: bool | None, manages: bool | None) -> str:
    if text:
        if text.upper() not in ("A", "B", "C"):
            raise ValueError(f"arkusz „{text}” – dozwolone A, B, C")
        return text.upper()
    return "A" if head else "B" if manages else "C"


def _row_employee(raw: dict, existing: Employee | None) -> Employee:
    """One row -> Employee; raises ValueError with a Polish message per bad field (joined by '; ')."""
    errors: list[str] = []

    def get(key: str, conv=lambda x: x, label: str | None = None):
        try:
            return conv(_cell(raw, key))
        except ValueError as e:
            errors.append(f"{label or key}: {e}")
            return None

    for k in REQUIRED:
        if not _cell(raw, k):
            errors.append(f"brak wartości w kolumnie „{k}”")
    civil = get("urzednik_mianowany", lambda t: bool(_bool(t)))
    grade_text = _cell(raw, "stopien_sluzbowy")
    grade = None
    if grade_text:
        try:
            grade = int(grade_text)
            if not 1 <= grade <= 9:
                raise ValueError
        except ValueError:
            errors.append(f"stopien_sluzbowy: „{grade_text}” – liczba 1–9")
            grade = None
    if grade is not None and civil is False:
        errors.append("stopien_sluzbowy: stopień służbowy ma tylko urzędnik służby cywilnej")
    manages = get("kieruje_zespolem", lambda t: _bool(t) if t else None)
    head = get("kierownik_urzedu", lambda t: _bool(t) if t else None)
    email = _cell(raw, "email") or None
    if email and not _EMAIL.match(email):
        errors.append(f"email: „{email}” – nieprawidłowy adres")
    start = get("data_zatrudnienia", _date)
    end = get("data_zakonczenia_zatrudnienia", _date)
    last = get("data_ostatniej_oceny", _date)
    grade_since = get("data_przyznania_stopnia", _date)
    if start and end and end < start:
        errors.append("data_zakonczenia_zatrudnienia przed datą zatrudnienia")
    sheet = get("arkusz", lambda t: _sheet(t, head, manages))
    if errors:
        raise ValueError("; ".join(errors))
    prev = existing.previous_evaluation if existing else None
    if last and (prev is None or prev.date != last):
        prev = PreviousEvaluation(outcome=prev.outcome if prev else None, level=prev.level if prev else None,
                                  date=last)
    base = existing or Employee(id="", first_name="", last_name="", office="", unit="", position="", sheet="C")
    return replace(
        base, id=_cell(raw, "id"), first_name=_cell(raw, "imie"), last_name=_cell(raw, "nazwisko"),
        office=_cell(raw, "urzad") or base.office, unit=_cell(raw, "komorka") or base.unit,
        position=_cell(raw, "stanowisko"), position_description=_cell(raw, "opis_stanowiska"),
        sheet=sheet, evaluator_id=_cell(raw, "id_przelozonego") or None, previous_evaluation=prev,
        civil_servant=bool(civil), grade=grade, grade_since=grade_since, manages_people=manages, is_office_head=head, email=email,
        employment_start=start, employment_end=end,
    )


def _cycle_in(evaluator_of: dict[str, str | None], start: str) -> list[str] | None:
    seen: list[str] = []
    cur: str | None = start
    while cur is not None:
        if cur in seen:
            return seen[seen.index(cur):] + [cur]
        seen.append(cur)
        cur = evaluator_of.get(cur)
    return None


def build_report(rows: list[dict], current: dict[str, Employee]) -> ImportReport:
    rep = ImportReport()
    seen: dict[str, int] = {}
    valid: list[tuple[int, Employee]] = []
    for n, raw in enumerate(rows, start=1):
        eid = _cell(raw, "id") or None
        if eid and eid in seen:
            rep.problems.append(RowProblem(n, eid, f"duplikat identyfikatora (pierwszy raz w wierszu {seen[eid]})"))
            continue
        if eid:
            seen[eid] = n
        try:
            valid.append((n, _row_employee(raw, current.get(eid) if eid else None)))
        except ValueError as e:
            rep.problems.append(RowProblem(n, eid, str(e)))
    merged = dict(current) | {e.id: e for _, e in valid}
    for n, e in valid:
        if e.evaluator_id and e.evaluator_id not in merged:
            rep.problems.append(RowProblem(n, e.id, f"nieznany przełożony „{e.evaluator_id}”"))
        elif e.evaluator_id == e.id:
            rep.problems.append(RowProblem(n, e.id, "pracownik nie może być swoim przełożonym"))
    evaluator_of = {k: v.evaluator_id for k, v in merged.items()}
    reported: set[frozenset] = set()
    for n, e in valid:
        loop = _cycle_in(evaluator_of, e.id)
        if loop and frozenset(loop) not in reported and len(loop) > 2:
            reported.add(frozenset(loop))
            rep.problems.append(RowProblem(n, e.id, "cykl w strukturze podległości: " + " → ".join(loop)))
    rep.employees = [e for _, e in valid]
    rep.added = [e.id for e in rep.employees if e.id not in current]
    rep.updated = [e.id for e in rep.employees if e.id in current]
    return rep


def read_rows(data: bytes, filename: str) -> list[dict]:
    """CSV / XLSX -> list of row dicts with normalised column names. Raises ValueError for a bad file."""
    try:
        df = parse_table(data, filename)
    except Exception as e:  # noqa: BLE001 – any parser error is "bad file" for the user
        raise ValueError(f"Nie udało się odczytać pliku: {e}") from e
    df = df.rename(columns={c: _norm(c) for c in df.columns}).astype(object)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("Brak wymaganych kolumn: " + ", ".join(missing))
    return df.to_dict(orient="records")
