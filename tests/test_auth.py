"""T1: login and sessions (AUTH_MODE=session). Rights still come from AccessPolicy only."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import auth
from app.api.state import reset_state
from backend import config
from backend.main import app

EMP, BOSS, OTHER = "grzegorz.wzor", "henryk.pryncypal", "janina.nowak"
PASSWORD = "bardzo-tajne-haslo"


@pytest.fixture
def session_mode(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "session")
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret-key")
    auth.delete_accounts()
    auth.create_account("gwzor", PASSWORD, EMP)
    auth.create_account("hpryncypal", PASSWORD, BOSS)
    auth.create_account("kadry", PASSWORD, "kadry")
    st = reset_state(today=date(2026, 6, 15), ai_mode="off")
    yield st
    auth.delete_accounts()


def login(client, who, password=PASSWORD):
    return client.post("/api/auth/login", json={"login": who, "haslo": password})


def eid(st, employee):
    return int(st.evaluations.cycles.find_open_for(employee).id)


def test_password_hash_is_salted_and_verifies():
    a, b = auth.hash_password("abc"), auth.hash_password("abc")
    assert a != b and auth.verify_password("abc", a) and not auth.verify_password("abd", a)


def test_good_login_sets_an_httponly_cookie_and_me_follows_the_session(session_mode):
    c = TestClient(app)
    r = login(c, "gwzor")
    assert r.status_code == 200 and r.json()["zalogowany"]
    assert "httponly" in r.headers["set-cookie"].lower()
    me = c.get("/api/me").json()
    assert me["pracownik"]["imie"] == "Grzegorz"
    assert c.get("/api/auth/status").json() == {"tryb_logowania": "SESJA", "zalogowany": True, "login": "gwzor"}


def test_wrong_password_and_unknown_login_get_the_same_401(session_mode):
    c = TestClient(app)
    bad, unknown = login(c, "gwzor", "zle-haslo-123"), login(c, "nikt", "zle-haslo-123")
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["komunikat"] == unknown.json()["komunikat"]
    assert c.get("/api/me").status_code == 401


def test_no_session_is_401(session_mode):
    r = TestClient(app).get("/api/dashboard")
    assert r.status_code == 401 and r.json()["kod"] == "BRAK_SESJI"


def test_x_user_id_header_is_ignored_in_session_mode(session_mode):
    c = TestClient(app)
    assert c.get("/api/me", headers={"X-User-Id": BOSS}).status_code == 401
    login(c, "gwzor")
    me = c.get("/api/me", headers={"X-User-Id": BOSS}).json()
    assert me["pracownik"]["imie"] == "Grzegorz"  # the cookie wins, the header does nothing


def test_users_switch_is_gone_in_session_mode(session_mode):
    assert TestClient(app).get("/api/users").status_code == 404


def test_evaluated_person_does_not_see_someone_elses_evaluation(session_mode):
    c = TestClient(app)
    login(c, "gwzor")
    assert c.get(f"/api/evaluations/{eid(session_mode, EMP)}").status_code == 200
    assert c.get(f"/api/evaluations/{eid(session_mode, OTHER)}").status_code == 403


def test_forged_or_expired_cookie_is_rejected(session_mode):
    token = auth.sign("kadry")
    assert auth.unsign(token) == "kadry"
    assert auth.unsign(token[:-1] + ("0" if token[-1] != "0" else "1")) is None
    assert auth.unsign(auth.sign("kadry", now=0)) is None  # expired long ago
    c = TestClient(app)
    c.cookies.set(auth.COOKIE, "a2FkcnF8OTk5OTk5OTk5OQ==.deadbeef")
    assert c.get("/api/me").status_code == 401


def test_logout_ends_the_session(session_mode):
    c = TestClient(app)
    login(c, "kadry")
    assert c.get("/api/me").json()["rola"] == "KADRY"
    assert c.post("/api/auth/logout").status_code == 204
    c.cookies.clear()
    assert c.get("/api/me").status_code == 401


def test_admin_flag_gives_read_access_to_the_whole_office(session_mode):
    auth.create_account("admin.gw", PASSWORD, EMP, admin=True)
    c = TestClient(app)
    login(c, "admin.gw")
    assert c.get(f"/api/evaluations/{eid(session_mode, OTHER)}").status_code == 200


def test_demo_mode_keeps_the_identity_switch():
    reset_state(today=date(2026, 6, 15), ai_mode="off")
    c = TestClient(app)
    assert c.get("/api/auth/status").json()["tryb_logowania"] == "DEMO"
    assert c.get("/api/users").status_code == 200
    assert c.get("/api/me", headers={"X-User-Id": BOSS}).json()["pracownik"]["imie"] == "Henryk"
    assert c.post("/api/auth/login", json={"login": "x", "haslo": "y"}).status_code == 404
