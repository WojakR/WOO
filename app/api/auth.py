"""Who is calling – the ONE place every router gets its user from (`current_user`, used via access.actor).
Permissions are still decided only by AccessPolicy (app/domain/access.py); this module only answers "who".

`AUTH_MODE` (backend/config.py):
- `demo`    – today's identity switcher: `X-User-Id` = employee id from pracownicy.json or `kadry`;
              no header = HR. `/api/auth/login` is off.
- `session` – login + password (hashlib.scrypt) -> signed HttpOnly cookie. `X-User-Id` is ignored,
              `/api/users` answers 404, every `/api/...` call without a valid session answers 401.

Accounts: table `accounts` (backend/db.py). Create them with
`python -m app.api.auth add <login> <employee_id|kadry> [--admin]` (asks for the password), or – demo only –
set AUTH_DEMO_PASSWORD and an empty table gets one account per employee (login = employee id) plus `kadry`."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from backend import config, db

from .errors import ApiProblem, api_error
from .state import HR, DemoState, get_state

COOKIE = "asystent_sesja"
# Reachable without a session in session mode (the login screen needs them)
PUBLIC_PATHS = {"/api/auth/login", "/api/auth/logout", "/api/auth/status"}
# Everything else under these prefixes needs a session in session mode
PROTECTED_PREFIXES = ("/api/", "/ask", "/upload", "/documents")
DEMO_ONLY_PATHS = {"/api/users"}

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_EPHEMERAL_KEY = secrets.token_bytes(32)  # used when SECRET_KEY is empty: sessions end with the process
MAX_FAILURES, FAILURE_WINDOW_S = 5, 15 * 60


@dataclass(frozen=True)
class SessionUser:
    login: str
    employee_id: str  # id from pracownicy.json or `kadry`
    admin: bool


_session_user: ContextVar[SessionUser | None] = ContextVar("session_user", default=None)


def session_mode() -> bool:
    return config.AUTH_MODE == "session"


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # unknown logins cost the same time as wrong passwords


# ---------------------------------------------------------------- signed cookie

def _key() -> bytes:
    return config.SECRET_KEY.encode() if config.SECRET_KEY else _EPHEMERAL_KEY


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _fingerprint(password_hash: str) -> str:
    """Changing the password (or deleting the account) ends its sessions."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def sign_session(acc: db.Account, now: float | None = None) -> str:
    exp = int((time.time() if now is None else now) + config.SESSION_HOURS * 3600)
    payload = _b64(json.dumps({"l": acc.login, "e": exp, "v": _fingerprint(acc.password_hash)}).encode())
    sig = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(cookie: str | None, now: float | None = None) -> SessionUser | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    good = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        data = json.loads(_unb64(payload))
        login, exp, ver = str(data["l"]), int(data["e"]), str(data["v"])
    except (ValueError, KeyError, TypeError):
        return None
    if exp < (time.time() if now is None else now):
        return None
    acc = db.get_account(login)
    if acc is None or not hmac.compare_digest(ver, _fingerprint(acc.password_hash)):
        return None
    return SessionUser(acc.login, acc.employee_id, acc.admin)


# ---------------------------------------------------------------- current user

def current_user(st: DemoState, x_user_id: str | None) -> str:
    """The caller's id for AccessPolicy: employee id from pracownicy.json or `kadry`.
    Every router goes through this (app/api/access.py re-exports it as `actor`)."""
    if session_mode():
        user = _session_user.get()
        if user is None:
            raise ApiProblem(401, "BRAK_SESJI", "Sesja wygasła lub nie zalogowano się. Zaloguj się ponownie.")
        who = user.employee_id
        if who != HR and (st.directory.get(who) is None or st.directory.get(who).removed_on):
            raise ApiProblem(403, "NIEZNANY_UZYTKOWNIK", "Konto nie jest powiązane z pracownikiem z kadr.")
        return who
    if x_user_id is None or x_user_id == HR:
        return HR
    if st.directory.get(x_user_id) is None or st.directory.get(x_user_id).removed_on:
        raise ApiProblem(403, "NIEZNANY_UZYTKOWNIK", "Nieznany użytkownik (nagłówek X-User-Id).")
    return x_user_id


