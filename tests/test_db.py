import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, db  # noqa: E402


def test_uses_test_database():
    assert config.DATABASE_URL.endswith("data/test.db")


def test_init_db_is_idempotent():
    db.init_db()
    db.init_db()
