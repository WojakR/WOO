"""AI model adapters: off, local (Ollama via backend.llm) and api (an external model via backend.llm / LiteLLM).

The assistant falls back to templates/rules on AiUnavailable / AiInvalidOutput – a model that is down, has no key
or answers nonsense never stops the evaluation.
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
    """External model through an API (LLM_MODELS in .env, LiteLLM: e.g. anthropic/claude-…, openai/…, azure/…),
    with fallback down the list of models.

    Pseudonymised twice: the assistant masks the people of the evaluation before the prompt reaches the adapter
    ([OSOBA_n]), and backend.llm.ask_llm masks everyone in the employee directory, PESEL, e-mails and phones
    ([OSOBA_Kn], …) before anything leaves the application. The JSON schema of the task goes into the system
    prompt (providers differ in structured outputs); the assistant validates every answer anyway.
    """

    def __init__(self, models: list[str] | None = None):
        self.models = models or config.LLM_MODELS
        self.name = f"api/{self.models[0]}" if self.models else "api"

    def available(self) -> bool:
        return bool(self.models) and not config.LLM_MOCK

    def _ask(self, system: str, prompt: str, json_mode: bool, temperature: float) -> str:
        try:
            return llm.ask_llm(prompt, system=system, json_mode=json_mode, temperature=temperature)
        except Exception as e:  # noqa: BLE001 – no key, limit, network, provider error -> the no-AI version
            raise AiUnavailable(f"Model przez API nie odpowiedział: {type(e).__name__}: {str(e)[:200]}") from e

    def complete_json(self, system: str, prompt: str, schema: dict, task: AiTask) -> dict:
        system = (f"{system}\n\nOdpowiedz WYŁĄCZNIE jednym obiektem JSON zgodnym z tym schematem (bez komentarzy, "
                  f"bez bloku ```):\n{json.dumps(schema, ensure_ascii=False)}")
        raw = self._ask(system, prompt, True, 0.1).strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise AiInvalidOutput(f"Model nie zwrócił poprawnego JSON: {raw[:120]}") from e
        if not isinstance(data, dict):
            raise AiInvalidOutput("Model zwrócił JSON, który nie jest obiektem.")
        return data

    def complete_text(self, system: str, prompt: str, task: AiTask) -> str:
        return self._ask(system, prompt, False, 0.3)

    def stream_text(self, system: str, prompt: str, task: AiTask) -> Iterator[str]:
        yield self.complete_text(system, prompt, task)  # one chunk: the drafts' SSE works the same


def build_ai_model(mode: str | None = None) -> AiModel:
    mode = (mode or config.AI_MODE).lower()
    if mode == "off":
        return OffModel()
    if mode == "local":
        return OllamaModel()
    if mode == "api":
        return ApiModel()
    raise ValueError(f"Nieznany AI_MODE „{mode}” (dozwolone: off, local, api).")
