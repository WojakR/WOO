# CLAUDE.md

HackNation 2026 project (Python 3.11+). README.md (Polish) is the human guide.
Task: KPRM "Cyfrowy Asystent Ocen Okresowych" – institution, demo scenario and MVP use cases in `docs/task.md`.
Data model (entities, enums, computed values, 🟢/🟡 scope): `docs/model-danych.md` – read before changing `backend/db.py`.
This is `projekt/` inside a monorepo; the agent-coordination toolkit is in `../server/` (do not edit it for app work).
Run all commands below from `projekt/`.

## Run / test
- Setup: `pip install -r requirements.txt`, copy `.env.example` to `.env`
- Tests: `python -m pytest -q` (Windows: `py -m pytest -q`). Tests run with `LLM_MOCK=1`, no API keys needed.
- Demo UI: `streamlit run frontend/app.py`; API: `uvicorn backend.main:app --reload`

## Architecture
- `backend/llm.py` – the ONLY place that calls an LLM: use `ask_llm()` / `ask_llm_json()`. Never import litellm/openai/anthropic elsewhere.
- `backend/parsers.py` – file parsing (PDF/XML/CSV/XLSX/OCR). Add new formats here.
- `backend/db.py` – database access via SQLModel; engine from `DATABASE_URL` (empty = SQLite at `DB_PATH`,
  PostgreSQL = change the URL). Tables = SQLModel classes with `table=True` in this module; `init_db()` runs
  `create_all()` (no Alembic: adding columns to an existing table needs a fresh DB). ORM only, no dialect-specific SQL.
- `backend/main.py` – FastAPI endpoints. Keep them thin; logic lives in backend modules.
- `frontend/app.py` – Streamlit demo; imports backend functions directly (no HTTP), so it deploys as one app.
- `scripts/` – setup check, synthetic data generator.
- `backend/kprm.py` – the ONLY reader of domain data in `../server/data/kprm/` (criteria, sheets A/B/C, rules and
  deadlines, sample employees, knowledge base, sample evaluations). Path: `KPRM_DATA_DIR`. Never hard-code values
  that come from regulations (thresholds, deadlines, criteria lists) – read them from `kprm.rules()` etc.

## Rules
- Every new backend function gets a test in `tests/` that passes with `LLM_MOCK=1`.
- Never commit `.env`, keys or real personal data; use `scripts/gen_fake_data.py`.
- UI text in Polish. Code, identifiers and commit messages in English.
- Keep the demo path working: `main` must always run.