class AuthMiddleware:
    """Pure ASGI: reads the session cookie once per request and exposes it to `current_user`
    (a context variable, so every existing router keeps its signature). In session mode it also
    answers 401 for protected paths without a session and 404 for the demo identity list."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        user = None
        if session_mode():
            path = scope.get("path", "")
            if path in DEMO_ONLY_PATHS:
                return await api_error(404, "NIE_ZNALEZIONO", "Lista tożsamości demo jest wyłączona.")(
                    scope, receive, send)
            user = read_session(_cookie(scope, COOKIE))
            if user is None and path.startswith(PROTECTED_PREFIXES) and path not in PUBLIC_PATHS:
                return await api_error(401, "BRAK_SESJI", "Zaloguj się, aby korzystać z aplikacji.")(
                    scope, receive, send)
        token = _session_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            _session_user.reset(token)


def _cookie(scope, name: str) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"cookie":
            for part in value.decode("latin-1").split(";"):
                k, _, v = part.strip().partition("=")
                if k == name:
                    return v
    return None


# ---------------------------------------------------------------- accounts

def create_account(login: str, password: str, employee_id: str, admin: bool = False) -> db.Account:
    return db.save_account(login.strip(), hash_password(password), employee_id, admin)


def ensure_demo_accounts(st: DemoState) -> int:
    """Demo convenience: empty table + AUTH_DEMO_PASSWORD -> an account per employee and `kadry` (admin)."""
    if not config.AUTH_DEMO_PASSWORD or db.count_accounts():
        return 0
    create_account(HR, config.AUTH_DEMO_PASSWORD, HR, admin=True)
    people = st.directory.all()
    for e in people:
        create_account(e.id, config.AUTH_DEMO_PASSWORD, e.id)
    return len(people) + 1


_failures: dict[str, list[float]] = {}


def _too_many_failures(login: str, now: float) -> bool:
    recent = [t for t in _failures.get(login, []) if now - t < FAILURE_WINDOW_S]
    _failures[login] = recent
    return len(recent) >= MAX_FAILURES


# ---------------------------------------------------------------- endpoints

router = APIRouter(prefix="/api/auth", tags=["sesja"])


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=120)
    haslo: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    tryb: str  # DEMO | SESSION
    zalogowany: bool
    login: str | None = None
    admin: bool = False


def _status(user: SessionUser | None) -> AuthStatus:
    if not session_mode():
        return AuthStatus(tryb="DEMO", zalogowany=False)
    return AuthStatus(tryb="SESSION", zalogowany=user is not None, login=user.login if user else None,
                      admin=bool(user and user.admin))


@router.get("/status", response_model=AuthStatus)
def status() -> AuthStatus:
    """Which identity mode the server runs in and whether this browser has a session (the UI starts here)."""
    return _status(_session_user.get())


@router.post("/login", response_model=AuthStatus)
def login(body: LoginIn, response: Response, st: DemoState = Depends(get_state)) -> AuthStatus:
    if not session_mode():
        raise ApiProblem(404, "NIE_ZNALEZIONO", "Logowanie jest wyłączone (AUTH_MODE=demo).")
    ensure_demo_accounts(st)
    name, now = body.login.strip(), time.time()
    if _too_many_failures(name, now):
        raise ApiProblem(429, "ZA_DUZO_PROB", "Zbyt wiele nieudanych prób. Spróbuj ponownie za kilkanaście minut.")
    acc = db.get_account(name)
    ok = verify_password(body.haslo, acc.password_hash if acc else _DUMMY_HASH)
    if acc is None or not ok:
        _failures.setdefault(name, []).append(now)
        raise ApiProblem(401, "BLEDNE_LOGOWANIE", "Nieprawidłowy login lub hasło.")
    _failures.pop(name, None)
    response.set_cookie(COOKIE, sign_session(acc, now), max_age=int(config.SESSION_HOURS * 3600), path="/",
                        httponly=True, samesite="lax", secure=config.SESSION_COOKIE_SECURE)
    return _status(SessionUser(acc.login, acc.employee_id, acc.admin))


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=config.SESSION_COOKIE_SECURE)
    response.status_code = 204
    return response


# ---------------------------------------------------------------- CLI

def _main(argv: list[str] | None = None) -> int:
    import argparse
    import getpass

    p = argparse.ArgumentParser(prog="python -m app.api.auth", description="Konta logowania (AUTH_MODE=session).")
    sub = p.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="załóż konto lub zmień hasło")
    add.add_argument("login")
    add.add_argument("employee_id", help="id z pracownicy.json albo 'kadry'")
    add.add_argument("--admin", action="store_true")
    rm = sub.add_parser("remove", help="usuń konto")
    rm.add_argument("login")
    args = p.parse_args(argv)
    if args.cmd == "remove":
        print("Usunięto." if db.delete_account(args.login) else "Nie ma takiego konta.")
        return 0
    if args.employee_id != HR and get_state().directory.get(args.employee_id) is None:
        print(f"Nieznany pracownik: {args.employee_id}")
        return 1
    password = getpass.getpass("Hasło: ")
    if not password or password != getpass.getpass("Powtórz hasło: "):
        print("Hasła są puste lub różne.")
        return 1
    create_account(args.login, password, args.employee_id, args.admin)
    print(f"Zapisano konto {args.login}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


def session_employee_id() -> str | None:
    """The employee id of the logged-in user of this request (session mode), else None."""
    user = _session_user.get()
    return user.employee_id if user else None


def admin_employee_ids() -> frozenset[str]:
    """Employees whose account has the admin flag – administrator's rights in AccessPolicy (session mode)."""
    if not session_mode():
        return frozenset()
    from sqlmodel import select

    with db.session() as s:
        return frozenset(a.employee_id for a in s.exec(select(db.Account).where(db.Account.admin)).all())
