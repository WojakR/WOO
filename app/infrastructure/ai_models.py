"""AI model adapters: off, local (Ollama via backend.llm) and api (not implemented yet).

The assistant falls back to templates/rules on AiUnavailable / AiInvalidOutput, but NOT on
NotImplementedError: choosing AI_MODE=api before the adapter exists fails loudly on purpose.
"""
from __future__ import annotations

import json
from typing import Iterator

from app.application.ports import AiInvalidOutput, AiModel, AiTask, AiUnavailable
from backend import config, llm


class OffModel:
    """AI disabled: every assistant feature uses its template / rule-based version."""

    name = "off"

    def available(self) -> bool:
        return False

    def complete_json(self, system: str, prompt: str, schema: dict, task: AiTask) -> dict:
        raise AiUnavailable("AI wyłączone (AI_MODE=off)")

    def complete_text(self, system: str, prompt: str, task: AiTask) -> str:
        raise AiUnavailable("AI wyłączone (AI_MODE=off)")

    def stream_text(self, system: str, prompt: str, task: AiTask) -> Iterator[str]:
        raise AiUnavailable("AI wyłączone (AI_MODE=off)")


class OllamaModel:
    """Local model through the Ollama HTTP API. Nothing leaves the machine."""

    def __init__(self, text_model: str | None = None, fast_model: str | None = None):
        self.text_model = text_model or config.AI_LOCAL_MODEL_TEXT
        self.fast_model = fast_model or config.AI_LOCAL_MODEL_FAST
        self.name = f"ollama/{self.text_model}"

    def _model(self, task: AiTask) -> str:
        return self.fast_model if task == "classify" else self.text_model

    def available(self) -> bool:
        return not config.LLM_MOCK

    def complete_json(self, system: str, prompt: str, schema: dict, task: AiTask) -> dict:
        try:
            raw = llm.ask_ollama(prompt, system, self._model(task), schema=schema)
        except llm.LocalModelUnavailable as e:
            raise AiUnavailable(str(e)) from e
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise AiInvalidOutput(f"Model nie zwrócił poprawnego JSON: {raw[:120]}") from e
        if not isinstance(data, dict):
            raise AiInvalidOutput("Model zwrócił JSON, który nie jest obiektem.")
        return data

    def complete_text(self, system: str, prompt: str, task: AiTask) -> str:
        try:
            return llm.ask_ollama(prompt, system, self._model(task), temperature=0.3)
        except llm.LocalModelUnavailable as e:
            raise AiUnavailable(str(e)) from e

    def stream_text(self, system: str, prompt: str, task: AiTask) -> Iterator[str]:
        try:
            yield from llm.stream_ollama(prompt, system, self._model(task))
        except llm.LocalModelUnavailable as e:
            raise AiUnavailable(str(e)) from e


class ApiModel:
    """External model through an API (Claude etc.), always with pseudonymisation. NOT IMPLEMENTED YET.

    To implement: call backend.llm.ask_llm / ask_llm_json (LiteLLM, LLM_MODELS) – the assistant already
    pseudonymises every prompt before it reaches the adapter.
    """

    name = "api"

    def available(self) -> bool:
        return True  # so the assistant actually calls it and the missing implementation is visible

    def complete_json(self, system: str, prompt: str, schema: dict, task: AiTask) -> dict:
        raise NotImplementedError("Adapter AI przez API nie jest jeszcze zaimplementowany (AI_MODE=api).")

    def complete_text(self, system: str, prompt: str, task: AiTask) -> str:
        raise NotImplementedError("Adapter AI przez API nie jest jeszcze zaimplementowany (AI_MODE=api).")

    def stream_text(self, system: str, prompt: str, task: AiTask) -> Iterator[str]:
        raise NotImplementedError("Adapter AI przez API nie jest jeszcze zaimplementowany (AI_MODE=api).")


def build_ai_model(mode: str | None = None) -> AiModel:
    mode = (mode or config.AI_MODE).lower()
    if mode == "off":
        return OffModel()
    if mode == "local":
        return OllamaModel()
    if mode == "api":
        return ApiModel()
    raise ValueError(f"Nieznany AI_MODE „{mode}” (dozwolone: off, local, api).")
