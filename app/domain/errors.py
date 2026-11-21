"""Domain errors. Messages (`str(err)`) are in Polish because they are shown to users."""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all business-rule violations."""


class ValidationError(DomainError):
    """One or more input values break the rules; `problems` lists every one of them."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class InvalidTransition(DomainError):
    """The requested step is not allowed in the cycle's current status."""


class FieldLocked(DomainError):
    """The field cannot be edited in the cycle's current status."""


class NotAuthorized(DomainError):
    """The acting person is not allowed to perform this step."""


class NotFound(DomainError):
    """A referenced cycle or employee does not exist."""
