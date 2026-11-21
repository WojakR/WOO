"""Database persistence of the application state (SQLModel; SQLite file locally, PostgreSQL via DATABASE_URL).

One table per aggregate: columns to search and join on (ids, people, status, dates) + the whole object as JSON
(`dane`, see json_codec.py). The full relational model in docs/model-danych.md is the next step; this keeps the
domain objects as they are and makes the data survive a restart – data must be kept for as long as a person works
in the office, and archived afterwards (KPRM mentor).

`save` replaces everything in one transaction (fine for one office: tens of evaluations, hundreds of notes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Column, Text, delete
from sqlmodel import Field, Session, SQLModel, select

from .json_codec import JsonCodec


class OcenaRow(SQLModel, table=True):
    __tablename__ = "ocena"
    id: str = Field(primary_key=True)
    oceniany_id: str = Field(index=True)
    oceniajacy_id: str = Field(index=True)
    status: str = Field(index=True)
    dane: str = Field(sa_column=Column(Text, nullable=False))


class NotatkaRow(SQLModel, table=True):
    __tablename__ = "notatka"
    id: int = Field(primary_key=True)
    ocena_id: int = Field(index=True)
    dane: str = Field(sa_column=Column(Text, nullable=False))


class NieobecnoscRow(SQLModel, table=True):
    __tablename__ = "nieobecnosc"
    id: int = Field(primary_key=True)
    pracownik_id: str = Field(index=True)
    ocena_id: str = Field(index=True)
    dane: str = Field(sa_column=Column(Text, nullable=False))


class ZmianaTerminuRow(SQLModel, table=True):
    __tablename__ = "zmiana_terminu"
    id: int = Field(primary_key=True)
    ocena_id: str = Field(index=True)
    dane: str = Field(sa_column=Column(Text, nullable=False))


class ZastepstwoRow(SQLModel, table=True):
    __tablename__ = "zastepstwo"
    id: int = Field(primary_key=True)
    oceniajacy_id: str = Field(index=True)
    zastepca_id: str = Field(index=True)
    od: date
    do: date
    dane: str = Field(sa_column=Column(Text, nullable=False))


class StanRow(SQLModel, table=True):
    """Small pieces of state: the server clock, versions for optimistic locking, HR-partner decisions…"""
    __tablename__ = "stan"
    klucz: str = Field(primary_key=True)
    dane: str = Field(sa_column=Column(Text, nullable=False))


_TABLES = [OcenaRow, NotatkaRow, NieobecnoscRow, ZmianaTerminuRow, ZastepstwoRow, StanRow]


@dataclass
class Snapshot:
    """Everything that must survive a restart. Objects are duck-typed by the attributes used for the columns."""
    cycles: list[Any] = field(default_factory=list)  # .id .employee_id .evaluator_id .status
    notes: list[Any] = field(default_factory=list)  # .note.id .evaluation_id
    absences: list[Any] = field(default_factory=list)  # .id .employee_id .cycle_id
    deadline_changes: list[Any] = field(default_factory=list)  # .id .cycle_id
    deputies: list[Any] = field(default_factory=list)  # .id .evaluator_id .deputy_id .od .do
    meta: dict[str, Any] = field(default_factory=dict)


class SqlStateStore:
    def __init__(self, engine, codec: JsonCodec):
        self.engine = engine
        self.codec = codec
        SQLModel.metadata.create_all(engine, tables=[t.__table__ for t in _TABLES])

    def is_empty(self) -> bool:
        with Session(self.engine) as s:
            return s.exec(select(StanRow).limit(1)).first() is None

    def clear(self) -> None:
        with Session(self.engine) as s:
            for t in _TABLES:
                s.exec(delete(t))
            s.commit()

    def save(self, snap: Snapshot) -> None:
        enc = self.codec.dumps
        with Session(self.engine) as s:
            for t in _TABLES:
                s.exec(delete(t))
            s.add_all(OcenaRow(id=c.id, oceniany_id=c.employee_id, oceniajacy_id=c.evaluator_id,
                               status=c.status.value, dane=enc(c)) for c in snap.cycles)
            s.add_all(NotatkaRow(id=int(r.note.id), ocena_id=r.evaluation_id, dane=enc(r)) for r in snap.notes)
            s.add_all(NieobecnoscRow(id=r.id, pracownik_id=r.employee_id, ocena_id=r.cycle_id, dane=enc(r))
                      for r in snap.absences)
            s.add_all(ZmianaTerminuRow(id=r.id, ocena_id=r.cycle_id, dane=enc(r)) for r in snap.deadline_changes)
            s.add_all(ZastepstwoRow(id=r.id, oceniajacy_id=r.evaluator_id, zastepca_id=r.deputy_id, od=r.od,
                                    do=r.do, dane=enc(r)) for r in snap.deputies)
            s.add_all(StanRow(klucz=k, dane=enc(v)) for k, v in snap.meta.items())
            s.commit()

    def load(self) -> Snapshot:
        dec = self.codec.loads
        with Session(self.engine) as s:
            def rows(t, order):
                return [dec(r.dane) for r in s.exec(select(t).order_by(order)).all()]
            return Snapshot(
                cycles=rows(OcenaRow, OcenaRow.id),
                notes=rows(NotatkaRow, NotatkaRow.id),
                absences=rows(NieobecnoscRow, NieobecnoscRow.id),
                deadline_changes=rows(ZmianaTerminuRow, ZmianaTerminuRow.id),
                deputies=rows(ZastepstwoRow, ZastepstwoRow.id),
                meta={r.klucz: dec(r.dane) for r in s.exec(select(StanRow)).all()},
            )
