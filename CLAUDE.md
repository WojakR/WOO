# CLAUDE.md

HackNation 2026 project (Python 3.11+). README.md (Polish) is the human guide.
Task: KPRM "Cyfrowy Asystent Ocen Okresowych" – institution, demo scenario and MVP use cases in `docs/task.md`.
This is `projekt/` inside a monorepo; the agent-coordination toolkit is in `../server/` (do not edit it for app work).
Run all commands below from `projekt/`.

## Run / test
- Setup: `pip install -r requirements.txt`, copy `.env.example` to `.env`
- Tests: `python -m pytest -q` (Windows: `py -m pytest -q`). Tests run with `LLM_MOCK=1`, no API keys needed.
- Demo UI: `streamlit run frontend/app.py`; API: `uvicorn backend.main:app --reload`

## Architecture
- `backend/llm.py` – the ONLY place that calls an LLM: `ask_llm()` / `ask_llm_json()` (LiteLLM) and `ask_ollama()` /
  `stream_ollama()` (local model). Never import litellm/openai/anthropic/requests-to-a-model elsewhere.
- AI suggestions (UC1, UC4, UC5, UC7): `app/application/assistant.py` (`AiSuggestionService`), prompts in
  `app/application/prompts/`, model adapters in `app/infrastructure/ai_models.py` (`AI_MODE` off|local|api; api raises
  `NotImplementedError` on purpose). Every feature must keep its no-AI fallback, pseudonymise prompts and validate the
  model's answer. Details: `docs/asystent.md`.
- `backend/parsers.py` – file parsing (PDF/XML/CSV/XLSX/OCR). Add new formats here.
- `backend/db.py` – SQLite access. Schema changes go in `init_db()`.
- `backend/main.py` – FastAPI endpoints. Keep them thin; logic lives in backend modules.
- `frontend/app.py` – Streamlit demo; imports backend functions directly (no HTTP), so it deploys as one app.
- `scripts/` – setup check, synthetic data generator.
- `app/` – onion core of the evaluation process (UC1–UC5): `app/domain/` pure Python (rules § 11, deadlines,
  cycle state machine with field locks; no fastapi/sqlite/litellm/backend imports – enforced by a test),
  `app/application/` use cases (`EvaluationService`) + ports (`typing.Protocol`), `app/infrastructure/` adapters
  (rule book from `backend.kprm`, in-memory repo, `FixedClock` for "przewiń czas").
- `backend/kprm.py` – the ONLY reader of domain data in `../server/data/kprm/` (criteria, sheets A/B/C, rules and
  deadlines, sample employees, knowledge base, sample evaluations). Path: `KPRM_DATA_DIR`. Never hard-code values
  that come from regulations (thresholds, deadlines, criteria lists) – read them from `kprm.rules()` etc.
- Deadlines (24 months, absences, criteria, re-evaluation, objection, change of position): rules, sources and the
  "longer than a month" boundary in `docs/terminy.md`; every dated KPRM example is a test.

## Rules
- Every new backend function gets a test in `tests/` that passes with `LLM_MOCK=1`.
- Never commit `.env`, keys or real personal data; use `scripts/gen_fake_data.py`.
- UI text in Polish. Code, identifiers and commit messages in English.
- Keep the demo path working: `main` must always run.
