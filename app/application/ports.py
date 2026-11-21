"""Ports the use cases depend on. Adapters live in app/infrastructure (or backend/ later, e.g. SQLite)."""
from __future__ import annotations

from datetime import date
from typing import Iterator, Literal, Protocol

from app.domain.cycle import EvaluationCycle
from app.domain.employee import Employee


class CycleRepository(Protocol):
    def get(self, cycle_id: str) -> EvaluationCycle | None: ...

    def save(self, cycle: EvaluationCycle) -> None: ...

    def list_all(self) -> list[EvaluationCycle]: ...

    def find_open_for(self, employee_id: str) -> EvaluationCycle | None:
        """The employee's cycle that is not yet acknowledged, if any."""
        ...

    def delete(self, cycle_id: str) -> None: ...


class EmployeeDirectory(Protocol):
    def get(self, employee_id: str) -> Employee | None: ...


class Clock(Protocol):
    def today(self) -> date: ...


class Notifier(Protocol):
    """Sends a message outside the application (e-mail). Adapters: app/infrastructure/notifier.py."""

    def send(self, to: str, subject: str, body: str) -> None: ...


# ---------------------------------------------------------------- AI model

AiTask = Literal["classify", "text"]  # classify = short JSON (may use a smaller model), text = drafts


class AiUnavailable(RuntimeError):
    """The model cannot answer now (off, not running, timeout). Callers fall back to templates/rules."""


class AiInvalidOutput(ValueError):
    """The model answered, but the answer failed validation (bad JSON, labels outside the list, …)."""


class AiModel(Protocol):
    """A language model the assistant may use. Adapters: off, local (Ollama), api (not implemented)."""

    name: str

    def available(self) -> bool: ...

    def complete_json(self, system: str, prompt: str, schema: dict, task: AiTask) -> dict:
        """Reply as JSON matching `schema`. Raises AiUnavailable / AiInvalidOutput."""
        ...

    def complete_text(self, system: str, prompt: str, task: AiTask) -> str: ...

    def stream_text(self, system: str, prompt: str, task: AiTask) -> Iterator[str]: ...
