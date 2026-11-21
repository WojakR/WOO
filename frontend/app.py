"""Cyfrowy Asystent Ocen Okresowych – Streamlit app. Run from projekt/: streamlit run frontend/app.py

Everything goes through the backend's /api contract (frontend/api_client.py): the server keeps the data in
the database and decides rules, permissions and allowed steps. Set API_URL=http://localhost:8000 to share
a running `uvicorn backend.main:app` with the web UI; without it the API runs inside this process.

Pages (side menu): evaluator / HR – Mój zespół (views/team.py; a row opens views/evaluation.py), Terminy, Ustawienia;
evaluated person – Moja ocena, Moje wnioski (views/employee.py). Wireframes: frontend/design/wireframes.drawio
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import name, to_date
from frontend.views import employee, evaluation, settings, team

st.set_page_config(page_title="Cyfrowy Asystent Ocen Okresowych", page_icon="🏛️", layout="wide",
                   initial_sidebar_state="expanded")
st.session_state.setdefault("a11y_font", "Standardowa")  # 120 % of the browser default – easier to read
st.session_state.setdefault("user_id", "henryk.pryncypal")
st.session_state.setdefault("view", "team")
st.session_state.setdefault("emp_view", "ocena")
_page = (st.session_state.user_id, st.session_state.view, st.session_state.get("eval_id"), st.session_state.emp_view)
_page_switch = st.session_state.get("_last_page") != _page
st.session_state._last_page = _page
ui.inject_css(ui.FONT_SCALES.get(st.session_state.a11y_font, 1.0), st.session_state.get("a11y_contrast", False),
              page_switch=_page_switch)

api = Api(st.session_state.user_id)
try:
    me, meta, users = api.me(), api.meta(), api.users()
except ApiError as e:
    st.error(f"Nie udało się połączyć z serwerem: {e.komunikat}")
    st.stop()
evaluator_ui = me["rola"] == "KADRY" or me["czy_oceniajacy"]

# the assistant switch is stored on the server per user (GET/PUT /api/me/asystent); the office switch wins
try:
    my_ai = api.my_assistant()
except ApiError:
    my_ai = {"asystent_ai": True, "asystent_ai_w_urzedzie": True}
office_ai = my_ai.get("asystent_ai_w_urzedzie", True)
if st.session_state.get("ai_on__user") != st.session_state.user_id:
    st.session_state.ai_on = bool(my_ai.get("asystent_ai", True))
    st.session_state.ai_on__user = st.session_state.user_id


def save_ai() -> None:
    try:
        api.set_my_assistant(asystent_ai=bool(st.session_state.ai_on))
    except ApiError as e:
        st.toast(e.komunikat)


ai = bool(st.session_state.ai_on) and office_ai


def go(view: str) -> None:
    st.session_state.view = view


def go_employee(view: str) -> None:
    st.session_state.emp_view = view


def switch_user() -> None:
    for k in [k for k in st.session_state if k.startswith(("sel_", "tx_", "sc_", "add_", "draft_", "confirm_",
                                                            "emp_", "pdf_", "auto_"))]:
        del st.session_state[k]
    st.session_state.pop("ai_cache", None)
    st.session_state.pop("eval_id", None)
    st.session_state.pop("ai_on__user", None)
    st.session_state.pop("rem_rules", None)
    st.session_state.view = "team"
    st.session_state.emp_view = "ocena"


def open_notification(nid: int, eid: int | None) -> None:
    try:
        api.read_notification(nid)
    except ApiError:
        pass
    if eid and evaluator_ui:
        team.open_evaluation(eid)


def menu_item(label: str, active: bool, on_click, args=()) -> None:
    st.button(label, use_container_width=True, type="primary" if active else "secondary", on_click=on_click, args=args)


def accessibility_panel() -> None:
    st.radio("Wielkość tekstu", list(ui.FONT_SCALES), key="a11y_font",
             help="Zgodnie z WCAG 2.1 (1.4.4). Stronę można też powiększyć skrótem Ctrl i +.")
    st.toggle("Wysoki kontrast", key="a11y_contrast",
              help="Ciemniejszy tekst pomocniczy, grubsze obramowania i podkreślone odnośniki (WCAG 2.1: 1.4.3).")


def demo_panel() -> None:
    ids = [u["id"] for u in users]
    labels = {u["id"]: f"{u['nazwa']} – {u['opis']}" for u in users}
    st.selectbox("Zalogowany jako", ids, key="user_id", format_func=labels.get, on_change=switch_user,
                 help="Bez logowania: wybierz osobę. Uprawnienia (kto co widzi i może zrobić) wylicza serwer.")
    st.markdown(f"**⏩ Data w aplikacji: {ui.fmt(meta['dzis'])}**", help="Na prezentacji nie poczekamy 24 miesięcy – "
                "przesuwasz zegar serwera, a system wysyła przypomnienia z tego okresu. W prawdziwym wdrożeniu tej "
                "opcji nie ma.")
    a, b, c = st.columns(3)
    for col, label, days in ((a, "+1 dz.", 1), (b, "+7 dni", 7), (c, "+30 dni", 30)):
        if col.button(label, use_container_width=True, key=f"adv_{days}"):
            try:
                r = api.clock(days=days)
                st.toast(f"Zegar: {ui.fmt(r.get('dzis'))}. Nowe przypomnienia: {r.get('nowe_powiadomienia', 0)}.")
            except ApiError as e:
                st.toast(e.komunikat)
            st.session_state.pop("ai_cache", None)
            st.rerun()
    new = st.date_input("Ustaw datę", to_date(meta["dzis"]), format="DD.MM.YYYY")
    if st.button("Ustaw datę", use_container_width=True, disabled=new is None):
        try:
            api.clock(set_to=new)
        except ApiError as e:
            st.toast(e.komunikat)
        st.session_state.pop("ai_cache", None)
        st.rerun()
    if st.button("↺ Przywróć dane przykładowe", use_container_width=True):
        api.reset()
        switch_user()
        st.toast("Przywrócono dane przykładowe.")
        st.rerun()


# ---------------------------------------------------------------- side menu
with st.sidebar:
    ui.theme_watcher()
    ui.html('<p class="app-title">🏛️ Asystent Ocen Okresowych</p>')
    st.caption("Ocena okresowa w służbie cywilnej")
    st.markdown("**Menu**")
    if evaluator_ui:
        view = st.session_state.view
        menu_item("👥 Mój zespół" if me["rola"] != "KADRY" else "👥 Oceny w urzędzie", view in ("team", "eval"), go,
                  ("team",))
        menu_item("🗓️ Terminy", view == "schedule", go, ("schedule",))
        menu_item("⚙️ Ustawienia", view == "settings", go, ("settings",))
    else:
        menu_item("📄 Moja ocena", st.session_state.emp_view == "ocena", go_employee, ("ocena",))
        menu_item("📨 Moje wnioski", st.session_state.emp_view == "wnioski", go_employee, ("wnioski",))
        menu_item("⚙️ Ustawienia", st.session_state.emp_view == "settings", go_employee, ("settings",))

    st.divider()
    mode = meta["tryb_ai"]
    available = meta.get("funkcje_ai", {}).get("model_dostepny")
    chip = ("wyłączony w aplikacji" if not ai else "wyłączony na serwerze (szablony)" if mode == "OFF"
            else "usługa zewnętrzna" if mode == "API" else "model lokalny" if available
            else "model lokalny niedostępny – szablony")
    st.caption(f"Data: {ui.fmt(meta['dzis'])} · Asystent AI: {chip}")

# ---------------------------------------------------------------- header: who + notifications
who, ai_col, a11y_col, bell_col, demo_col = st.columns([3.1, 1.4, 0.7, 0.8, 1.2], vertical_alignment="center")
with a11y_col.popover("Aa", use_container_width=True, help="Dostępność: wielkość tekstu i kontrast"):
    st.markdown("**Dostępność**")
    accessibility_panel()
with demo_col.popover("🎬 Demo", use_container_width=True, help="Tryb demo: kim jesteś, data w aplikacji, reset"):
    st.markdown("**Tryb demo**")
    demo_panel()
with ai_col.container(horizontal_alignment="right"):
    st.toggle("🤖 Asystent AI", key="ai_on", on_change=save_ai, disabled=not office_ai,
              help="Wyłączenie ukrywa wszystkie podpowiedzi asystenta AI: wskazówki do rozmów, propozycje przypisania "
                   "notatek, sugerowane oceny, szkice tekstów i HR partnera. Proces oceny działa bez zmian.")
role = "kadry" if me["rola"] == "KADRY" else "oceniający" if me["czy_oceniajacy"] else "oceniany"
who.markdown(f"<span class='lock'>Zalogowano jako (demo):</span> **{name(me['pracownik'])}** · {role} · "
             f"<span class='lock'>{me['urzad']}</span>", unsafe_allow_html=True)
try:
    notes = sorted(api.notifications(), key=lambda n: n["zaplanowane_na"], reverse=True)
except ApiError:
    notes = []
unread = [n for n in notes if not n["przeczytane"]]
with bell_col.popover(f"🔔 {len(unread)}" if unread else "🔔", use_container_width=True):
    st.markdown("**Powiadomienia**")
    if not notes:
        st.caption("Brak powiadomień do dziś (zegar serwera).")
    for n in notes[:15]:
        when = ui.fmt(n["zaplanowane_na"])
        label = f"{'🔵 ' if not n['przeczytane'] else ''}{when} · {n['tresc']}"
        st.button(label, key=f"notif_{n['id']}", type="tertiary", on_click=open_notification,
                  args=(n["id"], n.get("evaluation_id")),
                  help="Kliknij, aby oznaczyć jako przeczytane" + (" i otworzyć ocenę" if evaluator_ui else ""))
if not office_ai:
    st.info("Asystent AI jest wyłączony dla całego urzędu (ustawienie kadr) – aplikacja działa bez podpowiedzi.")
elif not ai:
    st.info("Asystent AI jest wyłączony – aplikacja działa bez podpowiedzi. Włączysz go przełącznikiem w prawym górnym rogu.")

# ---------------------------------------------------------------- routing
if not evaluator_ui and st.session_state.emp_view == "settings":
    settings.render(api, me, meta, users)
elif not evaluator_ui:
    employee.render(api, me, st.session_state.emp_view)
elif st.session_state.view == "settings":
    settings.render(api, me, meta, users)
elif st.session_state.view == "eval" and st.session_state.get("eval_id"):
    evaluation.render(api, me, meta, st.session_state.eval_id, ai)
elif st.session_state.view == "schedule":
    team.render_schedule(api, me)
else:
    team.render(api, me, ai)


