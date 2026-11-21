"""Printable evaluation sheet (HTML, laid out like the regulation's form A/B/C).
The browser's "Drukuj → Zapisz jako PDF" gives a PDF without any extra dependency."""
from __future__ import annotations

from html import escape

from app.domain.cycle import EvaluationCycle
from app.domain.employee import Employee
from app.domain.rulebook import RuleBook
from app.domain.scoring import compute_result

TITLES = {
    "A": "OCENA OKRESOWA KIEROWNIKA URZĘDU",
    "B": "OCENA OKRESOWA URZĘDNIKA SŁUŻBY CYWILNEJ LUB PRACOWNIKA SŁUŻBY CYWILNEJ "
         "ZAJMUJĄCEGO STANOWISKO KIEROWNICZE",
    "C": "OCENA OKRESOWA URZĘDNIKA SŁUŻBY CYWILNEJ LUB PRACOWNIKA SŁUŻBY CYWILNEJ",
}


def _d(d) -> str:
    return d.strftime("%d.%m.%Y") if d else "……………"


def _e(text) -> str:
    return escape(str(text or "")).replace("\n", "<br>")


def sheet_html(cycle: EvaluationCycle, employee: Employee, evaluator: Employee | None, rules: RuleBook,
               deadline, grade_request: dict | None = None) -> str:
    mandatory = rules.mandatory(cycle.sheet)
    ids = cycle.criteria_ids(rules)
    points = sorted(rules.scale)
    result = cycle.result
    if result is None and ids and all(cycle.scores.get(c) for c in ids):
        result = compute_result([cycle.scores[c] for c in ids], rules)

    def matrix(criteria) -> str:
        head = "".join(f"<th>{escape(rules.scale[p])}<br>{p} pkt</th>" for p in points)
        rows = "".join(
            f"<tr><td class='l'>{escape(rules.criterion_name(c))}</td>"
            + "".join(f"<td>{'X' if cycle.scores.get(c) == p else ''}</td>" for p in points) + "</tr>"
            for c in criteria)
        return f"<table><tr><th class='l'>Kryterium</th>{head}</tr>{rows or '<tr><td class=l>brak</td></tr>'}</table>"

    bands = "".join(
        f"<tr><td>{'X' if result and result.level == b.level else ''}</td>"
        f"<td class='l'>{'od' if b.lower_exclusive is None else 'powyżej ' + str(float(b.lower_exclusive)).rstrip('0').rstrip('.')}"
        f" … do {str(float(b.upper_inclusive)).rstrip('0').rstrip('.')} pkt</td><td class='l'>{escape(b.level)}</td></tr>"
        for b in rules.level_bands)
    outcome = result.outcome.value if result else ""
    prev = cycle.previous_evaluation or employee.previous_evaluation
    gr = grade_request or {}
    ev_name = evaluator.full_name if evaluator else cycle.evaluator_id

    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<title>Arkusz {cycle.sheet} – {escape(employee.full_name)}</title>
