import json
import sqlite3
from contextlib import contextmanager

from backend import config


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                kind TEXT,
                content TEXT,
                result TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")


def save_document(filename: str, kind: str, content: str, result=None) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO documents (filename, kind, content, result) VALUES (?, ?, ?, ?)",
            (filename, kind, content, json.dumps(result, ensure_ascii=False) if result is not None else None),
        )
        return cur.lastrowid


def list_documents(limit: int = 50):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, filename, kind, created_at FROM documents ORDER BY id DESC LIMIT ?", (limit,))]


init_db()
