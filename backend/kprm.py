"""Read-only access to the KPRM domain data in data/kprm (see data/kprm/README.md).

Everything that follows from regulations (criteria, sheets, thresholds, deadlines) is data,
not code: change the JSON files when the law changes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from backend.config import KPRM_DATA_DIR


def _load(name: str, data_dir: Path | None = None) -> dict:
    path = Path(data_dir or KPRM_DATA_DIR) / name
    if not path.is_file():
        raise FileNotFoundError(f"missing KPRM data file {path} (set KPRM_DATA_DIR?)")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache
def criteria() -> dict[str, dict]:
    """All 14 criteria keyed by id: {'id', 'nr', 'nazwa', 'wskazniki_behawioralne'}."""
    return {c["id"]: c for c in _load("kryteria.json")["kryteria"]}


@lru_cache
def sheets() -> dict:
    return _load("arkusze.json")


@lru_cache
def rules() -> dict:
    return _load("reguly.json")


@lru_cache
def employees() -> dict[str, dict]:
    return {e["id"]: e for e in _load("pracownicy.json")["pracownicy"]}


@lru_cache
def assistant_catalog() -> dict:
    """asystent.json: questions, development actions, HR-partner rules, templates (the no-AI fallback)."""
    return _load("asystent.json")


@lru_cache
def wellbeing() -> dict:
    """wellbeing.json: the burnout checklist (8 symptoms) for the review meeting."""
    return _load("wellbeing.json")


@lru_cache
def test_notes() -> dict:
    """notatki_testowe.json: hand-labelled notes for measuring classification accuracy."""
    return _load("notatki_testowe.json")


def mandatory_criteria(sheet: str) -> list[dict]:
    """Mandatory criteria of sheet A, B or C, in the order of the official form."""
    ids = sheets()["arkusze"][sheet]["kryteria_obowiazkowe"]
    return [criteria()[i] for i in ids]


def optional_criteria(sheet: str) -> list[dict]:
    """Criteria the evaluator may add (max sheets()['max_kryteriow_dodatkowych'])."""
    mandatory = set(sheets()["arkusze"][sheet]["kryteria_obowiazkowe"])
    return [c for c in criteria().values() if c["id"] not in mandatory]


def knowledge_docs() -> list[tuple[str, str]]:
    """(file name, text) of the knowledge base for RAG: regulations, KPRM guide, process docs."""
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted((KPRM_DATA_DIR / "wiedza").glob("*.md"))]


def example_evaluations() -> list[tuple[str, str]]:
    """(file name, text) of filled sample sheets from KPRM – few-shot style examples."""
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted((KPRM_DATA_DIR / "przyklady").glob("*.md"))]
