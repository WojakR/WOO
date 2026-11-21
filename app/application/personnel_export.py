"""Export of the evaluation sheet to the electronic personnel file (e-Akt), spec point 4 (optional).

The sheet goes to part B of the personnel file after the employee acknowledged the evaluation (§ 12 ust. 2 of the
regulation), and again after the objection was decided. A failed export is kept with its error and retried
(on the next export and on demand). The exporter is a port – the target interface of e-Akt is not known yet.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

from app.domain.cycle import EvaluationCycle

from .ports import PersonnelFileExporter

KIND = "ocena_okresowa"
FILE_PART = "B"  # część B akt osobowych – przebieg zatrudnienia


@dataclass(frozen=True)
class PersonnelDocument:
    employee_id: str
    cycle_id: str
    kind: str
    document_date: date  # the day the evaluation was acknowledged (or the objection decided)
    file_part: str
    reason: str  # ZAPOZNANIE | ROZPATRZENIE_SPRZECIWU
    filename: str
    pdf: bytes
    sha256: str

    def metadata(self) -> dict:
        return {"id_pracownika": self.employee_id, "id_oceny": self.cycle_id, "rodzaj_dokumentu": self.kind,
                "data_dokumentu": self.document_date.isoformat(), "czesc_akt": self.file_part,
                "zdarzenie": self.reason, "plik": self.filename, "sha256": self.sha256}


@dataclass(frozen=True)
class ExportStatus:
    cycle_id: str
    status: str  # WYSLANO | BLAD
    reason: str
    attempts: int
    last_attempt: datetime
    location: str = ""
    sha256: str = ""
    error: str = ""


def reason_of(c: EvaluationCycle) -> str:
    decided_later = c.objection_decided_on and c.acknowledged_on and c.objection_decided_on >= c.acknowledged_on
    return "ROZPATRZENIE_SPRZECIWU" if decided_later else "ZAPOZNANIE"


class ExportService:
    def __init__(self, exporter: PersonnelFileExporter, render_pdf: Callable[[EvaluationCycle], bytes],
                 statuses: dict[str, ExportStatus]):
        self.exporter = exporter
        self.render_pdf = render_pdf
        self.statuses = statuses  # kept in the application state (persisted with it)

    def document(self, c: EvaluationCycle) -> PersonnelDocument:
        pdf = self.render_pdf(c)
        reason = reason_of(c)
        day = c.objection_decided_on if reason == "ROZPATRZENIE_SPRZECIWU" else c.acknowledged_on
        name = f"ocena-okresowa-{c.employee_id}-{c.id}-{reason.lower()}.pdf"
        return PersonnelDocument(c.employee_id, c.id, KIND, day or date.today(), FILE_PART, reason, name, pdf,
                                 hashlib.sha256(pdf).hexdigest())

    def export(self, c: EvaluationCycle) -> ExportStatus:
        doc = self.document(c)
        prev = self.statuses.get(c.id)
        attempts = (prev.attempts if prev and prev.reason == doc.reason and prev.status == "BLAD" else 0) + 1
        now = datetime.now(timezone.utc)
        try:
            where = self.exporter.export(doc)
        except Exception as e:  # noqa: BLE001 – any failure (also an unfinished adapter): keep it, retry later
            status = ExportStatus(c.id, "BLAD", doc.reason, attempts, now, sha256=doc.sha256,
                                  error=f"{type(e).__name__}: {e}")
        else:
            status = ExportStatus(c.id, "WYSLANO", doc.reason, attempts, now, where, doc.sha256)
        self.statuses[c.id] = status
        return status

    def retry_failed(self, cycle_of: Callable[[str], EvaluationCycle | None]) -> list[ExportStatus]:
        out = []
        for cid, st in list(self.statuses.items()):
            if st.status == "BLAD" and (c := cycle_of(cid)) is not None:
                out.append(self.export(c))
        return out

