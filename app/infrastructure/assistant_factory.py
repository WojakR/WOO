"""Builds the AI suggestion service from configuration (AI_MODE) and the KPRM data."""
from __future__ import annotations

from app.application.assistant import AiCatalog, AiSuggestionService
from app.application.ports import AiModel
from backend import config, kprm

from .ai_models import build_ai_model
from .kprm_adapter import kprm_rulebook
from .settings import load_office_settings


def kprm_catalog() -> AiCatalog:
    return AiCatalog.from_raw(kprm.assistant_catalog(), kprm.example_evaluations(),
                              profile=load_office_settings().employee_profile)


def build_assistant(mode: str | None = None, model: AiModel | None = None) -> AiSuggestionService:
    return AiSuggestionService(
        rules=kprm_rulebook(),
        model=model or build_ai_model(mode),
        catalog=kprm_catalog(),
        min_confidence=config.AI_MIN_CONFIDENCE,
    )
