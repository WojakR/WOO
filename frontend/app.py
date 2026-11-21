"""Cyfrowy Asystent Ocen Okresowych – Streamlit app. Run from projekt/: streamlit run frontend/app.py

Calls the application layer directly (no HTTP), so it deploys as one app. Pages (side menu):
  evaluator: Mój zespół (views/team.py), Ocena pracownika (views/evaluation.py), Harmonogram, Wnioski
  evaluated person: Moja ocena, Moje wnioski (views/employee.py)
Wireframes: frontend/design/wireframes.drawio
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from backend import config
from frontend import ui
from frontend.demo_state import REQUEST_KINDS, REQUEST_STATUS, ai_on, get_state, open_evaluation, reset_state
from frontend.views import employee, evaluation, team

st.set_page_config(page_title="Cyfrowy Asystent Ocen Okresowych", page_icon="🏛️", layout="wide",
                   initial_sidebar_state="expanded")
st.session_state.setdefault("a11y_font", "Duża")  # larger text by default – easier to read
st.session_state.setdefault("ai_on", True)
ui.inject_css(ui.FONT_SCALES.get(st.session_state.a11y_font, 1.0), st.session_state.get("a11y_contrast", False))
state = get_state()

ROLE_EVALUATOR, ROLE_EMPLOYEE = "Oceniający (przełożony)", "Oceniany (pracownik)"
st.session_state.setdefault("role", ROLE_EVALUATOR)
st.session_state.setdefault("view", "team")
st.session_state.setdefault("emp_view", "ocena")


def go(view: str) -> None:
    st.session_state.view = view


def go_employee(view: str) -> None:
    st.session_state.emp_view = view


def open_current_evaluation() -> None:
    open_evaluation(st.session_state.get("eval_employee") or state.evaluated()[0].id)


def notifications(role: str, person: str | None) -> list[tuple[str, str, str | None]]:
    """(icon, text, employee id to open or None). Most urgent first."""
    evaluated = {e.id for e in state.evaluated()}
    items = []
    for r in state.service.reminders(lead_days=30):
        mine = r.recipient_id == person if role == ROLE_EMPLOYEE else r.recipient_id not in evaluated
        if mine:
            items.append(("🔴" if r.days_left < 0 else "🟡" if r.days_left <= 7 else "🔔", r.message, r.employee_id))
    if role == ROLE_EVALUATOR:
        items += [("📥", f"Nowy wniosek: {REQUEST_KINDS[q.kind].lower()} – {state.employee(q.employee_id).full_name}",
                   None) for q in state.pending_requests()]
    else:
        for (cycle_id, stage), when in sorted(state.invites.items(), key=lambda x: x[1]):
            c = state.cycle(cycle_id)
            if c.employee_id == person and when.date() >= state.today:
                kind = "rozpoczynającą ocenę" if stage == 1 else "oceniającą"
                items.append(("✉️", f"Zaproszenie na rozmowę {kind}: {when:%d.%m.%Y, %H:%M} "
                                    f"(od: {state.employee(c.evaluator_id).full_name})", None))
        items += [("📨", f"{REQUEST_KINDS[q.kind]}: {REQUEST_STATUS[q.status]}", None)
                  for q in state.requests if q.employee_id == person and q.decided]
    return items


def menu_item(label: str, active: bool, on_click, args=()) -> None:
    st.button(label, use_container_width=True, type="primary" if active else "secondary",
              on_click=on_click, args=args)


# ---------------------------------------------------------------- side menu
role = st.session_state.role
person = st.session_state.get("person") if role == ROLE_EMPLOYEE else None
with st.sidebar:
    ui.html('<p class="app-title">🏛️ Asystent Ocen Okresowych</p>')
    st.caption("Ocena okresowa w służbie cywilnej")
    st.markdown("**Menu**")
    if role == ROLE_EVALUATOR:
        view = st.session_state.view
        pending = len(state.pending_requests())
        menu_item("👥 Mój zespół", view == "team", go, ("team",))
        menu_item("📝 Ocena pracownika", view == "eval", open_current_evaluation)
        menu_item("🗓️ Harmonogram", view == "schedule", go, ("schedule",))
        menu_item(f"📥 Wnioski ({pending})" if pending else "📥 Wnioski", view == "requests", go, ("requests",))
    else:
        menu_item("📄 Moja ocena", st.session_state.emp_view == "ocena", go_employee, ("ocena",))
        menu_item("📨 Moje wnioski", st.session_state.emp_view == "wnioski", go_employee, ("wnioski",))

    st.divider()
    with st.expander("⚙️ Ustawienia", expanded=False):
        st.toggle("🤖 Asystent AI", key="ai_on",
                  help="Wyłączenie ukrywa wszystkie podpowiedzi asystenta: propozycje kryteriów, wskazówki do "
                       "rozmów, przypisywanie notatek, szkice tekstów i HR partnera. Proces oceny działa bez zmian.")
        st.radio("Wielkość tekstu", list(ui.FONT_SCALES), key="a11y_font")
        st.toggle("Wysoki kontrast", key="a11y_contrast",
                  help="Ciemniejszy tekst pomocniczy, grubsze obramowania i podkreślone odnośniki.")
        st.caption("Dostępność zgodnie z WCAG 2.1: powiększenie tekstu (1.4.4), kontrast (1.4.3), widoczny "
                   "fokus przy obsłudze klawiaturą (2.4.7). Stronę można też powiększyć skrótem Ctrl i +.")

    with st.expander("🎬 Tryb demo", expanded=False):
        st.caption("Bez logowania: wybierz, kim jesteś w prezentacji.")
        st.selectbox("Widok jako", [ROLE_EVALUATOR, ROLE_EMPLOYEE], key="role")
        if st.session_state.role == ROLE_EMPLOYEE:
            st.selectbox("Pracownik", [e.id for e in state.evaluated()], key="person",
                         format_func=lambda i: state.employee(i).full_name)
        st.markdown(f"**⏩ Data w aplikacji: {ui.fmt(state.today)}**")
        st.caption("Na prezentacji nie poczekamy 24 miesięcy – tu przesuwasz kalendarz aplikacji, żeby pokazać "
                   "przypomnienia i terminy. W prawdziwym wdrożeniu tej opcji nie ma.")
        a, b, c = st.columns(3)
        for col, label, days in ((a, "+1 dz.", 1), (b, "+7 dni", 7), (c, "+30 dni", 30)):
            if col.button(label, use_container_width=True, key=f"adv_{days}"):
                state.clock.advance(days=days)
                st.rerun()
        new = st.date_input("Ustaw datę", state.today, format="DD.MM.YYYY")
        if st.button("Ustaw datę", use_container_width=True, disabled=new == state.today):
            state.clock.set(new)
            st.rerun()
        if st.button("↺ Zacznij demo od nowa", use_container_width=True):
            reset_state()
            for k in list(st.session_state):
                if k not in ("role", "a11y_font", "a11y_contrast", "ai_on"):
                    del st.session_state[k]
            st.rerun()

    st.caption(f"Data: {ui.fmt(state.today)} · {'Asystent AI włączony' if ai_on() else 'Asystent AI wyłączony'}")

role = st.session_state.role
person = st.session_state.get("person") if role == ROLE_EMPLOYEE else None
if role == ROLE_EMPLOYEE and person is None:
    person = state.evaluated()[0].id

# ---------------------------------------------------------------- header: who + notifications
who, bell_col = st.columns([5, 1], vertical_alignment="center")
who.markdown(f"<span class='lock'>Zalogowano jako (demo):</span> **"
             + (state.employee(person).full_name + " – oceniany" if role == ROLE_EMPLOYEE else "oceniający")
             + "**", unsafe_allow_html=True)
notes = notifications(role, person)
with bell_col.popover(f"🔔 {len(notes)}" if notes else "🔔", use_container_width=True):
    st.markdown("**Powiadomienia**")
    if not notes:
        st.caption("Brak nowych powiadomień.")
    for i, (icon, text, emp_id) in enumerate(notes):
        if role == ROLE_EVALUATOR:
            st.button(f"{icon} {text}", key=f"notif_{i}", type="tertiary",
                      on_click=open_evaluation if emp_id else go, args=(emp_id,) if emp_id else ("requests",))
        else:
            st.markdown(f"{icon} {text}")
if not ai_on():
    st.info("Asystent AI jest wyłączony – aplikacja działa bez podpowiedzi. Włączysz go w menu: ⚙️ Ustawienia.")

# ---------------------------------------------------------------- routing
if role == ROLE_EMPLOYEE:
    employee.render(state, person, st.session_state.emp_view)
elif st.session_state.view == "eval" and st.session_state.get("eval_employee"):
    evaluation.render(state, st.session_state.eval_employee)
elif st.session_state.view == "schedule":
    team.render_schedule(state)
elif st.session_state.view == "requests":
    team.render_requests(state)
else:
    team.render(state)

st.divider()
if ai_on():
    st.caption(f"Tryb asystenta AI: {config.AI_MODE}{' (atrapa – LLM_MOCK)' if config.LLM_MOCK else ''}. "
               "Asystent tylko proponuje – decyzje podejmuje oceniający. Dane osobowe są pseudonimizowane przed "
               "wysłaniem do modelu. Dane w demo są fikcyjne (przykłady KPRM).")
else:
    st.caption("Asystent AI wyłączony. Dane w demo są fikcyjne (przykłady KPRM).")
