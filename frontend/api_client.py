"""The Streamlit app talks to the backend only through the /api contract (docs/api.md) – the same endpoints
as the web UI, so every rule, permission and saved record comes from the server and its database.

Transport:
- API_URL set (e.g. http://localhost:8000) -> HTTP to a running `uvicorn backend.main:app` (shared with the web UI);
- otherwise the FastAPI app runs in-process (fastapi TestClient): same routes, middleware and DB persistence,
  no second server needed for the demo.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

import streamlit as st


class ApiError(Exception):
    """Body of every 4xx/5xx from the server: {kod, komunikat, walidacje[]}."""

    def __init__(self, status: int, body: dict | None):
        body = body or {}
        self.status = status
        self.kod = body.get("kod", str(status))
        self.komunikat = body.get("komunikat") or body.get("detail") or f"Błąd serwera ({status})."
        self.walidacje = body.get("walidacje") or []
        super().__init__(self.komunikat)

    @property
    def messages(self) -> list[str]:
        return [self.komunikat] + [w.get("komunikat", "") for w in self.walidacje if w.get("komunikat")]


@st.cache_resource(show_spinner=False)
def _transport():
    url = os.environ.get("API_URL", "").rstrip("/")
    if url:
        import requests

        session = requests.Session()

        def call(method: str, path: str, headers: dict, **kw):
            return session.request(method, url + path, headers=headers, timeout=120, **kw)

        return call
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app, raise_server_exceptions=False)

    def call(method: str, path: str, headers: dict, **kw):
        return client.request(method, path, headers=headers, **kw)

    return call


class Api:
    def __init__(self, user_id: str):
        self.user_id = user_id

    # ---- plumbing --------------------------------------------------------------------------------
    def _req(self, method: str, path: str, json: Any = None, params: dict | None = None, raw: bool = False):
        r = _transport()(method, "/api" + path, {"X-User-Id": self.user_id}, json=json, params=params)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = None
            raise ApiError(r.status_code, body)
        if raw:
            return r
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ---- session / dictionaries ------------------------------------------------------------------
    def users(self) -> list[dict]:
        return self._req("GET", "/users")

    def me(self) -> dict:
        return self._req("GET", "/me")

    def meta(self) -> dict:
        return self._req("GET", "/meta")

    def criteria(self, sheet: str | None = None) -> list[dict]:
        return self._req("GET", "/criteria", params={"arkusz": sheet} if sheet else None)

    def dashboard(self) -> dict:
        return self._req("GET", "/dashboard")

    # ---- evaluation ------------------------------------------------------------------------------
    def evaluation(self, eid: int) -> dict:
        return self._req("GET", f"/evaluations/{eid}")

    def start(self, employee_number: int, start: date | None = None) -> dict:
        return self._req("POST", "/evaluations", {"oceniany_id": employee_number,
                                                  "data_poczatku_cyklu": start.isoformat() if start else None})

    def patch(self, ev: dict, **fields) -> dict:
        body = {"updated_at": ev["updated_at"]}
        for k, v in fields.items():
            body[k] = v.isoformat() if isinstance(v, date) else v
        return self._req("PATCH", f"/evaluations/{ev['id']}", body)

    def additional(self, eid: int, codes: list[str]) -> dict:
        return self._req("PUT", f"/evaluations/{eid}/criteria/additional", {"kody": codes})

    def scores(self, eid: int, points: dict[str, int | None]) -> dict:
        return self._req("PUT", f"/evaluations/{eid}/scores", {"punkty": points})

    def action(self, eid: int, akcja: str, komentarz: str | None = None) -> dict:
        return self._req("POST", f"/evaluations/{eid}/actions/{akcja}", {"komentarz": komentarz})

    def pdf(self, eid: int) -> tuple[bytes, str]:
        r = self._req("GET", f"/evaluations/{eid}/pdf", raw=True)
        name = f"ocena-{eid}.pdf"
        disp = r.headers.get("Content-Disposition", "")
        if 'filename="' in disp:
            name = disp.split('filename="', 1)[1].split('"', 1)[0]
        return r.content, name

    # ---- notes & evidence ------------------------------------------------------------------------
    def notes(self, eid: int) -> list[dict]:
        return self._req("GET", f"/evaluations/{eid}/notes")

    def add_note(self, eid: int, on: date, text: str, kind: str = "OBSERWACJA") -> dict:
        return self._req("POST", f"/evaluations/{eid}/notes", {"data": on.isoformat(), "tresc": text, "typ": kind})

    def patch_note(self, nid: int, **fields) -> dict:
        return self._req("PATCH", f"/notes/{nid}", fields)

    def delete_note(self, nid: int) -> None:
        self._req("DELETE", f"/notes/{nid}")

    def evidence(self, eid: int) -> dict:
        return self._req("GET", f"/evaluations/{eid}/evidence")

    # ---- assistant -------------------------------------------------------------------------------
    def conversation_prep(self, eid: int, kind: str) -> dict:
        return self._req("POST", f"/evaluations/{eid}/ai/conversation-prep", params={"rodzaj": kind})

    def draft(self, eid: int, kind: str) -> dict:
        return self._req("POST", f"/evaluations/{eid}/ai/draft", {"rodzaj": kind})

    def hr_partner(self, eid: int) -> dict:
        return self._req("GET", f"/evaluations/{eid}/hr-partner")

    def hr_decision(self, signal_id: int, status: str) -> None:
        self._req("POST", f"/hr-signals/{signal_id}/decision", {"status": status})

    # ---- deadlines, notifications, demo ----------------------------------------------------------
    def deadline_changes(self, eid: int) -> list[dict]:
        return self._req("GET", f"/evaluations/{eid}/deadline-changes")

    def notifications(self) -> list[dict]:
        return self._req("GET", "/notifications")

    def read_notification(self, nid: int) -> None:
        self._req("POST", f"/notifications/{nid}/read")

    def clock(self, days: int | None = None, set_to: date | None = None) -> dict:
        return self._req("POST", "/demo/clock", {"przesun_dni": days,
                                                 "ustaw_date": set_to.isoformat() if set_to else None})

    def reset(self) -> None:
        self._req("POST", "/demo/reset")


def as_hr() -> Api:
    """Read-only helper for lookups the contract has no endpoint for yet (e.g. "my evaluation" id)."""
    return Api("kadry")
