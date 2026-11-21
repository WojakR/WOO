"""Jedna funkcja do LLM dla całego zespołu: ask_llm(). Fallback po liście modeli."""
import json
import logging

from backend import config

log = logging.getLogger("llm")


def ask_llm(prompt: str, system: str = "Odpowiadasz po polsku, zwięźle i konkretnie.",
            json_mode: bool = False, temperature: float = 0.2) -> str:
    if config.LLM_MOCK:
        return json.dumps({"mock": True, "prompt": prompt[:80]}) if json_mode else f"[MOCK] {prompt[:120]}"

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


def ask_llm_json(prompt: str, system: str = "Zwracasz WYŁĄCZNIE poprawny JSON.") -> dict:
    """Wygodne do ekstrakcji danych z dokumentów."""
    raw = ask_llm(prompt, system=system, json_mode=True)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)
