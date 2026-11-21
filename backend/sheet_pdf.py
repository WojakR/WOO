"""PDF of the periodic-evaluation sheet (UC6), laid out after the KPRM form (wiedza/schemat-pol-arkusz-*.md).

Input is plain data (`SheetPdf`), so this module knows nothing about the API or the domain. Rendering uses
reportlab with a TrueType font that has Polish letters (env `PDF_FONT`, then common system fonts); without
one it falls back to Helvetica and transliterates (ą -> a), so a PDF is always produced – also offline.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

TITLE = "OCENA OKRESOWA URZĘDNIKA SŁUŻBY CYWILNEJ LUB PRACOWNIKA SŁUŻBY CYWILNEJ"
REGULATION = ("§ 5 ust. 1 rozporządzenia Prezesa Rady Ministrów z dnia 4 kwietnia 2016 r. w sprawie warunków "
              "i sposobu przeprowadzania ocen okresowych urzędników służby cywilnej i pracowników służby cywilnej "
              "(Dz. U. poz. 470)")

_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„”–§", 'acelnoszzACELNOSZZ""-S')


@dataclass(frozen=True)
class Person:
    first_name: str
    last_name: str
    unit: str = ""
    position: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass
class SheetPdf:
    sheet: str
    office: str
    employee: Person
    evaluator: Person
    scale: list[tuple[int, str]]                       # (points, label) in form order
    levels: list[tuple[str, str]]                      # (level label, range text) in form order
    mandatory: list[tuple[str, int | None]]            # (criterion name, points)
    additional: list[tuple[str, int | None]] = field(default_factory=list)
    max_additional: int = 3
    deadline: date | None = None
    criteria_set_on: date | None = None
    criteria_confirmed_on: date | None = None
    meeting_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    average: float | None = None
    level: str | None = None                           # one of `levels` labels
    positive: bool | None = None
    justification: str = ""
    iprz: str = ""
    civil_servant: bool = False
    previous: tuple[str, str, date | None] | None = None  # (outcome, level, date) – civil servants only
    evaluated_on: date | None = None
    acknowledged_on: date | None = None
    objection_days: int = 7
    draft: bool = True                                 # not yet submitted by the evaluator


# ---------------------------------------------------------------- fonts

_fonts: tuple[str, str, bool] | None = None


def _register_fonts() -> tuple[str, str, bool]:
    """-> (regular, bold, unicode_ok)."""
    global _fonts
    if _fonts is not None:
        return _fonts
    candidates = list(_FONT_CANDIDATES)
    if env := os.environ.get("PDF_FONT"):
        bold = os.environ.get("PDF_FONT_BOLD", env)
        candidates.insert(0, (env, bold))
    for regular, bold in candidates:
        if not Path(regular).is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("SheetFont", regular))
            pdfmetrics.registerFont(TTFont("SheetFont-Bold", bold if Path(bold).is_file() else regular))
            _fonts = ("SheetFont", "SheetFont-Bold", True)
            return _fonts
        except Exception:  # noqa: BLE001 – a broken font file just means "try the next one"
            continue
    _fonts = ("Helvetica", "Helvetica-Bold", False)
    return _fonts


# ---------------------------------------------------------------- helpers

def _d(day: date | None) -> str:
    return day.strftime("%d.%m.%Y") if day else "……………"


def _num(x: float | None) -> str:
    return f"{x:.2f}".replace(".", ",") if x is not None else "–"


class _Doc:
    def __init__(self):
        self.regular, self.bold, self.unicode_ok = _register_fonts()
        base = dict(fontName=self.regular, fontSize=9, leading=11.5)
        self.st = {
            "body": ParagraphStyle("body", **base),
            "small": ParagraphStyle("small", **{**base, "fontSize": 7.5, "leading": 9.5}),
            "bold": ParagraphStyle("bold", **{**base, "fontName": self.bold}),
            "title": ParagraphStyle("title", **{**base, "fontName": self.bold, "fontSize": 12, "leading": 15,
                                                "alignment": TA_CENTER}),
            "part": ParagraphStyle("part", **{**base, "fontName": self.bold, "fontSize": 10.5, "leading": 13,
                                               "spaceBefore": 8, "spaceAfter": 4}),
            "head": ParagraphStyle("head", **{**base, "fontName": self.bold, "fontSize": 8.5, "leading": 10.5,
                                               "textColor": colors.HexColor("#1f3b66")}),
            "center": ParagraphStyle("center", **{**base, "alignment": TA_CENTER}),
            "draft": ParagraphStyle("draft", **{**base, "fontName": self.bold, "textColor": colors.HexColor("#b42318"),
                                                "alignment": TA_CENTER}),
        }

    def t(self, text: str) -> str:
        text = text if self.unicode_ok else text.translate(_PL)
        return escape(text).replace("\n", "<br/>")

    def p(self, text: str, style: str = "body") -> Paragraph:
        return Paragraph(self.t(text), self.st[style])

    def table(self, rows, widths, extra=(), header=False):
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#8a94a6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")))
        return Table(rows, colWidths=widths, style=TableStyle(style + list(extra)))


def _mark(on: bool) -> str:
    return "X" if on else ""


# ---------------------------------------------------------------- render

def render_sheet_pdf(s: SheetPdf) -> bytes:
    doc = _Doc()
    p = doc.p
    W = A4[0] - 30 * mm
    out: list = []

    out.append(p(f"Arkusz {s.sheet}", "small"))
    out.append(p(TITLE, "title"))
    if s.draft:
        out.append(Spacer(1, 3))
        out.append(p("WERSJA ROBOCZA – ocena nie została jeszcze zatwierdzona przez oceniającego", "draft"))
    out.append(Spacer(1, 6))

    # ---- CZĘŚĆ I
    out.append(p("CZĘŚĆ I", "part"))
    out.append(doc.table([[p("NAZWA URZĘDU", "head"), p(s.office)]], [0.3 * W, 0.7 * W]))
    out.append(Spacer(1, 6))
    people = [[p("DANE OCENIANEGO", "head"), "", p("DANE OCENIAJĄCEGO", "head"), ""]]
    for label, a, b in [
        ("Imię", s.employee.first_name, s.evaluator.first_name),
        ("Nazwisko", s.employee.last_name, s.evaluator.last_name),
        ("Komórka organizacyjna", s.employee.unit, s.evaluator.unit),
        ("Stanowisko", s.employee.position, s.evaluator.position),
    ]:
        people.append([p(label, "small"), p(a or "–"), p(label, "small"), p(b or "–")])
    out.append(doc.table(people, [0.17 * W, 0.33 * W, 0.17 * W, 0.33 * W],
                         [("SPAN", (0, 0), (1, 0)), ("SPAN", (2, 0), (3, 0))], header=True))
    out.append(Spacer(1, 6))

    crit = [[p("KRYTERIA OCENY I TERMIN SPORZĄDZENIA OCENY", "head")], [p("Kryteria obowiązkowe", "bold")]]
    crit += [[p(f"{i}. {name}")] for i, (name, _) in enumerate(s.mandatory, start=1)]
    crit.append([p(f"Kryteria dodatkowe wybrane przez oceniającego (nie więcej niż {s.max_additional})", "bold")])
    adds = [name for name, _ in s.additional] + ["brak"] * (s.max_additional - len(s.additional))
    crit += [[p(f"{i}. {name}")] for i, name in enumerate(adds, start=1)]
    crit.append([p(f"Termin sporządzenia oceny: {_d(s.deadline)}", "bold")])
    out.append(doc.table(crit, [W], header=True))
    out.append(Spacer(1, 6))

    out.append(p("Potwierdzamy", "bold"))
    out.append(p(f"– przeprowadzenie rozmowy, o której mowa w {REGULATION}, i omówienie w trakcie rozmowy wszystkich "
                 "wymaganych zagadnień,\n– zapoznanie ocenianego z kryteriami oceny oraz terminem sporządzenia oceny.",
                 "small"))
    out.append(Spacer(1, 4))
    out.append(_signatures(doc, W, [
        ("oceniającego", s.criteria_set_on, s.evaluator.full_name if s.criteria_set_on else ""),
        ("ocenianego", s.criteria_confirmed_on, s.employee.full_name if s.criteria_confirmed_on else ""),
    ]))

    # ---- CZĘŚĆ II
    out.append(p("CZĘŚĆ II", "part"))
    out.append(doc.table([
        [p("Data przeprowadzenia rozmowy oceniającej", "small"), p(_d(s.meeting_date))],
        [p("Okres, w którym oceniany podlegał ocenie", "small"),
         p(f"od {_d(s.period_from)} do {_d(s.period_to)}")],
    ], [0.45 * W, 0.55 * W]))
    out.append(Spacer(1, 6))

    name_w = 0.40 * W
    col_w = (W - name_w) / max(1, len(s.scale))
    head = [p("Kryterium", "head")] + [p(f"{label}\n{pts} pkt", "small") for pts, label in s.scale]
    rows = [head]
    group_rows = []

    def group(title, items, empty):
        group_rows.append(len(rows))
        rows.append([p(title, "bold")] + [""] * len(s.scale))
        if not items:
            rows.append([p(empty)] + [""] * len(s.scale))
        for name, pts in items:
            rows.append([p(name)] + [p(_mark(pts == v), "center") for v, _ in s.scale])

    group("KRYTERIA OBOWIĄZKOWE", s.mandatory, "–")
    group("KRYTERIA DODATKOWE WYBRANE PRZEZ OCENIAJĄCEGO", s.additional, "brak")
    extra = [("ALIGN", (1, 0), (-1, -1), "CENTER")]
    for r in group_rows:
        extra += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f3f5f9"))]
    out.append(doc.table(rows, [name_w] + [col_w] * len(s.scale), extra, header=True))
    out.append(Spacer(1, 6))

    out.append(doc.table([[p("Średnia arytmetyczna z ocen cząstkowych przyznanych za poszczególne kryteria oceny",
                             "small"), p(_num(s.average), "bold")]], [0.75 * W, 0.25 * W]))
    out.append(Spacer(1, 6))

    lv = [[p("PRZYZNANIE OCENY", "head"), "", ""]]
    lv += [[p(_mark(s.level == label), "center"), p(label), p(rng, "small")] for label, rng in s.levels]
    out.append(KeepTogether(doc.table(lv, [0.1 * W, 0.45 * W, 0.45 * W], [("SPAN", (0, 0), (-1, 0))], header=True)))
    out.append(Spacer(1, 6))

    out.append(doc.table([[p("OCENA OKRESOWA W SŁUŻBIE CYWILNEJ:", "head"),
                           p(f"[{_mark(s.positive is True) or ' '}]  POZYTYWNA", "bold"),
                           p(f"[{_mark(s.positive is False) or ' '}]  NEGATYWNA", "bold")]],
                         [0.44 * W, 0.28 * W, 0.28 * W]))
    out.append(Spacer(1, 6))

    for title, text in [("UZASADNIENIE PRZYZNANEJ OCENY", s.justification),
                        ("WNIOSKI DOTYCZĄCE INDYWIDUALNEGO PROGRAMU ROZWOJU ZAWODOWEGO", s.iprz)]:
        out.append(doc.table([[p(title, "head")], [p(text.strip() or "–")]], [W], header=True))
        out.append(Spacer(1, 6))

    prev_rows = [[p("DANE DOTYCZĄCE POPRZEDNIEJ OCENY OKRESOWEJ URZĘDNIKA SŁUŻBY CYWILNEJ", "head"), "", ""]]
    if s.civil_servant:
        outcome, level, day = s.previous or ("brak", "", None)
        prev_rows.append([p(f"Ocena: {outcome or 'brak'}"), p(f"Poziom: {level or '–'}"),
                          p(f"Data sporządzenia: {_d(day) if day else '–'}")])
    else:
        prev_rows.append([p("nie dotyczy – oceniany nie jest urzędnikiem służby cywilnej", "small"), "", ""])
    out.append(doc.table(prev_rows, [W / 3] * 3, [("SPAN", (0, 0), (-1, 0))]
                         + ([] if s.civil_servant else [("SPAN", (0, 1), (-1, 1))]), header=True))
    out.append(Spacer(1, 6))

    grade = "NIE DOTYCZY" if not s.civil_servant else ("NIE" if s.positive is False else "")
    out.append(doc.table([
        [p("CZY DO OCENY OKRESOWEJ DOŁĄCZONO WNIOSEK O PRZYZNANIE KOLEJNEGO STOPNIA SŁUŻBOWEGO", "head"), "", ""],
        [p(f"[{_mark(grade == 'TAK') or ' '}]  TAK"), p(f"[{_mark(grade == 'NIE') or ' '}]  NIE"),
         p(f"[{_mark(grade == 'NIE DOTYCZY') or ' '}]  NIE DOTYCZY (oceniany jest pracownikiem służby cywilnej)")],
    ], [0.2 * W, 0.2 * W, 0.6 * W], [("SPAN", (0, 0), (-1, 0))], header=True))
    out.append(Spacer(1, 6))

    ev = s.evaluator
    out.append(KeepTogether([
        doc.table([[p("DANE OCENIAJĄCEGO", "head"), ""],
                   [p("Imię i nazwisko", "small"), p(ev.full_name)],
                   [p("Komórka organizacyjna", "small"), p(ev.unit or "–")],
                   [p("Stanowisko", "small"), p(ev.position or "–")],
                   [p("Miejscowość, data", "small"), p(f"……………, {_d(s.evaluated_on)}")]],
                  [0.3 * W, 0.7 * W], [("SPAN", (0, 0), (-1, 0))], header=True),
        Spacer(1, 6),
        doc.table([[p("Przeprowadzono ze mną rozmowę oceniającą oraz zapoznałem (-łam) się z oceną okresową "
                      "i wnioskami dotyczącymi indywidualnego programu rozwoju zawodowego", "small"), ""],
                   [p("Miejscowość, data", "small"), p(f"……………, {_d(s.acknowledged_on)}")],
                   [p("Imię i nazwisko ocenianego", "small"),
                    p(s.employee.full_name if s.acknowledged_on else "……………")]],
                  [0.3 * W, 0.7 * W], [("SPAN", (0, 0), (-1, 0))]),
        Spacer(1, 6),
        p("Pouczenie", "bold"),
        p(f"Na podstawie art. 83 ust. 1 ustawy z dnia 21 listopada 2008 r. o służbie cywilnej od oceny okresowej "
          f"służy, w terminie {s.objection_days} dni od dnia zapoznania się z oceną, sprzeciw do dyrektora "
          "generalnego urzędu.", "small"),
    ]))

    buf = io.BytesIO()

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(doc.regular, 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(15 * mm, 9 * mm, doc.t(f"Arkusz {s.sheet} – {s.employee.full_name}"))
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"str. {d.page}")
        canvas.restoreState()

    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=doc.t(f"Ocena okresowa – {s.employee.full_name}"),
                            author="Cyfrowy Asystent Ocen Okresowych")
    pdf.build(out, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _signatures(doc: _Doc, width: float, who: list[tuple[str, date | None, str]]):
    p = doc.p
    cells = [[p(f"Miejscowość, data: ……………, {_d(day)}\nImię i nazwisko {role}: {name or '……………'}", "small")
              for role, day, name in who]]
    return doc.table(cells, [width / len(who)] * len(who))
