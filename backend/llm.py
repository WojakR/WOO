"""Jedna funkcja do LLM dla całego zespołu: ask_llm(). Fallback po liście modeli.

Pseudonimizacja jest WŁĄCZONA ZAWSZE: zanim prompt (i system prompt) wyjdzie do modelu, imiona i nazwiska
wszystkich osób z katalogu pracowników (+ `people` z wywołania), PESEL, e-maile i telefony zamieniamy na tokeny,
a w odpowiedzi przywracamy imiona i nazwiska. Tokeny tej warstwy mają własny prefiks `[OSOBA_K1]`, więc tokenów
`[OSOBA_1]` wstawionych wcześniej przez asystenta (app/application/assistant.py) nie ruszamy ani nie mylimy.
"""
import json
import logging
from functools import lru_cache
from typing import Iterable

from app.application.privacy import Pseudonymizer
from backend import config, kprm

log = logging.getLogger("llm")

GUARD_LABEL = "OSOBA_K"  # K = osoba z katalogu pracowników


@lru_cache(maxsize=1)
def _directory_people() -> tuple[tuple[str, str], ...]:
    return tuple((e.get("imie", ""), e.get("nazwisko", "")) for e in kprm.employees().values())


@lru_cache(maxsize=1)
def _directory_guard() -> Pseudonymizer:
    return Pseudonymizer(_directory_people(), label=GUARD_LABEL)


def _guard(people: Iterable[tuple[str, str]] | None = None) -> Pseudonymizer:
    """Everyone in the employee directory, plus `people` named by the caller (e.g. not in the directory yet)."""
    if not people:
        return _directory_guard()
    return Pseudonymizer(dict.fromkeys([*_directory_people(), *people]), label=GUARD_LABEL)


def ask_llm(prompt: str, system: str = "Odpowiadasz po polsku, zwięźle i konkretnie.",
            json_mode: bool = False, temperature: float = 0.2,
            people: Iterable[tuple[str, str]] | None = None) -> str:
    guard = _guard(people)
    prompt, system = guard.mask(prompt), guard.mask(system)
    if config.LLM_MOCK:
        # deliberately NOT unmasked: the echo shows exactly what would have left the application
        return json.dumps({"mock": True, "prompt": prompt[:80]}) if json_mode else f"[MOCK] {prompt[:120]}"
    return guard.unmask(_complete(system, prompt, json_mode, temperature))


def _complete(system: str, prompt: str, json_mode: bool, temperature: float) -> str:
    """The only place that sends text out (LiteLLM). Receives already pseudonymised text."""
    from litellm import completion  # import tutaj, żeby tryb MOCK działał szybko

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    errors = []
    for model in config.LLM_MODELS:
        try:
            kwargs = {"model": model, "messages": messages, "temperature": temperature, "timeout": 60}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = completion(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:  # limit, brak klucza, awaria -> następny model
            log.warning("Model %s nie zadziałał: %s", model, e)
            errors.append(f"{model}: {type(e).__name__}: {str(e)[:150]}")
    raise RuntimeError("Żaden model nie odpowiedział:\n" + "\n".join(errors))


def ask_llm_json(prompt: str, system: str = "Zwracasz WYŁĄCZNIE poprawny JSON.",
                 people: Iterable[tuple[str, str]] | None = None) -> dict:
    """Wygodne do ekstrakcji danych z dokumentów."""
    raw = ask_llm(prompt, system=system, json_mode=True, people=people)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


# ---------------------------------------------------------------- local model (Ollama HTTP API)

class LocalModelUnavailable(RuntimeError):
    """Ollama is not running, the model is not pulled, or it timed out."""


def _ollama_payload(model: str, system: str, prompt: str, schema: dict | None, stream: bool,
                    temperature: float) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": stream,
        "options": {"temperature": temperature},
    }
    if schema is not None:
        payload["format"] = schema  # Ollama structured outputs: the reply must match this JSON schema
    return payload


def ask_ollama(prompt: str, system: str, model: str, schema: dict | None = None,
               temperature: float = 0.1, timeout: float | None = None) -> str:
    """One chat completion from the local Ollama server. With `schema` the reply is JSON matching it."""
    import requests

    if config.LLM_MOCK:
        raise LocalModelUnavailable("LLM_MOCK=1: lokalny model wyłączony w testach")
    try:
        r = requests.post(f"{config.OLLAMA_URL}/api/chat", timeout=timeout or config.AI_TIMEOUT_S,
                          json=_ollama_payload(model, system, prompt, schema, False, temperature))
        r.raise_for_status()
        return r.json()["message"]["content"]
    except (requests.RequestException, KeyError, ValueError) as e:
        raise LocalModelUnavailable(f"Ollama ({model}) nie odpowiedziała: {type(e).__name__}: {str(e)[:150]}") from e


def stream_ollama(prompt: str, system: str, model: str, temperature: float = 0.3,
                  timeout: float | None = None):
    """Yields text chunks as the local model writes them (for SSE drafts)."""
    import requests

    if config.LLM_MOCK:
        raise LocalModelUnavailable("LLM_MOCK=1: lokalny model wyłączony w testach")
    try:
        with requests.post(f"{config.OLLAMA_URL}/api/chat", stream=True, timeout=timeout or config.AI_TIMEOUT_S,
                           json=_ollama_payload(model, system, prompt, None, True, temperature)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                part = json.loads(line)
                if chunk := part.get("message", {}).get("content"):
                    yield chunk
                if part.get("done"):
                    return
    except (requests.RequestException, ValueError) as e:
        raise LocalModelUnavailable(f"Ollama ({model}) nie odpowiedziała: {type(e).__name__}: {str(e)[:150]}") from e
