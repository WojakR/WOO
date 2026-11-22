"""Registration of the evaluation's documents in the office's EZD (elektroniczne zarządzanie dokumentacją, e.g. EZD RP).

The documents of the evaluation are official records of the office, so they go into the document management
system next to the personnel file (e-Akt, personnel_export.py):
- the evaluation sheet, once final for the file (acknowledged / refusal noted / objection decided, changed),
- the letter about the changed deadline of the evaluation (§ 8 of the regulation, art. 81 ust. 8).

Each one goes with the metadata EZD asks for on import (kind, title, date, the case's JRWA class, author,
addressee, SHA-256). A failed registration is kept with its error and retried (on the next one and on demand) –
like the e-Akt export. The registry is a port; the EZD's interface of the office is not known yet
(app/infrastructure/ezd.py: a directory package that EZD imports, an HTTP skeleton).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

from app.domain.cycle import EvaluationCycle

from .personnel_export import reason_of

SHEET = "ARKUSZ_OCENY_OKRESOWEJ"
DEADLINE_LETTER = "PISMO_ZMIANA_TERMINU_OCENY"


@dataclass(frozen=True)
class EzdDocument:
    key: str  # stable: sheet-<cycle>-<event> / letter-<change id>
    kind: str  # SHEET | DEADLINE_LETTER
    title: str
    document_date: date
    case_class: str  # JRWA symbol (office setting EZD_JRWA); empty = chosen by the registry office
    author: str  # who signed it (evaluator)
    addressee: str  # the evaluated person
    employee_id: str
    cycle_id: str
    filename: str
    pdf: bytes
    sha256: str

    def metadata(self) -> dict:
        return {"klucz": self.key, "rodzaj_dokumentu": self.kind, "tytul": self.title,
                "data_dokumentu": self.document_date.isoformat(), "jrwa": self.case_class, "autor": self.author,
                "adresat": self.addressee, "id_pracownika": self.employee_id, "id_oceny": self.cycle_id,
                "plik": self.filename, "sha256": self.sha256, "dostep": "ograniczony – dane osobowe pracownika"}


@dataclass(frozen=True)
class RegistrationStatus:
    key: str
    cycle_id: str
    kind: str
    status: str  # ZAREJESTROWANO | BLAD
    attempts: int
    last_attempt: datetime
    reference: str = ""  # where / under which number EZD keeps it
    sha256: str = ""
    error: str = ""


def sheet_document(c: EvaluationCycle, pdf: bytes, case_class: str, author: str, addressee: str) -> EzdDocument:
    reason = reason_of(c)
    day = (c.objection_decided_on if reason == "ROZPATRZENIE_SPRZECIWU" else c.acknowledged_on) or date.today()
    title = f"Arkusz oceny okresowej – {addressee}" + (" (po rozpatrzeniu sprzeciwu)"
                                                       if reason == "ROZPATRZENIE_SPRZECIWU" else "")
    return EzdDocument(f"arkusz-{c.id}-{reason.lower()}-{day.isoformat()}", SHEET, title, day, case_class, author,
                       addressee, c.employee_id, c.id, f"arkusz-oceny-{c.employee_id}-{c.id}.pdf", pdf,
                       hashlib.sha256(pdf).hexdigest())


def letter_document(change_id: int, c: EvaluationCycle, pdf: bytes, day: date, case_class: str, author: str,
                    addressee: str) -> EzdDocument:
    return EzdDocument(f"pismo-termin-{change_id}", DEADLINE_LETTER, f"Informacja o zmianie terminu oceny okresowej – "
                       f"{addressee}", day, case_class, author, addressee, c.employee_id, c.id,
                       f"zmiana-terminu-oceny-{c.id}-{change_id}.pdf", pdf, hashlib.sha256(pdf).hexdigest())


class EzdService:
    def __init__(self, registry, statuses: dict[str, RegistrationStatus]):
        self.registry = registry  # ports.DocumentRegistry
        self.statuses = statuses  # kept in the application state (persisted with it)
        self.pending: dict[str, EzdDocument] = {}  # failed ones, to retry within this process

    def register(self, doc: EzdDocument) -> RegistrationStatus:
        prev = self.statuses.get(doc.key)
        if prev is not None and prev.status == "ZAREJESTROWANO":
            return prev  # once: EZD gives the document its own number
        attempts = (prev.attempts if prev else 0) + 1
        now = datetime.now(timezone.utc)
        try:
            ref = self.registry.register(doc)
        except Exception as e:  # noqa: BLE001 – any failure (also an unfinished adapter): keep it, retry later
            status = RegistrationStatus(doc.key, doc.cycle_id, doc.kind, "BLAD", attempts, now, sha256=doc.sha256,
                                        error=f"{type(e).__name__}: {e}")
            self.pending[doc.key] = doc
        else:
            status = RegistrationStatus(doc.key, doc.cycle_id, doc.kind, "ZAREJESTROWANO", attempts, now, ref,
                                        doc.sha256)
            self.pending.pop(doc.key, None)
        self.statuses[doc.key] = status
        return status

    def retry_failed(self, rebuild: Callable[[RegistrationStatus], EzdDocument | None]) -> list[RegistrationStatus]:
        """`rebuild` makes the document again from the state (after a restart nothing else is in memory)."""
        out = []
        for key, st in list(self.statuses.items()):
            if st.status != "BLAD":
                continue
            doc = self.pending.get(key) or rebuild(st)
            if doc is not None:
                out.append(self.register(doc))
        return out
