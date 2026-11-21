"""API (FastAPI) + aplikacja webowa. Uruchom: uvicorn backend.main:app --reload
->  http://localhost:8000 (interfejs),  http://localhost:8000/docs (API)"""
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.admin import router as admin_router
from app.api.audit import audit_middleware
from app.api.audit import router as audit_router
from app.api.auth import AuthMiddleware
from app.api.auth import router as auth_router
from app.api.deadline_requests import router as deadline_requests_router
from app.api.employees import router as employees_router
from app.api.errors import install_error_handlers
from app.api.evaluations import router as evaluations_router
from app.api.evaluator_changes import router as evaluator_changes_router
from app.api.history import router as hr_tasks_router
from app.api.routes import router as api_router
from app.api.notes import router as notes_router
from app.api.deputies import router as deputies_router
from app.api.office import router as office_router
from app.api.reminders import router as reminders_router
from app.api.wellbeing import router as wellbeing_router
from app.api.admin_rcp import router as rcp_router
from app.api.reports import router as reports_router
from app.api.knowledge import router as knowledge_router
from app.api.archive import router as archive_router
from app.api.eakt import router as eakt_router
from app.api.legacy_import import router as legacy_router
from app.api.state import save_state
from backend import config, db
from backend.llm import ask_llm
from backend.parsers import parse_file, to_llm_text

app = FastAPI(title="HackNation 2026 – API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)  # login / logout / mode (AUTH_MODE)
app.include_router(api_router)  # contract endpoints /api/... (docs/api.md)
app.include_router(notes_router)
app.include_router(deputies_router)  # zastępstwa
app.include_router(deadline_requests_router)  # zmiana terminu (art. 81 ust. 8)
app.include_router(reminders_router)  # przypomnienia
app.include_router(employees_router)  # widok Pracownicy
app.include_router(evaluator_changes_router)  # zmiana oceniającego
app.include_router(evaluations_router)  # sheet, dashboard, HR partner, demo – used by the web UI
app.include_router(admin_router)  # HR import
app.include_router(hr_tasks_router)  # consequences of evaluations (HR tasks)
app.include_router(audit_router)  # dziennik zmian (HR)
app.include_router(office_router)  # regulation requirements, visibility, AI switches (admin)
app.include_router(wellbeing_router)  # burnout checklist at the review meeting (working material)
app.include_router(rcp_router)  # working-time import (RCP) for the HR partner
app.include_router(reports_router)  # progress, outcomes, training needs
app.include_router(knowledge_router)  # "Pomoc": manual + regulations
app.include_router(archive_router)  # frozen closed evaluations, retention review
app.include_router(eakt_router)  # e-Akt export retry
app.include_router(legacy_router)  # import of old evaluations (PDF)
install_error_handlers(app)


_CHANGES = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def persist_after_changes(request, call_next):
    """Every successful change to /api/... is written to the database (app/infrastructure/sql_store.py)."""
    response = await call_next(request)
    path = request.url.path
    if (request.method in _CHANGES and path.startswith("/api/") and not path.startswith("/api/auth/")
            and response.status_code < 400):
        save_state()
    return response


# dziennik zmian – inside the auth middleware (needs the user), around the state change itself
app.middleware("http")(audit_middleware)


# Added last = outermost: the session is known before any other middleware or router runs (app/api/auth.py)
app.add_middleware(AuthMiddleware)


class AskIn(BaseModel):
    prompt: str
    context: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "models": config.LLM_MODELS, "mock": config.LLM_MOCK}


@app.post("/ask")
def ask(body: AskIn):
    prompt = body.prompt if not body.context else f"Kontekst:\n{body.context}\n\nPytanie: {body.prompt}"
    return {"answer": ask_llm(prompt)}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    kind, content = parse_file(data, file.filename)
    text = to_llm_text(kind, content)
    doc_id = db.save_document(file.filename, kind, text)
    return {"id": doc_id, "kind": kind, "preview": text[:2000]}


@app.get("/documents")
def documents():
    return db.list_documents()


# Web UI (frontend/web) – mounted last so it never shadows API routes
WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / "web"


class _RevalidatedStatic(StaticFiles):
    """Browsers revalidate (ETag) on every load, so a new UI version shows up without a hard refresh."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


if WEB_DIR.is_dir():
    app.mount("/", _RevalidatedStatic(directory=WEB_DIR, html=True), name="web")
