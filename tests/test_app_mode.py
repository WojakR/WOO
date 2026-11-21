"""T2: APP_MODE=production – system clock in Warsaw, no /api/demo/*, no demo seed; demo mode unchanged."""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

import app.api.state as state_mod
from app.api.state import build_state, reset_state
from app.infrastructure.clock import OFFICE_TZ, SystemClock
from backend import config
from backend.main import app

client = TestClient(app)


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(config, "APP_MODE", "production")
    st = reset_state(ai_mode="off")
    yield st
    monkeypatch.setattr(config, "APP_MODE", "demo")
    reset_state(today=date(2026, 6, 15), ai_mode="off")


def test_system_clock_is_today_in_warsaw():
    assert SystemClock().today() == datetime.now(OFFICE_TZ).date()


def test_production_uses_the_system_clock_and_no_seed(production):
    assert isinstance(production.clock, SystemClock)
    assert production.evaluations.cycles.list_all() == []
    assert build_state(scenario=True).evaluations.cycles.list_all() == []  # not even the demo scenario


def test_production_hides_the_demo_endpoints(production):
    assert client.get("/api/demo/clock").status_code == 404
    assert client.post("/api/demo/clock", json={"przesun_dni": 7}).status_code == 404
    assert client.post("/api/demo/reset").status_code == 404


def test_meta_tells_the_ui_the_mode(production):
    meta = client.get("/api/meta").json()
    assert meta["tryb_aplikacji"] == "PRODUKCJA"
    assert meta["dzis"] == datetime.now(OFFICE_TZ).date().isoformat()


def test_production_ignores_the_saved_demo_date(production):
    snap = state_mod.snapshot(production)
    snap.meta["dzis"] = date(2020, 1, 1)
    assert state_mod.restore(snap, ai_mode="off").clock.today() == datetime.now(OFFICE_TZ).date()


def test_demo_mode_keeps_the_clock_and_reset():
    reset_state(today=date(2026, 6, 15), ai_mode="off")
    assert client.get("/api/meta").json()["tryb_aplikacji"] == "DEMO"
    assert client.post("/api/demo/clock", json={"przesun_dni": 1}).json()["dzis"] == "2026-06-16"
