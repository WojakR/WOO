"""Dziennik zmian (audit log) – append-only. There is deliberately no update or delete here:
an evaluation is a personnel document, every change must stay accountable (who, what, when)."""
from __future__ import annotations

from sqlmodel import select

from backend import db


def append(user_id: str, action: str, evaluation_id: int | None = None, field: str | None = None,
           before: str | None = None, after: str | None = None) -> None:
    with db.session() as s:
        s.add(db.AuditEntry(user_id=user_id, evaluation_id=evaluation_id, action=action, field=field,
                            before=before, after=after))
        s.commit()


def append_many(entries: list[dict]) -> None:
    if not entries:
        return
    with db.session() as s:
        for e in entries:
            s.add(db.AuditEntry(**e))
        s.commit()


def for_evaluation(evaluation_id: int) -> list[db.AuditEntry]:
    with db.session() as s:
        q = select(db.AuditEntry).where(db.AuditEntry.evaluation_id == evaluation_id).order_by(db.AuditEntry.id)
        return list(s.exec(q).all())


def all_entries(limit: int = 500) -> list[db.AuditEntry]:
    with db.session() as s:
        return list(s.exec(select(db.AuditEntry).order_by(db.AuditEntry.id.desc()).limit(limit)).all())
