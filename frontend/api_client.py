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


def _skip_unreachable_local_model() -> None:
    """In-process mode only, before the backend reads its config. With AI_MODE=local but no local model server
    running, every assistant call waited 2–4 s for the connection to fail before using templates/rules.
    Check once (0.5 s); if nothing listens, start the backend with AI_MODE=off – the same templates and rules,
    instantly. Restart the app after starting Ollama to use the model again."""
    import socket
    from urllib.parse import urlparse

    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    if os.environ.get("AI_MODE", "local").lower() != "local" or os.environ.get("LLM_MOCK") == "1":
        return
    url = urlparse(os.environ.get("OLLAMA_API_BASE") or "http://localhost:11434")
    host = "127.0.0.1" if url.hostname in (None, "localhost") else url.hostname
    try:
        with socket.create_connection((host, url.port or 11434), timeout=0.5):
            pass
    except OSError:
        os.environ["AI_MODE"] = "off"
        return
    if url.hostname in (None, "localhost"):  # "localhost" tries IPv6 first on Windows: 2 s lost per call
        os.environ["OLLAMA_API_BASE"] = f"{url.scheme or 'http'}://127.0.0.1:{url.port or 11434}"


@st.cache_resource(show_spinner=False)
def _transport():
    url = os.environ.get("API_URL", "").rstrip("/")
    if url:
        import requests

        session = requests.Session()

        def call(method: str, path: str, headers: dict, **kw):
            return session.request(method, url + path, headers=headers, timeout=120, **kw)

        return call
    _skip_unreachable_local_model()
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
    def _req(self, method: str, path: str, json: Any = None, params: dict | None = None, raw: bool = False,
             files: dict | None = None):
        kw = {"files": files} if files else {"json": json}
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        r = _transport()(method, "/api" + path, {"X-User-Id": self.user_id}, params=params, **kw)
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

    def action(self, eid: int, akcja: str, komentarz: str | None = None, uwzglednij: bool | None = None,
               tryb: str | None = None) -> dict:
        return self._req("POST", f"/evaluations/{eid}/actions/{akcja}",
                         {"komentarz": komentarz, "uwzglednij": uwzglednij, "tryb": tryb})

    def reminder_plan(self, eid: int) -> list[dict]:
        return self._req("GET", f"/evaluations/{eid}/przypomnienia")

    # ---- absences ----------------------------------------------------------------------------------
    def absences(self, employee_number: int) -> list[dict]:
        return self._req("GET", f"/employees/{employee_number}/absences")

    def add_absence(self, employee_number: int, od: date, do: date, typ: str) -> dict:
        return self._req("POST", f"/employees/{employee_number}/absences",
                         {"od": od.isoformat(), "do": do.isoformat(), "typ": typ})

    # ---- settings: my assistant, office, regulation, reminders, deputies --------------------------
    def my_assistant(self) -> dict:
        return self._req("GET", "/me/asystent")

    def set_my_assistant(self, **fields) -> dict:
        return self._req("PUT", "/me/asystent", fields)

    def office(self) -> dict:
        return self._req("GET", "/ustawienia/urzad")

    def set_office(self, **fields) -> dict:
        return self._req("PUT", "/ustawienia/urzad", fields)

    def rules(self) -> dict:
        return self._req("GET", "/ustawienia/reguly")

    def set_rules(self, values: dict[str, int], basis: str, criteria: dict[str, dict] | None = None,
                  from_date: date | None = None) -> dict:
        return self._req("PUT", "/ustawienia/reguly", {"wartosci": values, "kryteria": criteria or {},
                                                       "obowiazuje_od": from_date.isoformat() if from_date else None,
                                                       "podstawa_zmiany": basis})

    def reset_rules(self) -> None:
        self._req("DELETE", "/ustawienia/reguly")

    def reminders(self, office: bool = False) -> dict:
        return self._req("GET", "/ustawienia/przypomnienia" if office else "/me/przypomnienia")

    def set_reminders(self, body: dict, office: bool = False) -> dict:
        return self._req("PUT", "/ustawienia/przypomnienia" if office else "/me/przypomnienia", body)

    def reset_reminders(self) -> None:
        self._req("DELETE", "/me/przypomnienia")

    def deputies(self) -> list[dict]:
        return self._req("GET", "/zastepstwa")

    def add_deputy(self, evaluator_number: int, deputy_number: int, od: date, do: date) -> dict:
        return self._req("POST", "/zastepstwa", {"oceniajacy_id": evaluator_number, "zastepca_id": deputy_number,
                                                 "od": od.isoformat(), "do": do.isoformat()})

    def delete_deputy(self, did: int) -> None:
        self._req("DELETE", f"/zastepstwa/{did}")

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


    def _file(self, path: str, default: str) -> tuple[bytes, str]:
        r = self._req("GET", path, raw=True)
        disp = r.headers.get("Content-Disposition", "")
        name = disp.split('filename="', 1)[1].split('"', 1)[0] if 'filename="' in disp else default
        return r.content, name

    # ---- employees, history, archive (T6, T22, T23) ------------------------------------------------
    def employees(self, **filters) -> dict:
        return self._req("GET", "/employees", params={k: v for k, v in filters.items() if v not in (None, "")})

    def employee(self, employee_number: int) -> dict:
        return self._req("GET", f"/employees/{employee_number}")

    def history(self, employee_number: int) -> list[dict]:
        return self._req("GET", f"/employees/{employee_number}/evaluations")

    def archive(self) -> list[dict]:
        return self._req("GET", "/archive")

    def archive_run(self) -> dict:
        return self._req("POST", "/archive/run")

    def archive_review(self) -> list[dict]:
        return self._req("GET", "/archive/review")

    def archive_pdf(self, record_id: int) -> tuple[bytes, str]:
        return self._file(f"/archive/{record_id}/pdf", f"archiwum-{record_id}.pdf")

    def archive_delete(self, record_id: int) -> dict:
        return self._req("POST", f"/archive/{record_id}/delete", {"zatwierdzam": True})

    def archive_delete_notes(self, eid: int) -> dict:
        return self._req("POST", f"/archive/notes/{eid}/delete", {"zatwierdzam": True})

    def legacy_imports(self) -> list[dict]:
        return self._req("GET", "/legacy-import")

    def legacy_upload(self, name: str, data: bytes) -> dict:
        return self._req("POST", "/legacy-import", files={"file": (name, data)})

    def legacy_fix(self, rid: int, **fields) -> dict:
        return self._req("PUT", f"/legacy-import/{rid}", {k: (v.isoformat() if isinstance(v, date) else v)
                                                           for k, v in fields.items()})

    def legacy_approve(self, rid: int, accept_discrepancies: bool = False) -> dict:
        return self._req("POST", f"/legacy-import/{rid}/approve", {"akceptuje_rozbieznosci": accept_discrepancies})

    # ---- reports (T17–T19) -------------------------------------------------------------------------
    def report_progress(self, rok: int | None = None, komorka: str | None = None) -> dict:
        return self._req("GET", "/reports/progress", params={"rok": rok, "komorka": komorka or None})

    def report_outcomes(self, rok: int | None = None, komorka: str | None = None, poziom: str | None = None,
                        wynik: str | None = None) -> dict:
        return self._req("GET", "/reports/outcomes", params={"rok": rok, "komorka": komorka or None,
                                                              "poziom": poziom, "wynik": wynik})

    def report_training(self, komorka: str | None = None) -> dict:
        return self._req("GET", "/reports/training-needs", params={"komorka": komorka or None})

    def report_training_csv(self, komorka: str | None = None) -> bytes:
        return self._req("GET", "/reports/training-needs.csv", params={"komorka": komorka or None}, raw=True).content

    # ---- in the evaluation: wellbeing, paper, sheet, position and evaluator change, audit (T7–T15) ---
    def wellbeing_checklist(self) -> dict:
        return self._req("GET", "/wellbeing/checklist")

    def wellbeing(self, eid: int) -> dict:
        return self._req("GET", f"/evaluations/{eid}/wellbeing")

    def set_wellbeing(self, eid: int, answers: dict[str, dict]) -> dict:
        return self._req("PUT", f"/evaluations/{eid}/wellbeing", {"odpowiedzi": answers})

    def paper(self, eid: int, printed: date | None, signed: date | None) -> dict:
        return self._req("PUT", f"/evaluations/{eid}/paper", {"data_wydruku": printed.isoformat() if printed else None,
                                                             "data_podpisu": signed.isoformat() if signed else None})

    def change_sheet(self, eid: int, sheet: str, reason: str) -> dict:
        return self._req("PUT", f"/evaluations/{eid}/sheet", {"arkusz": sheet, "uzasadnienie": reason})

    def position_change(self, employee_number: int, on: date, position: str, sheet: str | None) -> dict:
        return self._req("POST", f"/employees/{employee_number}/position-changes",
                         {"data_zmiany": on.isoformat(), "nowe_stanowisko": position, "nowy_arkusz": sheet})

    def evaluator_change_check(self, employee_number: int, on: date) -> dict:
        return self._req("GET", f"/employees/{employee_number}/evaluator-change", params={"data_zmiany": on.isoformat()})

    def evaluator_change(self, employee_number: int, new_number: int, on: date, early: bool = False) -> dict:
        return self._req("POST", f"/employees/{employee_number}/evaluator-change",
                         {"nowy_oceniajacy_id": new_number, "data_zmiany": on.isoformat(), "ocena_przed_zmiana": early})

    def audit(self, eid: int) -> list[dict]:
        return self._req("GET", f"/evaluations/{eid}/audit")

    def hr_tasks(self) -> list[dict]:
        return self._req("GET", "/kadry/zadania")

    # ---- administration: HR data import, RCP, e-Akt (T5, T16, T24) ---------------------------------
    def import_employees(self, name: str, data: bytes, preview: bool, start_cycles: bool = False) -> dict:
        return self._req("POST", "/admin/employees/import", files={"file": (name, data)},
                         params={"podglad": str(preview).lower(), "uruchom_cykle": str(start_cycles).lower()})

    def rcp_import(self, name: str, data: bytes) -> dict:
        return self._req("POST", "/admin/rcp/import", files={"file": (name, data)})

    def rcp_summary(self) -> list[dict]:
        return self._req("GET", "/admin/rcp/summary")

    def eakt_retry(self) -> dict:
        return self._req("POST", "/admin/eakt/retry")

    # ---- help (T21) --------------------------------------------------------------------------------
    def knowledge(self) -> list[dict]:
        return self._req("GET", "/knowledge")

    def knowledge_search(self, q: str) -> dict:
        return self._req("GET", "/knowledge/search", params={"q": q})

    def knowledge_doc(self, slug: str) -> dict:
        return self._req("GET", f"/knowledge/{slug}")


def as_hr() -> Api:
    """Read-only helper for lookups the contract has no endpoint for yet (e.g. "my evaluation" id)."""
    return Api("kadry")
