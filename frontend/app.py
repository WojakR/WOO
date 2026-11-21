"""Cyfrowy Asystent Ocen Okresowych – Streamlit demo. Run from projekt/: streamlit run frontend/app.py

Calls the application layer directly (no HTTP), so it deploys as one app. Views:
  1. evaluation screen (evaluator) – frontend/views/evaluation.py
  2. my team summary (evaluator)   – frontend/views/team.py
  3. evaluated person              – frontend/views/employee.py
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

st.set_page_config(page_title="Cyfrowy Asystent Ocen Okresowych", page_icon="🏛️", layout="wide")
st.session_state.setdefault("a11y_font", "Duża")  # larger text by default – easier to read
ui.inject_css(ui.FONT_SCALES.get(st.session_state.a11y_font, 1.0),
              st.session_state.get("a11y_contrast", False))
state = get_state()

ROLE_EVALUATOR, ROLE_EMPLOYEE = "Oceniający (przełożony)", "Oceniany (pracownik)"
st.session_state.setdefault("view", "team")
st.session_state.setdefault("role", ROLE_EVALUATOR)


def go_team() -> None:
    st.session_state.view = "team"


def notifications(role: str, person: str | None) -> list[tuple[str, str, str | None]]:
    """(icon, text, employee id to open or None). Newest/most urgent first."""
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


# ---------------------------------------------------------------- header
st.session_state.setdefault("ai_on", True)
bar_text, bar_switch = st.columns([4.2, 1.5], vertical_alignment="center")
with bar_switch.container(horizontal_alignment="right"):
    st.toggle("🤖 Asystent AI", key="ai_on",
              help="Wyłączenie ukrywa wszystkie podpowiedzi asystenta: propozycje kryteriów, wskazówki do rozmów, "
                   "przypisywanie notatek, szkice tekstów i HR partnera. Proces oceny działa dalej bez zmian.")
if not st.session_state.ai_on:
    bar_text.info("Asystent AI jest wyłączony – aplikacja działa bez podpowiedzi. Włączysz go przełącznikiem obok.")
title, role_col, who_col, a11y_col, time_col, bell_col = st.columns([2.2, 1.3, 1.4, 1.0, 1.1, 0.8],
                                                                    vertical_alignment="center")
with title:
    ui.html('<p class="app-title">🏛️ Cyfrowy Asystent Ocen Okresowych</p>'
            '<p class="app-sub">Ocena okresowa w służbie cywilnej – od kryteriów do arkusza, z wirtualnym HR partnerem</p>')
role = role_col.selectbox("Widok jako", [ROLE_EVALUATOR, ROLE_EMPLOYEE], key="role", label_visibility="collapsed")
person = None
if role == ROLE_EMPLOYEE:
    ids = [e.id for e in state.evaluated()]
    person = who_col.selectbox("Pracownik", ids, key="person", format_func=lambda i: state.employee(i).full_name,
                               label_visibility="collapsed")
else:
    who_col.caption("Demo bez logowania – rolę wybierasz z listy obok.")

with a11y_col.popover("Aa Dostępność", use_container_width=True, help="Wielkość tekstu i kontrast (WCAG 2.1)"):
    st.markdown("**Ustawienia dostępności**")
    st.radio("Wielkość tekstu", list(ui.FONT_SCALES), key="a11y_font", horizontal=True)
    st.toggle("Wysoki kontrast", key="a11y_contrast",
              help="Ciemniejszy tekst pomocniczy, grubsze obramowania i podkreślone odnośniki.")
    st.caption("Zgodnie z WCAG 2.1: powiększenie tekstu bez utraty treści (1.4.4), kontrast (1.4.3), "
               "widoczny fokus przy obsłudze klawiaturą (2.4.7). Przeglądarka pozwala też powiększać "
               "stronę skrótem Ctrl i +.")

with time_col.popover(f"📅 {ui.fmt(state.today)}", use_container_width=True, help="Przewiń czas (demo)"):
    st.markdown("**⏩ Przewiń czas (tylko demo)**")
    st.caption("Na prezentacji nie poczekamy 24 miesięcy – tu „przesuwasz kalendarz” aplikacji do przodu, żeby "
               "pokazać przypomnienia, zbliżające się i przekroczone terminy. Zmienia tylko datę w tej sesji; "
               "w prawdziwym wdrożeniu tej opcji nie ma.")
    a, b, c = st.columns(3)
    for col, label, days in ((a, "+1 dzień", 1), (b, "+1 tydz.", 7), (c, "+30 dni", 30)):
        if col.button(label, use_container_width=True):
            state.clock.advance(days=days)
            st.rerun()
    new = st.date_input("Ustaw datę", state.today, format="DD.MM.YYYY")
    if new != state.today and st.button("Ustaw", type="primary"):
        state.clock.set(new)
        st.rerun()
    st.divider()
    if st.button("↺ Zacznij demo od nowa", use_container_width=True):
        reset_state()
        for k in list(st.session_state):
            if k not in ("role",):
                del st.session_state[k]
        st.rerun()

notes = notifications(role, person)
with bell_col.popover(f"🔔 {len(notes)}" if notes else "🔔", use_container_width=True):
    st.markdown("**Powiadomienia**")
    if not notes:
        st.caption("Brak nowych powiadomień.")
    for i, (icon, text, emp_id) in enumerate(notes):
        if role == ROLE_EVALUATOR:
            st.button(f"{icon} {text}", key=f"notif_{i}", type="tertiary",
                      on_click=open_evaluation if emp_id else go_team, args=(emp_id,) if emp_id else ())
        else:
            st.markdown(f"{icon} {text}")
st.divider()

# ---------------------------------------------------------------- routing
if role == ROLE_EMPLOYEE:
    employee.render(state, person)
elif st.session_state.view == "eval" and st.session_state.get("eval_employee"):
    evaluation.render(state, st.session_state.eval_employee)
else:
    team.render(state)

if ai_on():
    st.caption(f"Tryb asystenta AI: {config.AI_MODE}{' (atrapa – LLM_MOCK)' if config.LLM_MOCK else ''}. "
               "Asystent tylko proponuje – decyzje podejmuje oceniający. Dane osobowe są pseudonimizowane przed "
               "wysłaniem do modelu. Dane w demo są fikcyjne (przykłady KPRM).")
else:
    st.caption("Asystent AI wyłączony. Dane w demo są fikcyjne (przykłady KPRM).")
