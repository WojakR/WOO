"""Login and sessions (AUTH_MODE=session) – where the identity comes from; WHAT someone may do is still decided
only by AccessPolicy (app/domain/access.py).

- Accounts: table `konto` (backend/db.py) – login, scrypt hash, employee id (or `kadry`), admin flag.
  Create them with `python -m scripts.create_account <login> <employee_id> [--admin]`.
- Session: signed HttpOnly cookie `sesja` = login + expiry, HMAC-SHA256 with SECRET_KEY (.env).
- AUTH_MODE=demo (default): the identity switch of the demo (`X-User-Id`), no login.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlmodel import select

from backend import config, db

from .errors import ApiProblem

router = APIRouter(prefix="/api/auth", tags=["sesja"])
COOKIE = "sesja"
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

# the logged-in login of the request being served (set by `session_middleware`)
_session_login: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_login", default=None)


def session_mode() -> bool:
    return config.AUTH_MODE == "session"


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(got.hex(), digest)


# ---------------------------------------------------------------- signed cookie

def _key() -> bytes:
    if not config.SECRET_KEY:
        raise ApiProblem(500, "BRAK_SECRET_KEY", "Serwer nie ma ustawionego SECRET_KEY (plik .env).")
    return config.SECRET_KEY.encode()


def sign(login: str, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + config.SESSION_HOURS * 3600)
    payload = base64.urlsafe_b64encode(f"{login}|{expires}".encode()).decode()
    mac = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def unsign(token: str | None, now: float | None = None) -> str | None:
    """The login in a valid, unexpired token – else None (forged, expired, malformed)."""
    if not token or "." not in token or not config.SECRET_KEY:
        return None
    payload, mac = token.rsplit(".", 1)
    if not hmac.compare_digest(mac, hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        login, expires = base64.urlsafe_b64decode(payload.encode()).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return login if int(expires) > (time.time() if now is None else now) else None


# ---------------------------------------------------------------- accounts

def get_account(login: str) -> db.Account | None:
    with db.session() as s:
        return s.get(db.Account, login)


def create_account(login: str, password: str, employee_id: str, admin: bool = False) -> db.Account:
    if len(password) < 10:
        raise ValueError("Hasło musi mieć co najmniej 10 znaków.")
    with db.session() as s:
        if s.get(db.Account, login) is not None:
            raise ValueError(f"Konto {login} już istnieje.")
        acc = db.Account(login=login, password_hash=hash_password(password), employee_id=employee_id, admin=admin)
        s.add(acc)
        s.commit()
        return acc


def delete_accounts() -> None:
    """Tests only."""
    with db.session() as s:
        for acc in s.exec(select(db.Account)).all():
            s.delete(acc)
        s.commit()


def admin_employee_ids() -> frozenset[str]:
    """Employees whose account has the admin flag – they get the administrator's rights in AccessPolicy."""
    if not session_mode():
        return frozenset()
    with db.session() as s:
        return frozenset(a.employee_id for a in s.exec(select(db.Account).where(db.Account.admin)).all()
                         if a.active)


def session_employee_id() -> str | None:
    """The employee id of the logged-in user of this request (session mode), else None."""
    login = _session_login.get()
    acc = get_account(login) if login else None
    return acc.employee_id if acc and acc.active else None


async def session_middleware(request: Request, call_next):
    """Reads the session cookie once per request; `app.api.access.actor` uses the result."""
    token = _session_login.set(unsign(request.cookies.get(COOKIE)) if session_mode() else None)
    try:
        return await call_next(request)
    finally:
        _session_login.reset(token)


# ---------------------------------------------------------------- endpoints

class LoginIn(BaseModel):
    login: str
    haslo: str


class AuthStatusOut(BaseModel):
    tryb_logowania: str  # DEMO | SESJA
    zalogowany: bool
    login: str | None = None


@router.get("/status", response_model=AuthStatusOut)
def status() -> AuthStatusOut:
    """Public: lets the UI decide between the login screen and the demo identity switch."""
    if not session_mode():
        return AuthStatusOut(tryb_logowania="DEMO", zalogowany=True)
    login = _session_login.get()
    ok = login is not None and session_employee_id() is not None
    return AuthStatusOut(tryb_logowania="SESJA", zalogowany=ok, login=login if ok else None)


@router.post("/login", response_model=AuthStatusOut)
def login(body: LoginIn, response: Response) -> AuthStatusOut:
    if not session_mode():
        raise ApiProblem(404, "NIE_ZNALEZIONO", "Logowanie jest wyłączone (tryb demo).")
    acc = get_account(body.login.strip())
    # the same message and the same work for an unknown login and a wrong password
    ok = verify_password(body.haslo, acc.password_hash if acc else hash_password(secrets.token_hex(8)))
    if not (acc and acc.active and ok):
        raise ApiProblem(401, "BLEDNE_LOGOWANIE", "Nieprawidłowy login lub hasło.")
    response.set_cookie(COOKIE, sign(acc.login), httponly=True, samesite="strict", secure=config.COOKIE_SECURE,
                        max_age=int(config.SESSION_HOURS * 3600), path="/")
    return AuthStatusOut(tryb_logowania="SESJA", zalogowany=True, login=acc.login)


@router.post("/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response
