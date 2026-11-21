import io
from datetime import date

from pypdf import PdfReader

import backend.sheet_pdf as sp


def _sheet(**kw) -> sp.SheetPdf:
    base = dict(
        sheet="C", office="Urząd Testowy",
        employee=sp.Person("Grzegorz", "Wzór", "Referat", "specjalista"),
        evaluator=sp.Person("Henryk", "Pryncypał", "Referat", "kierownik"),
        scale=[(1, "znacznie poniżej oczekiwań"), (3, "poniżej oczekiwań"), (5, "na poziomie oczekiwań"),
               (7, "powyżej oczekiwań"), (9, "znacznie powyżej oczekiwań")],
        levels=[("na poziomie oczekiwań", "powyżej 4 do 6 pkt")],
        mandatory=[("Rzetelność", 5)], additional=[("Kreatywność", 7)],
        average=6.0, level="na poziomie oczekiwań", positive=True,
        justification="Dobra praca.", iprz="Kurs.", evaluated_on=date(2026, 5, 25), draft=False,
    )
    return sp.SheetPdf(**{**base, **kw})


def _text(data: bytes) -> str:
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_render_contains_form_sections():
    text = _text(sp.render_sheet_pdf(_sheet()))
    for part in ("CZĘŚĆ I", "CZĘŚĆ II", "Rzetelność", "Kreatywność", "6,00", "Pouczenie", "25.05.2026"):
        assert part in text or part.translate(sp._PL) in text
    assert "WERSJA ROBOCZA" not in text


def test_draft_marker_and_font_fallback(monkeypatch):
    monkeypatch.setattr(sp, "_fonts", ("Helvetica", "Helvetica-Bold", False))
    text = _text(sp.render_sheet_pdf(_sheet(draft=True, average=None, level=None, positive=None)))
    assert "WERSJA ROBOCZA" in text and "Rzetelnosc" in text  # transliterated without a Unicode font
