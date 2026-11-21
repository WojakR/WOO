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
