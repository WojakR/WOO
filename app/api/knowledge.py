"""Knowledge base in the app (spec, point 4): the user manual and the text of the regulations.

GET /api/knowledge                 – list (manual first, then regulations and KPRM materials)
GET /api/knowledge/search?q=...    – full-text search on the server (fragments with the nearest heading)
GET /api/knowledge/{slug}          – one document as Markdown (404 for an unknown slug)
Texts: server/data/kprm/wiedza/*.md (read by backend/kprm.py) + docs/podrecznik.md (this project's manual).
The UI renders Markdown itself and never inserts HTML from it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

from app.domain.errors import NotFound
from backend import kprm

router = APIRouter(prefix="/api/knowledge", tags=["pomoc"])

DOCS = Path(__file__).resolve().parents[2] / "docs"
MANUAL = DOCS / "podrecznik.md"
TUTORIAL = DOCS / "samouczek.md"  # "Pierwsze kroki" – first in the help list
KIND = {  # document -> group shown in the help list
    "samouczek": "PODRECZNIK", "podrecznik": "PODRECZNIK",
    "rozporzadzenie-oceny-okresowe-2016": "PRZEPISY", "ustawa-o-sluzbie-cywilnej": "PRZEPISY",
    "ustawa-sc-wyciag-oceny": "PRZEPISY",
}
MIN_QUERY = 3
MAX_HITS = 30


def slugify(text: str) -> str:
    """Anchor of a heading – the same rule as in frontend/web/js/views/help.js."""
    text = unicodedata.normalize("NFD", text.casefold().replace("ł", "l"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


@dataclass(frozen=True)
class Doc:
    slug: str
    title: str
    kind: str
    text: str


@lru_cache
def _docs() -> tuple[Doc, ...]:
    raw = []
    for slug, path in (("samouczek", TUTORIAL), ("podrecznik", MANUAL)):
        if path.is_file():
            raw.append((slug, path.read_text(encoding="utf-8")))
    raw += [(Path(name).stem, text) for name, text in kprm.knowledge_docs()]
    out = []
    for slug, text in raw:
        first = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), slug)
        out.append(Doc(slug, first, KIND.get(slug, "MATERIALY"), text))
    order = {"PODRECZNIK": 0, "PRZEPISY": 1, "MATERIALY": 2}
    return tuple(sorted(out, key=lambda d: (order[d.kind], d.slug != "samouczek", d.title)))


def _doc(slug: str) -> Doc:
    doc = next((d for d in _docs() if d.slug == slug), None)
    if doc is None:
        raise NotFound(f"Nie ma dokumentu „{slug}” w bazie wiedzy.")
    return doc


@router.get("")
def knowledge_list() -> list[dict]:
    return [{"slug": d.slug, "tytul": d.title, "rodzaj": d.kind, "znaki": len(d.text)} for d in _docs()]


def search(q: str) -> list[dict]:
    needle = " ".join(q.split()).casefold()
    hits = []
    for d in _docs():
        lines = d.text.splitlines()
        heading = d.title
        count = 0
        first = None
        for line in lines:
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
            pos = line.casefold().find(needle)
            if pos < 0:
                continue
            count += line.casefold().count(needle)
            if first is None:
                start = max(0, pos - 80)
                frag = line[start:pos + len(needle) + 120].strip()
                first = (("…" if start else "") + frag + ("…" if pos + len(needle) + 120 < len(line) else ""), heading)
        if first:
            hits.append({"slug": d.slug, "tytul": d.title, "rodzaj": d.kind, "fragment": first[0],
                         "naglowek": first[1], "kotwica": slugify(first[1]), "trafienia": count})
    hits.sort(key=lambda h: (h["rodzaj"] != "PODRECZNIK", -h["trafienia"]))
    return hits[:MAX_HITS]


@router.get("/search")
def knowledge_search(q: str = "") -> dict:
    if len(q.strip()) < MIN_QUERY:
        return {"q": q, "wyniki": [], "komunikat": f"Wpisz co najmniej {MIN_QUERY} znaki."}
    return {"q": q, "wyniki": search(q)}


@router.get("/{slug}")
def knowledge_doc(slug: str) -> dict:
    d = _doc(slug)
    headings = [{"poziom": len(m.group(1)), "tekst": m.group(2).strip(), "kotwica": slugify(m.group(2))}
                for m in re.finditer(r"^(#{1,4})\s+(.+)$", d.text, re.M)]
    return {"slug": d.slug, "tytul": d.title, "rodzaj": d.kind, "tresc": d.text, "naglowki": headings}
