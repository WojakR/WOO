"""Every 4xx in the contract's shape `ApiError {kod, komunikat, walidacje[]}` (docs/api.md, rule 5).
Domain errors carry Polish messages already; they are mapped to status codes here, once for all routes."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import FieldLocked, InvalidTransition, NotAuthorized, NotFound, ValidationError

from . import schemas as s


def api_error(status: int, kod: str, komunikat: str, walidacje: list[s.Walidacja] = ()) -> JSONResponse:
    body = s.ApiError(kod=kod, komunikat=komunikat, walidacje=list(walidacje))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


class ApiProblem(Exception):
    """A 4xx/5xx the domain does not raise itself (version conflict, blocked action with its checks,
    feature not available yet). Rendered as ApiError like every other error."""

    def __init__(self, status: int, kod: str, komunikat: str, walidacje: list[s.Walidacja] = ()):
        super().__init__(komunikat)
        self.status, self.kod, self.komunikat, self.walidacje = status, kod, komunikat, list(walidacje)


_SIMPLE = (
    (NotFound, 404, "NIE_ZNALEZIONO"),
    (NotAuthorized, 403, "BRAK_UPRAWNIEN"),
    (InvalidTransition, 409, "PRZEJSCIE_NIEDOZWOLONE"),
    (FieldLocked, 409, "POLE_ZABLOKOWANE"),
)


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, status, kod in _SIMPLE:
        app.add_exception_handler(
            exc_type, lambda request, exc, status=status, kod=kod: api_error(status, kod, str(exc)))

    @app.exception_handler(ApiProblem)
    async def _problem(request: Request, exc: ApiProblem):
        return api_error(exc.status, exc.kod, exc.komunikat, exc.walidacje)

    @app.exception_handler(ValidationError)
    async def _domain_validation(request: Request, exc: ValidationError):
        return api_error(422, "WALIDACJA", "Dane nie spełniają reguł oceny.",
                         [s.Walidacja(kod="WALIDACJA", waga=s.Waga.BLAD, komunikat=p) for p in exc.problems])

    @app.exception_handler(RequestValidationError)
    async def _bad_request(request: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors():
            field = str(err["loc"][-1]) if err.get("loc") else None
            problems.append(s.Walidacja(kod="BLEDNA_WARTOSC", pole=field, waga=s.Waga.BLAD,
                                        komunikat=f"Nieprawidłowa wartość pola „{field}”."))
        return api_error(422, "BLEDNE_ZAPYTANIE", "Zapytanie ma nieprawidłowe dane.", problems)
