"""Database access (SQLModel). The engine comes from `config.DATABASE_URL`:
SQLite locally, PostgreSQL by changing the URL only. Keep queries ORM-only (no dialect-specific SQL)."""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from backend import config

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=_connect_args)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: int | None = Field(default=None, primary_key=True)
    filename: str | None = None
    kind: str | None = None
    content: str | None = Field(default=None, sa_column=Column(Text))
    result: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


@contextmanager
def session():
    with Session(engine, expire_on_commit=False) as s:
        yield s


def init_db():
    """Creates missing tables. New tables = new SQLModel classes with table=True in this module."""
    SQLModel.metadata.create_all(engine)


def save_document(filename: str, kind: str, content: str, result=None) -> int:
    with session() as s:
        doc = Document(filename=filename, kind=kind, content=content, result=result)
        s.add(doc)
        s.commit()
        return doc.id


def list_documents(limit: int = 50):
    with session() as s:
        docs = s.exec(select(Document).order_by(Document.id.desc()).limit(limit)).all()
        return [
            {"id": d.id, "filename": d.filename, "kind": d.kind,
             "created_at": d.created_at.isoformat(sep=" ", timespec="seconds")}
            for d in docs
        ]


init_db()