<style>
body {{ font-family: "Times New Roman", serif; font-size: 11pt; margin: 2cm; color: #000; }}
h1 {{ font-size: 13pt; text-align: center; }} h2 {{ font-size: 12pt; margin-top: 18pt; }}
table {{ border-collapse: collapse; width: 100%; margin: 6pt 0; }}
td, th {{ border: 1px solid #000; padding: 3pt 5pt; text-align: center; vertical-align: top; font-size: 10pt; }}
.l {{ text-align: left; }} .box {{ border: 1px solid #000; min-height: 50pt; padding: 5pt; }}
.sig {{ display: flex; justify-content: space-between; margin-top: 18pt; font-size: 10pt; }}
@media print {{ body {{ margin: 1.2cm; }} .noprint {{ display: none; }} }}
</style></head><body>
<p class="noprint" style="background:#fff8c5;padding:6pt">Aby zapisać PDF: Drukuj (Ctrl+P) → „Zapisz jako PDF”.</p>
<p style="text-align:right">ARKUSZ {cycle.sheet}</p>
<h1>{TITLES.get(cycle.sheet, "OCENA OKRESOWA")}</h1>
<h2>CZĘŚĆ I</h2>
<table><tr><td class="l" style="width:35%">NAZWA URZĘDU</td><td class="l">{_e(employee.office)}</td></tr></table>
<table><tr><th colspan="2" class="l">DANE OCENIANEGO</th><th colspan="2" class="l">DANE OCENIAJĄCEGO</th></tr>
<tr><td class="l">Imię i nazwisko</td><td class="l">{_e(employee.full_name)}</td><td class="l">Imię i nazwisko</td><td class="l">{_e(ev_name)}</td></tr>
<tr><td class="l">Komórka organizacyjna</td><td class="l">{_e(employee.unit)}</td><td class="l">Komórka organizacyjna</td><td class="l">{_e(evaluator.unit if evaluator else "")}</td></tr>
<tr><td class="l">Stanowisko</td><td class="l">{_e(employee.position)}</td><td class="l">Stanowisko</td><td class="l">{_e(evaluator.position if evaluator else "")}</td></tr></table>
<table><tr><th class="l">Kryteria obowiązkowe</th><th class="l">Kryteria dodatkowe wybrane przez oceniającego (nie więcej niż {rules.max_additional_criteria})</th></tr>
<tr><td class="l">{"<br>".join(escape(rules.criterion_name(c)) for c in mandatory)}</td>
<td class="l">{"<br>".join(escape(rules.criterion_name(c)) for c in cycle.additional_criteria) or "brak"}</td></tr></table>
<p>Termin sporządzenia oceny: <b>{_d(deadline)}</b></p>
<p>Potwierdzamy przeprowadzenie rozmowy, o której mowa w § 5 ust. 1 rozporządzenia, i zapoznanie ocenianego z kryteriami
oceny oraz terminem sporządzenia oceny.</p>
<div class="sig"><span>oceniający: {_d(cycle.criteria_set_on)} – {_e(ev_name)}</span>
<span>oceniany: {_d(cycle.criteria_confirmed_on)} – {_e(employee.full_name)}</span></div>
<h2>CZĘŚĆ II</h2>
<p>Data przeprowadzenia rozmowy oceniającej: <b>{_d(cycle.meeting_date)}</b><br>
Okres, w którym oceniany podlegał ocenie: od <b>{_d(cycle.period_from)}</b> do <b>{_d(cycle.period_to)}</b></p>
<p><b>KRYTERIA OBOWIĄZKOWE</b></p>{matrix(mandatory)}
<p><b>KRYTERIA DODATKOWE WYBRANE PRZEZ OCENIAJĄCEGO</b></p>{matrix(cycle.additional_criteria)}
<p>Średnia arytmetyczna z ocen cząstkowych: <b>{f"{result.average_display:.2f}".replace(".", ",") if result else "……"}</b></p>
<p><b>PRZYZNANIE OCENY</b></p>
<table><tr><th>X</th><th class="l">Średnia arytmetyczna</th><th class="l">Ogólny poziom spełnienia kryteriów</th></tr>{bands}</table>
<table><tr><th>OCENA OKRESOWA W SŁUŻBIE CYWILNEJ</th><th>POZYTYWNA {"X" if outcome == "pozytywna" else ""}</th>
<th>NEGATYWNA {"X" if outcome == "negatywna" else ""}</th></tr></table>
<p><b>UZASADNIENIE PRZYZNANEJ OCENY</b></p><div class="box">{_e(cycle.justification)}</div>
<p><b>WNIOSKI DOTYCZĄCE INDYWIDUALNEGO PROGRAMU ROZWOJU ZAWODOWEGO</b></p><div class="box">{_e(cycle.iprz_conclusions)}</div>
<p>Dane dotyczące poprzedniej oceny okresowej: {_e(prev.outcome if prev else "brak")}{", " + _e(prev.level) if prev and prev.level else ""}{", " + _d(prev.date) if prev and prev.date else ""}</p>
<p>Czy do oceny dołączono wniosek o przyznanie kolejnego stopnia służbowego:
<b>{"TAK" if gr.get("attach") else "NIE" if gr.get("official") else "NIE DOTYCZY"}</b></p>
<div class="sig"><span>oceniający: {_d(cycle.evaluated_on)} – {_e(ev_name)}</span>
<span>zapoznałem/-am się z oceną: {_d(cycle.acknowledged_on)} – {_e(employee.full_name)}</span></div>
{f'<h2>CZĘŚĆ III</h2><p><b>UMOTYWOWANY WNIOSEK O PRZYZNANIE KOLEJNEGO STOPNIA SŁUŻBOWEGO</b></p><div class="box">{_e(gr.get("text"))}</div>' if gr.get("attach") else ""}
</body></html>"""
