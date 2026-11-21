import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, db  # noqa: E402


def test_uses_test_database():
    assert config.DATABASE_URL.endswith("data/test.db")


def test_save_and_list_document_roundtrip():
    doc_id = db.save_document("ocena.txt", "text", "treść", {"task": "t", "lista": [1, 2]})
    listed = db.list_documents(5)
    assert listed[0]["id"] == doc_id
    assert listed[0]["filename"] == "ocena.txt" and listed[0]["kind"] == "text"
    assert isinstance(listed[0]["created_at"], str)
    with db.session() as s:
        assert s.get(db.Document, doc_id).result == {"task": "t", "lista": [1, 2]}


def test_list_documents_newest_first_and_limit():
    a = db.save_document("a.txt", "text", "a")
    b = db.save_document("b.txt", "text", "b")
    ids = [d["id"] for d in db.list_documents(2)]
    assert ids == [b, a]


def test_init_db_is_idempotent():
    db.init_db()
    db.init_db()
