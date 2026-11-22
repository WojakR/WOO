"""Adapters of DocumentRegistry (app/application/ports.py) – the office's EZD interface is not known yet.

- DirectoryRegistry: works now – an import package per document: <dir>/<yyyy-mm>/<key>/<file>.pdf + metadane.json
  (kind, title, date, JRWA class, author, addressee, SHA-256). EZD RP and other systems import such packages
  (watched folder / the registry office's import), or an integration job can pick them up.
- HttpRegistry: skeleton for the EZD service (EZD_URL, EZD_TOKEN in .env); raises NotImplementedError listing
  what is missing from the supplier before it can be written.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.application.ezd_registry import EzdDocument


class DirectoryRegistry:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def register(self, document: EzdDocument) -> str:
        folder = self.directory / f"{document.document_date:%Y-%m}" / document.key
        folder.mkdir(parents=True, exist_ok=True)
        pdf = folder / document.filename
        tmp = pdf.with_suffix(".pdf.tmp")
        tmp.write_bytes(document.pdf)
        tmp.replace(pdf)  # never leave a half-written PDF next to its metadata
        (folder / "metadane.json").write_text(json.dumps(document.metadata(), ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        return str(pdf)


QUESTIONS_FOR_THE_SUPPLIER = (
    "Który system EZD (EZD RP, EZD PUW, inny) i wersja API (REST / SOAP / ePUAP), środowisko testowe.",
    "Uwierzytelnianie: konto techniczne, token, certyfikat klienta (mTLS)?",
    "Czy dokument trafia do istniejącej sprawy (znak sprawy) czy system zakłada nową sprawę – i kto jest jej "
    "referentem (kadry, oceniający)?",
    "Klasa JRWA dla ocen okresowych w urzędzie i kategoria archiwalna (np. B10 w aktach osobowych).",
    "Format pliku (PDF/A?), limit rozmiaru, wymagany podpis / pieczęć elektroniczna urzędu.",
    "Metadane obowiązkowe (tytuł, data, nadawca, adresat, rodzaj dokumentu) i ich słowniki.",
    "Ograniczenie dostępu do dokumentu z danymi osobowymi pracownika (kto widzi go w EZD).",
    "Wersjonowanie: jak dołączyć arkusz po zmianie oceny lub ponownym sporządzeniu (nowa wersja czy nowy dokument).",
    "Potwierdzenie rejestracji (numer / identyfikator dokumentu), kody błędów, limity i zalecane ponawianie.",
)


class HttpRegistry:
    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def register(self, document: EzdDocument) -> str:
        missing = "\n".join(f"- {q}" for q in QUESTIONS_FOR_THE_SUPPLIER)
        raise NotImplementedError(
            f"Adapter EZD (HTTP, {self.url or 'brak EZD_URL'}) nie jest jeszcze zaimplementowany – brakuje "
            f"specyfikacji interfejsu od dostawcy:\n{missing}")


def build_registry(mode: str, directory: Path, url: str = "", token: str = ""):
    """From config: off -> None (no registration), katalog -> DirectoryRegistry, http -> HttpRegistry."""
    if mode == "off":
        return None
    if mode == "katalog":
        return DirectoryRegistry(directory)
    if mode == "http":
        return HttpRegistry(url, token)
    raise ValueError(f"EZD_MODE: nieznany tryb „{mode}” (off | katalog | http)")
