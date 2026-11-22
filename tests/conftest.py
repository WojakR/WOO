import os
import sys
from pathlib import Path

# Loaded by pytest before any test module, so backend.config never sees .env's real database.
_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("LLM_MOCK", "1")
os.environ["AUTH_MODE"] = "demo"  # X-User-Id switcher; tests/test_auth.py switches to session itself
os.environ["EAKT_MODE"] = "off"  # tests export to a temporary directory explicitly
os.environ["EZD_MODE"] = "off"  # the same for the EZD registry
os.environ["DB_PATH"] = "data/test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{(_ROOT / 'data' / 'test.db').as_posix()}"
sys.path.insert(0, str(_ROOT))
