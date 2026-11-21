"""Adapters of PersonnelFileExporter (app/application/ports.py) – the e-Akt interface is not known yet.

- DirectoryExporter: works now – <dir>/<employee id>/<file>.pdf + <file>.json (metadata: employee id, kind of
  document, date, part of the file, SHA-256). A records system or an integration job can pick the files up.
- HttpExporter: skeleton for the e-Akt service (EAKT_URL, EAKT_TOKEN in .env); raises NotImplementedError listing
  what is missing from the supplier before it can be written.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.application.personnel_export import PersonnelDocument


class DirectoryExporter:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def export(self, document: PersonnelDocument) -> str:
        folder = self.directory / document.employee_id
        folder.mkdir(parents=True, exist_ok=True)
        pdf = folder / document.filename
        tmp = pdf.with_suffix(".pdf.tmp")
        tmp.write_bytes(document.pdf)
        tmp.replace(pdf)  # never leave a half-written PDF next to its metadata
        pdf.with_suffix(".json").write_text(json.dumps(document.metadata(), ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        return str(pdf)


QUESTIONS_FOR_THE_SUPPLIER = (
    "Adres i wersja API (REST/SOAP/ePUAP), środowisko testowe.",
    "Uwierzytelnianie: token, certyfikat klienta (mTLS), konto techniczne urzędu?",
    "Identyfikator pracownika w e-Akt (PESEL, nr ewidencyjny kadr, własne ID) i sposób mapowania.",
    "Słownik rodzajów dokumentów i oznaczenie części akt (B) dla arkusza oceny okresowej.",
    "Format pliku (PDF/A?), limit rozmiaru, wymagany podpis elektroniczny (kwalifikowany / pieczęć urzędu).",
    "Metadane obowiązkowe (data dokumentu, sygnatura, JRWA, autor) i ich format.",
    "Wersjonowanie: jak zastąpić dokument po rozpatrzeniu sprzeciwu (nowa wersja czy nowy dokument).",
    "Potwierdzenie przyjęcia (UPO / identyfikator dokumentu), kody błędów, limity i zalecane ponawianie.",
)


class HttpExporter:
    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def export(self, document: PersonnelDocument) -> str:
        missing = "\n".join(f"- {q}" for q in QUESTIONS_FOR_THE_SUPPLIER)
        raise NotImplementedError(
            f"Adapter e-Akt (HTTP, {self.url or 'brak EAKT_URL'}) nie jest jeszcze zaimplementowany – "
            f"brakuje specyfikacji interfejsu od dostawcy:\n{missing}")


def build_exporter(mode: str, directory: Path, url: str = "", token: str = ""):
    """From config: off -> None (no export), katalog -> DirectoryExporter, http -> HttpExporter."""
    if mode == "off":
        return None
    if mode == "katalog":
        return DirectoryExporter(directory)
    if mode == "http":
        return HttpExporter(url, token)
    raise ValueError(f"EAKT_MODE: nieznany tryb „{mode}” (off | katalog | http)")
