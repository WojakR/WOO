import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _secret(name: str, default: str = "") -> str:
    """Najpierw zmienna środowiskowa / .env, potem st.secrets (Streamlit Cloud)."""
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st

        if name in st.secrets:
            os.environ[name] = str(st.secrets[name])  # LiteLLM czyta klucze z env
            return str(st.secrets[name])
    except Exception:
        pass
    return default


for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OLLAMA_API_BASE"):
    _secret(_k)

LLM_MODELS = [m.strip() for m in _secret("LLM_MODELS", "openai/gpt-4o-mini").split(",") if m.strip()]
LLM_MOCK = _secret("LLM_MOCK", "0") == "1"
DB_PATH = ROOT / _secret("DB_PATH", "data/app.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
# SQLAlchemy URL; empty = SQLite file at DB_PATH. PostgreSQL: postgresql+psycopg://user:pass@host:5432/db
DATABASE_URL = _secret("DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}"
# Domain data (KPRM: criteria, sheets, rules, sample employees, knowledge base) lives in the monorepo's server/
KPRM_DATA_DIR = Path(_secret("KPRM_DATA_DIR", str(ROOT.parent / "server" / "data" / "kprm")))

# Assistant (AI suggestions): off = templates/rules only, local = Ollama, api = not implemented yet
AI_MODE = _secret("AI_MODE", "local").lower()
OLLAMA_URL = _secret("OLLAMA_API_BASE", "http://localhost:11434").rstrip("/")
_BIELIK = "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"
AI_LOCAL_MODEL_TEXT = _secret("AI_LOCAL_MODEL_TEXT", _BIELIK)  # drafts, conversation prep, HR partner
AI_LOCAL_MODEL_FAST = _secret("AI_LOCAL_MODEL_FAST", AI_LOCAL_MODEL_TEXT)  # note classification; a smaller model is fine
AI_TIMEOUT_S = float(_secret("AI_TIMEOUT_S", "60"))
AI_MIN_CONFIDENCE = float(_secret("AI_MIN_CONFIDENCE", "0.6"))

# Identity (app/api/auth.py): demo = X-User-Id from the top-bar switcher, session = login + signed cookie
AUTH_MODE = _secret("AUTH_MODE", "demo").lower()
SECRET_KEY = _secret("SECRET_KEY")  # signs the session cookie; empty = random per process (sessions end on restart)
SESSION_HOURS = float(_secret("SESSION_HOURS", "8"))
SESSION_COOKIE_SECURE = _secret("SESSION_COOKIE_SECURE", "0") == "1"  # 1 behind HTTPS
# session mode, empty accounts table: create one account per employee + `kadry` with this password (demo only)
AUTH_DEMO_PASSWORD = _secret("AUTH_DEMO_PASSWORD")
