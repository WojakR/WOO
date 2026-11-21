"""View 3: the evaluated person – status of the evaluation, confirmations and requests."""
from __future__ import annotations

from html import escape

import streamlit as st

from app.domain.calendar import add_months
from app.domain.cycle import Status
from backend import kprm
from frontend import ui
from frontend.demo_state import REQUEST_KINDS, REQUEST_STATUS, DemoState, safe
from frontend.sheet_export import sheet_html


def _can_request(state: DemoState, cycle) -> dict[str, str | None]:
    """Request kind -> None if allowed, else the reason why not."""
    months = kprm.rules()["terminy"]["zmiana_terminu_mozliwa_po_miesiacach_od_ostatniej_oceny"]
    out: dict[str, str | None] = {}
    since = add_months(cycle.start_date, months)
    out["ZMIANA_TERMINU"] = None if state.today >= since and cycle.status in (
        Status.CYCLE_STARTED, Status.CRITERIA_SET, Status.CRITERIA_CONFIRMED) else (
        f"możliwy od {ui.fmt(since)} ({months} mies. od poprzedniej oceny), przed rozmową oceniającą")
    objection = state.service.objection_deadline(cycle.id)
    out["SPRZECIW"] = None if objection and state.today <= objection else (
        f"możliwy do {ui.fmt(objection)}" if objection else "możliwy w ciągu 7 dni od zapoznania się z oceną")
    return out


def render(state: DemoState, employee_id: str) -> None:
    emp = state.employee(employee_id)
    cycle = state.cycle_for(employee_id)
    rules = state.service.rules
    st.subheader(f"Moja ocena okresowa – {emp.full_name}")
    if cycle is None:
        st.info("Nie masz jeszcze rozpoczętego cyklu oceny.")
        return
    evaluator = state.employee(cycle.evaluator_id)
    stage = state.stage(cycle)
    left, right = st.columns([1.7, 1.3], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("**Status oceny**")
            ui.mini_stepper(state, cycle)
            label, due = state.deadline_hint(cycle)
            planned = sorted((w for (cid, _), w in state.invites.items() if cid == cycle.id and w.date() >= state.today))
            ui.html(ui.kv([
                ("Etap", ui.stage_label(stage)),
                ("Oceniający", f"{evaluator.full_name}, {evaluator.position}" if evaluator else "—"),
                ("Arkusz", cycle.sheet),
                (label, ui.fmt(due)),
                ("Zaplanowana rozmowa", f"{planned[0]:%d.%m.%Y, %H:%M}" if planned else "—"),
                ("Ocena", cycle.result.outcome.value if cycle.result and stage >= 5 else "w trakcie"),
            ]))

        if cycle.status is Status.CRITERIA_SET:
            with st.container(border=True):
                st.markdown("**✍️ Do potwierdzenia: rozmowa i kryteria oceny**")
                ui.html("<b>Kryteria obowiązkowe:</b>" + ui.ul(rules.criterion_name(c) for c in rules.mandatory(cycle.sheet))
                        + "<b>Kryteria dodatkowe:</b>" + (ui.ul(rules.criterion_name(c) for c in cycle.additional_criteria)
                                                         or "<p>brak</p>")
                        + ("<b>Oczekiwania i cele:</b>" + ui.ul(cycle.goals) if cycle.goals else "")
                        + f"<p>Termin sporządzenia oceny: <b>{ui.fmt(state.service.evaluation_deadline(cycle.id))}</b></p>")
                if st.button("Potwierdzam odbycie rozmowy i zapoznanie się z kryteriami oraz terminem oceny",
                             type="primary", use_container_width=True):
                    _, problems = safe(state.service.confirm_criteria, cycle.id, employee_id)
                    ui.show_problems(problems) if problems else st.rerun()
        elif cycle.status is Status.EVALUATION_DONE:
            with st.container(border=True):
                st.markdown("**✍️ Do potwierdzenia: zapoznanie się z oceną**")
                r = cycle.result
                avg = f"{r.average_display:.2f}".replace(".", ",")
                ui.html(f'<div class="result {"pos" if r.outcome.value == "pozytywna" else "neg"}">'
                        f'Ocena <b>{r.outcome.value.upper()}</b> · średnia {avg} · {escape(r.level)}</div>')
                if cycle.justification:
                    ui.html(f"<b>Uzasadnienie:</b><p>{escape(cycle.justification)}</p>")
                ui.html(f"<b>Wnioski rozwojowe (IPRZ):</b><p>{escape(cycle.iprz_conclusions)}</p>")
                if st.button("Potwierdzam zapoznanie się z oceną", type="primary", use_container_width=True):
                    _, problems = safe(state.service.acknowledge, cycle.id, employee_id)
                    ui.show_problems(problems) if problems else st.rerun()
        elif cycle.status is Status.ACKNOWLEDGED:
            objection = state.service.objection_deadline(cycle.id)
            if objection and state.today <= objection:
                st.info(f"Jeśli nie zgadzasz się z oceną, możesz złożyć sprzeciw do dyrektora generalnego do "
                        f"**{ui.fmt(objection)}** ({ui.days_text((objection - state.today).days)}).")
        if stage >= 2:
            with st.container(border=True):
                st.markdown("**Moje kryteria i cele**")
                ui.html(ui.ul(rules.criterion_name(c) for c in cycle.criteria_ids(rules))
                        + ("<b>Cele:</b>" + ui.ul(cycle.goals) if cycle.goals else ""))
        if stage >= 5:
            doc = sheet_html(cycle, emp, evaluator, rules, state.service.evaluation_deadline(cycle.id),
                             state.grade_request.get(cycle.id))
            st.download_button("📄 Pobierz arkusz oceny (do druku / PDF)", doc.encode("utf-8"),
                               file_name=f"arkusz-{cycle.sheet}-{employee_id}.html", mime="text/html")

    with right:
        with st.container(border=True):
            st.markdown("**📨 Wnioski**")
            allowed = _can_request(state, cycle)
            with st.popover("Złóż wniosek", use_container_width=True):
                kind = st.selectbox("Rodzaj wniosku", list(REQUEST_KINDS), format_func=REQUEST_KINDS.get)
                reason = allowed[kind]
                if reason:
                    st.caption(f"Wniosek {reason}.")
                text = st.text_area("Uzasadnienie", key=f"req_text_{employee_id}")
                if st.button("Wyślij wniosek", type="primary", disabled=bool(reason) or not text.strip()):
                    state.submit_request(employee_id, cycle.id, kind, text)
                    st.toast("Wniosek wysłany do oceniającego.")
                    st.rerun()
            mine = sorted((r for r in state.requests if r.employee_id == employee_id),
                          key=lambda r: r.created, reverse=True)
            st.markdown("**Historia wniosków**")
            if not mine:
                st.caption("Nie złożono żadnych wniosków.")
            for r in mine:
                ui.html(f'<div class="note"><b>{escape(REQUEST_KINDS[r.kind])}</b> · {ui.fmt(r.created)}<br>'
                        f'{escape(r.text)}<br><span class="d">{REQUEST_STATUS[r.status]}'
                        f'{" · " + ui.fmt(r.decided) if r.decided else ""}</span></div>')
        st.caption("Wniosek o kolejny stopień służbowy składa oceniający (część III arkusza).")
