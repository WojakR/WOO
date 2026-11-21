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
from frontend.demo_state import REQUEST_KINDS, REQUEST_STATUS, get_state, reset_state
from frontend.views import employee, evaluation, team

st.set_page_config(page_title="Cyfrowy Asystent Ocen Okresowych", page_icon="🏛️", layout="wide")
ui.inject_css()
state = get_state()

ROLE_EVALUATOR, ROLE_EMPLOYEE = "Oceniający (przełożony)", "Oceniany (pracownik)"
st.session_state.setdefault("view", "team")
st.session_state.setdefault("role", ROLE_EVALUATOR)


def notifications(role: str, person: str | None) -> list[tuple[str, str]]:
    evaluated = {e.id for e in state.evaluated()}
    items = []
    for r in state.service.reminders(lead_days=30):
        mine = r.recipient_id == person if role == ROLE_EMPLOYEE else r.recipient_id not in evaluated
        if mine:
            items.append(("🔴" if r.days_left < 0 else "🟡" if r.days_left <= 7 else "🔔", r.message))
    if role == ROLE_EVALUATOR:
        items += [("📥", f"Nowy wniosek: {REQUEST_KINDS[q.kind].lower()} – {state.employee(q.employee_id).full_name}")
                  for q in state.pending_requests()]
    else:
        items += [("📨", f"{REQUEST_KINDS[q.kind]}: {REQUEST_STATUS[q.status]}")
                  for q in state.requests if q.employee_id == person and q.decided]
    return items


# ---------------------------------------------------------------- header
title, role_col, who_col, time_col, bell_col = st.columns([2.4, 1.3, 1.5, 1.1, 0.7], vertical_alignment="center")
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

with time_col.popover(f"📅 {ui.fmt(state.today)}", use_container_width=True, help="Przewiń czas (demo)"):
    st.markdown("**⏩ Przewiń czas (demo)**")
    st.caption("Pokazuje przypomnienia i terminy. Zmienia tylko datę w tej sesji.")
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
    for icon, text in notes:
        st.markdown(f"{icon} {text}")
st.divider()

# ---------------------------------------------------------------- routing
if role == ROLE_EMPLOYEE:
    employee.render(state, person)
elif st.session_state.view == "eval" and st.session_state.get("eval_employee"):
    evaluation.render(state, st.session_state.eval_employee)
else:
    team.render(state)

st.caption(f"Tryb asystenta AI: {config.AI_MODE}{' (atrapa – LLM_MOCK)' if config.LLM_MOCK else ''}. "
           "Asystent tylko proponuje – decyzje podejmuje oceniający. Dane osobowe są pseudonimizowane przed "
           "wysłaniem do modelu. Dane w demo są fikcyjne (przykłady KPRM).")
