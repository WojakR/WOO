"""Login and sessions (app/api/auth.py): AUTH_MODE=session replaces the X-User-Id switcher;
permissions are still AccessPolicy's. Other tests run in the default demo mode."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import auth
from app.api.state import reset_state
from backend import config, db
from backend.main import app

EMP, BOSS, OTHER = "grzegorz.wzor", "henryk.pryncypal", "janina.nowak"
PASSWORD = "Tajne-haslo-1"


@pytest.fixture
def st():
    return reset_state(today=date(2026, 6, 15), ai_mode="off")


@pytest.fixture
def session_mode(monkeypatch, st):
    monkeypatch.setattr(config, "AUTH_MODE", "session")
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(config, "AUTH_DEMO_PASSWORD", "")
    auth._failures.clear()
    for login in (EMP, BOSS, OTHER, "kadry"):
        auth.create_account(login, PASSWORD, login, admin=login == "kadry")
    yield st
    for login in (EMP, BOSS, OTHER, "kadry"):
        db.delete_account(login)


def logged_in(login: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"login": login, "haslo": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def eid(st, employee: str) -> int:
    return int(st.evaluations.cycles.find_open_for(employee).id)


# ---------------------------------------------------------------- passwords and cookies

def test_password_hash_is_salted_scrypt_and_verifies():
    a, b = auth.hash_password("x"), auth.hash_password("x")
    assert a.startswith("scrypt$") and a != b
    assert auth.verify_password("x", a) and not auth.verify_password("y", a)
    assert not auth.verify_password("x", "garbage")


def test_tampered_or_expired_session_is_rejected(session_mode):
    acc = db.get_account(EMP)
    cookie = auth.sign_session(acc)
    assert auth.read_session(cookie).employee_id == EMP
    payload, sig = cookie.rsplit(".", 1)
    forged = auth._b64(auth._unb64(payload).replace(EMP.encode(), BOSS.encode())) + "." + sig
    assert auth.read_session(forged) is None
    assert auth.read_session(auth.sign_session(acc, now=0)) is None  # expired long ago


# ---------------------------------------------------------------- login / logout

def test_correct_login_sets_an_httponly_cookie_and_me_follows_the_session(session_mode):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"login": EMP, "haslo": PASSWORD})
    assert r.status_code == 200 and r.json()["zalogowany"] is True
    set_cookie = r.headers["set-cookie"]
    assert auth.COOKIE in set_cookie and "HttpOnly" in set_cookie and "samesite=lax" in set_cookie.lower()
    me = c.get("/api/me")
    assert me.status_code == 200
    assert (me.json()["pracownik"]["imie"], me.json()["pracownik"]["nazwisko"]) == ("Grzegorz", "Wzór")


def test_wrong_password_and_unknown_login_are_401(session_mode):
    c = TestClient(app)
    for body in ({"login": EMP, "haslo": "zle"}, {"login": "nikt", "haslo": PASSWORD}):
        r = c.post("/api/auth/login", json=body)
        assert r.status_code == 401 and r.json()["kod"] == "BLEDNE_LOGOWANIE"
        assert auth.COOKIE not in r.headers.get("set-cookie", "")


def test_repeated_failures_are_throttled(session_mode):
    c = TestClient(app)
    for _ in range(auth.MAX_FAILURES):
        c.post("/api/auth/login", json={"login": EMP, "haslo": "zle"})
    assert c.post("/api/auth/login", json={"login": EMP, "haslo": PASSWORD}).status_code == 429


def test_logout_ends_the_session(session_mode):
    c = logged_in(EMP)
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/me").status_code == 401


def test_status_tells_the_ui_the_mode(session_mode):
    assert TestClient(app).get("/api/auth/status").json() == {
        "tryb": "SESSION", "zalogowany": False, "login": None, "admin": False}
    assert logged_in("kadry").get("/api/auth/status").json()["admin"] is True


# ---------------------------------------------------------------- no session, no header trick

def test_no_session_is_401(session_mode):
    c = TestClient(app)
    for path in ("/api/me", "/api/dashboard", f"/api/evaluations/{eid(session_mode, EMP)}"):
        r = c.get(path)
        assert r.status_code == 401 and r.json()["kod"] == "BRAK_SESJI"


def test_x_user_id_header_is_ignored_in_session_mode(session_mode):
    anon = TestClient(app)
    assert anon.get("/api/me", headers={"X-User-Id": BOSS}).status_code == 401
    assert anon.get("/api/me", headers={"X-User-Id": "kadry"}).status_code == 401
    c = logged_in(EMP)  # logged in as the evaluated person, pretending to be the boss
    me = c.get("/api/me", headers={"X-User-Id": BOSS}).json()
    assert me["pracownik"]["imie"] == "Grzegorz" and me["czy_oceniajacy"] is False


def test_demo_identity_list_is_404_in_session_mode(session_mode):
    assert logged_in(EMP).get("/api/users").status_code == 404


def test_evaluated_person_does_not_see_someone_elses_evaluation(session_mode):
    c = logged_in(EMP)
    assert c.get(f"/api/evaluations/{eid(session_mode, EMP)}").status_code == 200
    assert c.get(f"/api/evaluations/{eid(session_mode, OTHER)}").status_code == 403
    # ... and the header does not help
    assert c.get(f"/api/evaluations/{eid(session_mode, OTHER)}", headers={"X-User-Id": "kadry"}).status_code == 403


def test_evaluator_session_gets_evaluator_actions(session_mode):
    r = logged_in(BOSS).get(f"/api/evaluations/{eid(session_mode, EMP)}")
    assert r.status_code == 200 and r.json()["dozwolone_akcje"]


def test_demo_accounts_are_created_for_an_empty_table(session_mode, monkeypatch):
    for login in (EMP, BOSS, OTHER, "kadry"):
        db.delete_account(login)
    monkeypatch.setattr(config, "AUTH_DEMO_PASSWORD", "pokaz")
    try:
        r = TestClient(app).post("/api/auth/login", json={"login": BOSS, "haslo": "pokaz"})
        assert r.status_code == 200
        assert db.get_account("kadry").admin is True
    finally:
        for login in ["kadry", *(e.id for e in session_mode.directory.all())]:
            db.delete_account(login)


# ---------------------------------------------------------------- demo mode (default) unchanged

def test_demo_mode_keeps_the_switcher_and_has_no_login(st):
    c = TestClient(app)
    assert config.AUTH_MODE == "demo"
    assert c.get("/api/users").status_code == 200
    assert c.get("/api/me", headers={"X-User-Id": EMP}).json()["pracownik"]["imie"] == "Grzegorz"
    assert c.get("/api/auth/status").json()["tryb"] == "DEMO"
    assert c.post("/api/auth/login", json={"login": EMP, "haslo": PASSWORD}).status_code == 404
