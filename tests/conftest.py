import os
from pathlib import Path

# Loaded by pytest before any test module, so backend.config never sees .env's real database.
_ROOT = Path(__file__).resolve().parent.parent
os.environ["LLM_MOCK"] = "1"
os.environ["DB_PATH"] = "data/test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{(_ROOT / 'data' / 'test.db').as_posix()}"
