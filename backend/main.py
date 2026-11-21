"""API (FastAPI). Uruchom: uvicorn backend.main:app --reload  ->  http://localhost:8000/docs"""
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import config, db
from backend.llm import ask_llm
from backend.parsers import parse_file, to_llm_text

app = FastAPI(title="HackNation 2026 – API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
