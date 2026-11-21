"""PDF letter „Powiadomienie o zmianie terminu oceny okresowej" (§ 8 rozporządzenia: the evaluated person is
informed in writing of the new deadline; a copy is attached to the sheet). Plain data in, bytes out – same fonts
as the sheet (backend/sheet_pdf.py)."""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from backend.sheet_pdf import _d, _Doc


@dataclass
class DeadlineNotice:
    office: str
    place: str  # miejscowość (may be empty)
    issued_on: date
    employee_name: str
    employee_position: str
    employee_unit: str
    evaluator_name: str
    evaluator_position: str
    old_deadline: date
    new_deadline: date
    legal_basis: str  # e.g. "art. 81 ust. 8 pkt 2 – przewidywana dłuższa … nieobecność ocenianego"
    justification: str


def render_deadline_notice(n: DeadlineNotice) -> bytes:
    doc = _Doc()
    p = doc.p
    out = [
        p(f"{n.place + ', ' if n.place else ''}dnia {_d(n.issued_on)}", "body"),
        Spacer(1, 4 * mm),
        p(n.office, "bold"),
        Spacer(1, 8 * mm),
        p(f"Pan(i) {n.employee_name}", "bold"),
        p(f"{n.employee_position}{', ' + n.employee_unit if n.employee_unit else ''}"),
        Spacer(1, 10 * mm),
        p("POWIADOMIENIE O ZMIANIE TERMINU OCENY OKRESOWEJ", "title"),
        Spacer(1, 8 * mm),
        p("Na podstawie art. 81 ust. 8 ustawy z dnia 21 listopada 2008 r. o służbie cywilnej oraz § 8 rozporządzenia "
          "Prezesa Rady Ministrów z dnia 4 kwietnia 2016 r. w sprawie warunków i sposobu przeprowadzania ocen "
          "okresowych urzędników służby cywilnej i pracowników służby cywilnej informuję, że termin sporządzenia "
          f"Pana(i) oceny okresowej został zmieniony z dnia {_d(n.old_deadline)} na dzień {_d(n.new_deadline)}."),
        Spacer(1, 4 * mm),
        p(f"Podstawa zmiany: {n.legal_basis}."),
        Spacer(1, 3 * mm),
        p("Uzasadnienie:", "bold"),
        p(n.justification.strip() or "–"),
        Spacer(1, 4 * mm),
        p("Kopię niniejszego pisma dołącza się do arkusza oceny okresowej.", "small"),
        Spacer(1, 18 * mm),
        p("……………………………………………", "body"),
        p(f"{n.evaluator_name} – {n.evaluator_position}", "small"),
        p("(podpis oceniającego)", "small"),
        Spacer(1, 14 * mm),
        p("Potwierdzam otrzymanie pisma:   ……………………………   dnia ……………", "body"),
        p("(podpis ocenianego)", "small"),
    ]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=18 * mm, title="Powiadomienie o zmianie terminu oceny okresowej").build(out)
    return buf.getvalue()
