"""ArchiveStore on the `archiwum` table (backend/db.py::ArchiveRecord). Insert-only: no update method exists."""
from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import Session, SQLModel, select

from app.application.archive import Frozen
from backend.db import ArchiveRecord


def _frozen(r: ArchiveRecord) -> Frozen:
    return Frozen(r.id, r.cycle_id, r.employee_id, r.frozen_on, r.snapshot, r.snapshot_sha256, r.pdf, r.pdf_sha256)


class SqlArchiveStore:
    def __init__(self, engine):
        self.engine = engine
        SQLModel.metadata.create_all(engine, tables=[ArchiveRecord.__table__])

    def get(self, cycle_id: str) -> Frozen | None:
        with Session(self.engine) as s:
            r = s.exec(select(ArchiveRecord).where(ArchiveRecord.cycle_id == cycle_id)).first()
            return _frozen(r) if r else None

    def by_id(self, record_id: int) -> Frozen | None:
        with Session(self.engine) as s:
            r = s.get(ArchiveRecord, record_id)
            return _frozen(r) if r else None

    def add(self, f: Frozen) -> Frozen:
        with Session(self.engine) as s:
            r = ArchiveRecord(cycle_id=f.cycle_id, employee_id=f.employee_id, frozen_on=f.frozen_on,
                              snapshot=f.snapshot, snapshot_sha256=f.snapshot_sha256, pdf=f.pdf, pdf_sha256=f.pdf_sha256)
            s.add(r)
            s.commit()
            s.refresh(r)
            return _frozen(r)

    def all(self) -> list[Frozen]:
        with Session(self.engine) as s:
            return [_frozen(r) for r in s.exec(select(ArchiveRecord).order_by(ArchiveRecord.id)).all()]

    def delete(self, record_id: int) -> None:
        with Session(self.engine) as s:
            s.exec(delete(ArchiveRecord).where(ArchiveRecord.id == record_id))
            s.commit()

    def clear(self) -> None:
        """Tests / demo reset only."""
        with Session(self.engine) as s:
            s.exec(delete(ArchiveRecord))
            s.commit()
