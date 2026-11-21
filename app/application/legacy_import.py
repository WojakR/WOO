"""Import of old evaluations from the KPRM sheet A/B/C (spec, point 4, optional).

Rules on the structure of the form first (the text from a PDF – backend/parsers.py – or a text export):
employee and evaluator, dates, criteria with partial scores, the declared average, the marked level and outcome,
justification and IPRZ. Then the § 11 rules (app/domain/scoring.py) check what was declared and list every
discrepancy. HR corrects the fields on the verification screen and approves; the evaluation joins the person's
history as a finished cycle marked "imported", with the original file.

Partial scores: an "X" right after the criterion is 1 point; a full row (5 columns) gives the column; otherwise
the score is taken from the justification ("… (ocena: powyżej oczekiwań)") or left for HR to fill in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from fractions import Fraction
from typing import Callable, Iterable

from app.domain.cycle import EvaluationCycle, Status
from app.domain.employee import Employee
from app.domain.rulebook import RuleBook
from app.domain.scoring import EvaluationResult, Outcome, compute_result, level_for_average

DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
TOLERANCE = Fraction(1, 20)  # declared averages are rounded (6,3 for 6,33…); ±0,05 is the same average


@dataclass
class LegacySheet:
    sheet: str | None = None
    office: str = ""
    employee_name: tuple[str, str] = ("", "")
    employee_id: str | None = None
    evaluator_name: tuple[str, str] = ("", "")
    evaluator_id: str | None = None
    meeting_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    scores: dict[str, int | None] = field(default_factory=dict)  # criterion id -> points (None = not read)
    declared_average: Fraction | None = None
    level: str | None = None
    outcome: str | None = None  # "pozytywna" | "negatywna"
    evaluated_on: date | None = None
    acknowledged_on: date | None = None
    justification: str = ""
    iprz: str = ""
    notes: list[str] = field(default_factory=list)  # what the parser assumed


@dataclass(frozen=True)
class Problem:
    code: str
    severity: str  # BLAD (blocks the approval) | OSTRZEZENIE
    message: str


# ---------------------------------------------------------------- parsing

def _date(text: str) -> date | None:
    m = DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().lstrip("|").split("|")]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" .:)")


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"\w+", text.casefold()) if len(w) > 2}


def _criterion_by_text(text: str, rules: RuleBook) -> str | None:
    """Inflected criterion names in the justification ("organizacji pracy …") – the best match of word stems."""
    words = _stems(text)
    best, score = None, 0
    for c in rules.criteria.values():
        name = _stems(c.name)
        hits = len(words & name)
        if hits > score or (hits == score and best and len(name) < len(_stems(rules.criteria[best].name))):
            best, score = c.id, hits
    return best if score else None


def parse_sheet(text: str, rules: RuleBook) -> LegacySheet:
    lines = text.replace("\r\n", "\n").split("\n")
    s = LegacySheet()
    by_name = {_norm(c.name): c.id for c in rules.criteria.values()}
    levels = {_norm(lv): lv for lv in rules.scale.values()}
    points_of = {lv: p for p, lv in rules.scale.items()}
    scale = sorted(rules.scale)

    if m := re.search(r"ARKUSZ\s+([ABC])\b", text):
        s.sheet = m.group(1)
    names: list[tuple[str, str]] = []
    first: str | None = None
    for line in lines:
        cells = _cells(line) if line.startswith("|") else []
        if len(cells) >= 2 and cells[0].upper() == "NAZWA URZĘDU" and not s.office:
            s.office = cells[1]
        if len(cells) >= 2 and cells[0] == "Imię":
            first = cells[1]
        elif len(cells) >= 2 and cells[0] == "Nazwisko" and first is not None:
            names.append((first, cells[1]))
            first = None
    if names:
        s.employee_name = names[0]
    if len(names) > 1:
        s.evaluator_name = names[1]

    meeting = next((i for i, l in enumerate(lines) if "DATA PRZEPROWADZENIA ROZMOWY" in l), None)
    average_at = next((i for i, l in enumerate(lines) if l.startswith("| Średnia arytmetyczna")), None)
    if meeting is not None:
        s.meeting_date = _date(" ".join(lines[meeting:meeting + 2]))
        period = next((l for l in lines[meeting:meeting + 4] if "OD):" in l), "")
        if period:
            parts = period.split("DO):")
            s.period_from, s.period_to = _date(parts[0]), _date(parts[1]) if len(parts) > 1 else None

    # partial scores: the score matrix between the meeting date and the average
    if meeting is not None and average_at is not None:
        for line in lines[meeting:average_at]:
            if not line.startswith("|"):
                continue
            cells = _cells(line)
            cid = by_name.get(_norm(cells[0]))
            if cid is None:
                continue
            marks = [i for i, c in enumerate(cells[1:]) if c.strip().casefold() == "x"]
            pts = None
            if marks and len(cells) - 1 >= len(scale):
                pts = scale[marks[0]]
            elif marks and marks[0] == 0:
                pts = scale[0]
            s.scores[cid] = pts
    if average_at is not None:
        cells = _cells(lines[average_at])
        raw = cells[1].replace(",", ".") if len(cells) > 1 else ""
        if re.fullmatch(r"\d+(\.\d+)?", raw):
            s.declared_average = Fraction(raw)
        for line in lines[average_at + 1:average_at + 12]:
            cells = _cells(line)
            if len(cells) >= 3 and cells[0].casefold() == "x" and _norm(cells[2]) in levels:
                s.level = levels[_norm(cells[2])]
                break

    outcome_at = next((i for i, l in enumerate(lines) if "POZYTYWNA)" in l and "NEGATYWNA)" in l), None)
    if outcome_at is not None:
        after_pos = lines[outcome_at].split("POZYTYWNA)")[1]
        pos_mark, neg_mark = after_pos.split("NEGATYWNA)")
        if pos_mark.strip(" |").casefold() == "x":
            s.outcome = Outcome.POSITIVE.value
        elif neg_mark.strip(" |").casefold() == "x":
            s.outcome = Outcome.NEGATIVE.value
        # justification = the first table block after the outcome, IPRZ = the second one
        blocks: list[list[str]] = []
        for line in lines[outcome_at + 1:]:
            if line.startswith("| Ocena)") or line.startswith("| TAK"):
                break
            if line.startswith("|"):
                blocks.append([line.lstrip("| ").strip()])
            elif blocks and line.strip():
                blocks[-1].append(line.strip())
        if blocks:
            s.justification = "\n".join(blocks[0]).strip()
        if len(blocks) > 1:
            s.iprz = "\n".join(x for b in blocks[1:] for x in b).strip()

    # scores the matrix did not give: "(ocena: <level>)" after the criterion in the justification
    for line in s.justification.split("\n"):
        for m in re.finditer(r"([^.;()]*?)\(ocena:\s*([^)]+)\)", line):
            cid = _criterion_by_text(m.group(1), rules)
            lv = levels.get(_norm(m.group(2)))
            if cid and lv and s.scores.get(cid) is None:
                s.scores[cid] = points_of[lv]
                s.notes.append(f"Ocena cząstkowa „{rules.criterion_name(cid)}” odczytana z uzasadnienia ({lv}).")

    # dates of drawing up (evaluator's signature in part II) and of the acknowledgement
    ack_at = next((i for i, l in enumerate(lines) if "Przeprowadzono ze mną rozmowę oceniającą" in l), None)
    if ack_at is not None:
        start = outcome_at or 0
        for line in lines[start:ack_at]:
            if line.startswith("|") and "podpis" in line.casefold() and (d := _date(line)):
                s.evaluated_on = d
        s.acknowledged_on = next((d for line in lines[ack_at + 1:ack_at + 3] if (d := _date(line))), None)
    if s.evaluated_on is None and s.meeting_date:
        s.evaluated_on = s.meeting_date
        s.notes.append("Brak daty sporządzenia oceny – przyjęto datę rozmowy oceniającej.")
    return s


def match_people(s: LegacySheet, people: Iterable[Employee]) -> LegacySheet:
    """Employee and evaluator by first and last name (unique match only)."""
    people = list(people)

    def find(name: tuple[str, str]) -> str | None:
        hits = [e.id for e in people if (e.first_name.casefold(), e.last_name.casefold())
                == (name[0].casefold(), name[1].casefold())]
        return hits[0] if len(hits) == 1 else None

    return replace(s, employee_id=s.employee_id or find(s.employee_name),
                   evaluator_id=s.evaluator_id or find(s.evaluator_name))


# ---------------------------------------------------------------- checks (§ 11)

def result_of(s: LegacySheet, rules: RuleBook) -> EvaluationResult | None:
    """Recomputed from the partial scores when all are known, else None."""
    if s.scores and all(v is not None for v in s.scores.values()):
        return compute_result(list(s.scores.values()), rules)
    return None


def check(s: LegacySheet, rules: RuleBook) -> list[Problem]:
    out: list[Problem] = []
    if not s.employee_id:
        out.append(Problem("BRAK_PRACOWNIKA", "BLAD",
                           f"Nie rozpoznano pracownika „{' '.join(s.employee_name).strip() or '?'}” – wybierz go z listy."))
    if s.sheet not in rules.sheets:
        out.append(Problem("BRAK_ARKUSZA", "BLAD", "Nie rozpoznano arkusza (A, B albo C)."))
    if s.evaluated_on is None:
        out.append(Problem("BRAK_DATY", "BLAD", "Brak daty sporządzenia oceny."))
    if s.level is None:
        out.append(Problem("BRAK_POZIOMU", "BLAD", "Nie zaznaczono ogólnego poziomu oceny."))
    if s.outcome is None:
        out.append(Problem("BRAK_WYNIKU", "BLAD", "Nie zaznaczono, czy ocena jest pozytywna, czy negatywna."))
    missing = [rules.criterion_name(c) for c, v in s.scores.items() if v is None]
    if missing:
        out.append(Problem("BRAK_OCENY_CZASTKOWEJ", "OSTRZEZENIE",
                           "Nie odczytano ocen cząstkowych: " + ", ".join(missing) + " – uzupełnij, jeśli znasz."))
    if s.sheet in rules.sheets:
        lacking = [rules.criterion_name(c) for c in rules.mandatory(s.sheet) if c not in s.scores]
        if lacking:
            out.append(Problem("BRAK_KRYTERIUM", "OSTRZEZENIE", "W arkuszu brak kryteriów obowiązkowych: "
                               + ", ".join(lacking) + "."))
    computed = result_of(s, rules)
    if s.declared_average is None and computed is None:
        out.append(Problem("BRAK_SREDNIEJ", "BLAD", "W arkuszu nie wpisano średniej, a ocen cząstkowych nie da się "
                                                    "odczytać w całości – wpisz średnią albo oceny cząstkowe."))
    if s.declared_average is not None and computed is not None and abs(computed.average - s.declared_average) > TOLERANCE:
        out.append(Problem("SREDNIA_NIEZGODNA", "BLAD",
                           f"Średnia w arkuszu ({float(s.declared_average):g}) różni się od średniej z ocen cząstkowych "
                           f"({computed.average_display:g}, § 11 ust. 1)."))
    average = s.declared_average if s.declared_average is not None else computed.average if computed else None
    if average is not None and s.level is not None:
        try:
            band = level_for_average(average, rules)
        except Exception:  # noqa: BLE001 – an average outside the scale is a discrepancy, not a crash
            band = None
        if band != s.level:
            out.append(Problem("POZIOM_NIEZGODNY", "BLAD",
                               f"Średnia {float(average):g} odpowiada poziomowi „{band or 'poza skalą'}”, a w arkuszu "
                               f"zaznaczono „{s.level}” (§ 11 ust. 1 pkt 2)."))
    if s.level is not None and s.outcome is not None:
        has_one = any(v == rules.forbidden_partial_score for v in s.scores.values())
        all_known = bool(s.scores) and all(v is not None for v in s.scores.values())
        positive_level = s.level in rules.positive_levels
        if s.outcome == Outcome.POSITIVE.value and (not positive_level or has_one):
            out.append(Problem("WYNIK_NIEZGODNY", "BLAD", "Ocena oznaczona jako pozytywna, ale "
                               + ("jest ocena cząstkowa 1 pkt" if has_one else f"poziom „{s.level}”")
                               + " oznacza ocenę negatywną (§ 11 ust. 1 pkt 3–4)."))
        if s.outcome == Outcome.NEGATIVE.value and positive_level and not has_one and all_known:
            out.append(Problem("WYNIK_NIEZGODNY", "BLAD", "Ocena oznaczona jako negatywna, ale poziom i oceny cząstkowe "
                                                         "dają ocenę pozytywną (§ 11 ust. 1 pkt 3–4)."))
    if s.outcome == Outcome.NEGATIVE.value and not s.justification.strip():
        out.append(Problem("BRAK_UZASADNIENIA", "OSTRZEZENIE", "Ocena negatywna bez uzasadnienia (§ 11 ust. 3)."))
    return out


def blocking(problems: Iterable[Problem]) -> list[Problem]:
    return [p for p in problems if p.severity == "BLAD"]


# ---------------------------------------------------------------- the imported cycle

def to_cycle(s: LegacySheet, cycle_id: str, evaluator_id: str, today: date, rules: RuleBook) -> EvaluationCycle:
    """A finished cycle in the employee's history, marked imported (never part of progress reports)."""
    computed = result_of(s, rules)
    average = s.declared_average if s.declared_average is not None else computed.average
    result = EvaluationResult(average, s.level, Outcome(s.outcome))
    mandatory = set(rules.mandatory(s.sheet))
    c = EvaluationCycle(
        id=cycle_id, employee_id=s.employee_id, evaluator_id=evaluator_id, sheet=s.sheet,
        start_date=s.period_from or s.evaluated_on, after_negative=False, criteria_deadline=s.evaluated_on,
        status=Status.ACKNOWLEDGED, additional_criteria=[c for c in s.scores if c not in mandatory],
        meeting_date=s.meeting_date, period_from=s.period_from, period_to=s.period_to,
        scores={c: v for c, v in s.scores.items() if v is not None}, justification=s.justification,
        iprz_conclusions=s.iprz, result=result, evaluated_on=s.evaluated_on,
        acknowledged_on=s.acknowledged_on or s.evaluated_on, imported=True,
    )
    c.history.append((today, Status.ACKNOWLEDGED))
    return c


def parse_file(data: bytes, filename: str, rules: RuleBook, people: Iterable[Employee],
               text_of: Callable[[bytes, str], str]) -> LegacySheet:
    return match_people(parse_sheet(text_of(data, filename), rules), people)
