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


class Account(SQLModel, table=True):
    """Login account (app/api/auth.py). `employee_id` = id from pracownicy.json or `kadry` (HR)."""
    __tablename__ = "accounts"

    login: str = Field(primary_key=True)
    password_hash: str  # scrypt$n$r$p$salt_hex$hash_hex (auth.hash_password)
    employee_id: str
    admin: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class AuditEntry(SQLModel, table=True):
    """Dziennik zmian – append-only (app/infrastructure/audit_log.py never updates or deletes a row)."""
    __tablename__ = "dziennik_zmian"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=_utcnow, index=True)  # UTC
    user_id: str = Field(index=True)
    evaluation_id: int | None = Field(default=None, index=True)
    action: str  # e.g. AKCJA_ZATWIERDZ_OCENE, ZMIANA_POLA, NOTATKA_DODANA, POBRANIE_PDF
    field: str | None = None
    before: str | None = Field(default=None, sa_column=Column(Text))
    after: str | None = Field(default=None, sa_column=Column(Text))


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


def get_account(login: str) -> Account | None:
    with session() as s:
        return s.get(Account, login)


def count_accounts() -> int:
    with session() as s:
        return len(s.exec(select(Account.login)).all())


def save_account(login: str, password_hash: str, employee_id: str, admin: bool = False) -> Account:
    """Creates or replaces the account `login`."""
    with session() as s:
        acc = s.get(Account, login) or Account(login=login, password_hash=password_hash, employee_id=employee_id)
        acc.password_hash, acc.employee_id, acc.admin = password_hash, employee_id, admin
        s.add(acc)
        s.commit()
        return acc


def delete_account(login: str) -> bool:
    with session() as s:
        acc = s.get(Account, login)
        if acc is None:
            return False
        s.delete(acc)
        s.commit()
        return True


init_db()
