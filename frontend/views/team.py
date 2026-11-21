"""View 2: the evaluator's team – search, filters, KPIs, schedule and requests to decide."""
from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from frontend import ui
from app.domain.deadlines import is_longer_than
from frontend.demo_state import DONE, REQUEST_KINDS, REQUEST_STATUS, STAGES, DemoState, ai_on, open_evaluation

SIGNAL_ICONS = {"PRZECIAZENIE": "⚠️ przeciążenie", "DLUGA_NIEOBECNOSC": "🏥 nieobecność",
                "ZMIANA_OBOWIAZKOW": "🔄 nowe obowiązki", "SPADEK_OCEN": "📉 spadek", "DO_DOCENIENIA": "👏 docenić"}


SORT_KEYS = {
    "pilnosc": lambda r: (r["_stage"] == DONE, r["Dni"] if r["Dni"] is not None else 10**6),
    "pracownik": lambda r: r["Pracownik"],
    "arkusz": lambda r: (r["Arkusz"], r["Pracownik"]),
    "etap": lambda r: (r["_stage"], r["Pracownik"]),
    "termin": lambda r: (r["Termin"] is None, r["Termin"] or date.max),
    "sygnaly": lambda r: (-r["_signals"], r["Pracownik"]),
}


def _toggle_sort(col: str) -> None:
    cur, asc = st.session_state.get("team_sort", ("pilnosc", True))
    st.session_state.team_sort = (col, not asc if cur == col else True)


def _rows(state: DemoState) -> list[dict]:
    rows = []
    for emp in state.evaluated():
        cycle = state.cycle_for(emp.id)
        if cycle is None:
            rows.append({"id": emp.id, "Pracownik": emp.full_name, "Stanowisko": emp.position, "Komórka": emp.unit,
                         "Arkusz": emp.sheet, "Etap": "— brak cyklu", "Status": "", "Termin": None, "Dni": None,
                         "Pilność": "none", "Sygnały HR": "", "_stage": 0, "_signals": 0})
            continue
        stage = state.stage(cycle)
        label, due = state.deadline_hint(cycle)
        days = (due - state.today).days if due else None
        signals = state.assistant.hr_partner(cycle, emp, state.notes.get(cycle.id, []), cycle.absences, state.today,
                                             use_ai=False).signals if ai_on() else ()
        _, status = state.stage_status(cycle, stage) if stage != DONE else ("", "zakończona")
        rows.append({
            "id": emp.id, "Pracownik": emp.full_name, "Stanowisko": emp.position, "Komórka": emp.unit,
            "Arkusz": emp.sheet, "Etap": ui.stage_label(stage), "Status": status,
            "Termin": due, "Dni": days, "Pilność": ui.urgency(days) if stage != DONE else "none",
            "Sygnały HR": " ".join(SIGNAL_ICONS.get(s.kind, s.kind) for s in signals),
            "_stage": stage, "_signals": len(signals), "_label": label,
        })
    return rows


def render(state: DemoState) -> None:
    rows = _rows(state)
    in_progress = [r for r in rows if 0 < r["_stage"] < DONE]
    soon = [r for r in in_progress if r["Dni"] is not None and 0 <= r["Dni"] <= 30]
    late = [r for r in in_progress if r["Dni"] is not None and r["Dni"] < 0]
    pending = state.pending_requests()

    st.subheader("Mój zespół")
    st.caption("Demo: lista obejmuje wszystkich ocenianych z danych przykładowych KPRM.")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Oceny w toku", len(in_progress), border=True)
    k2.metric("Termin w ciągu 30 dni", len(soon), border=True)
    k3.metric("Po terminie", len(late), border=True)
    k4.metric("Wnioski do rozpatrzenia", len(pending), border=True)

    main, side = st.columns([2.7, 1.3], gap="large")
    with main:
        s1, s2 = st.columns([4, 1], vertical_alignment="bottom")
        q = s1.text_input("Szukaj pracownika", placeholder="imię, nazwisko, stanowisko lub komórka organizacyjna",
                          key="team_q")
        s2.button("🔍 Szukaj", use_container_width=True, key="team_search")
        f1, f2, f3 = st.columns([1.5, 1, 1.2], vertical_alignment="bottom")
        stage_opts = [f"{i} · {s}" for i, s in enumerate(STAGES, start=1)] + ["Zakończona"]
        stages = f1.multiselect("Etap", stage_opts, placeholder="wszystkie etapy")
        sheets = f2.multiselect("Arkusz", ["A", "B", "C"], placeholder="A / B / C")
        only_signals = f3.toggle("Tylko z sygnałami HR", disabled=not ai_on())

        view = rows
        if q:
            ql = q.casefold()
            view = [r for r in view if ql in " ".join([r["Pracownik"], r["Stanowisko"], r["Komórka"]]).casefold()]
        if stages:
            view = [r for r in view if r["Etap"] in stages]
        if sheets:
            view = [r for r in view if r["Arkusz"] in sheets]
        if only_signals:
            view = [r for r in view if r["_signals"]]
        sort_col, asc = st.session_state.get("team_sort", ("pilnosc", True))
        view = sorted(view, key=SORT_KEYS[sort_col], reverse=not asc)

        widths = [1.15, 2.1, 0.55, 1.8, 1.1, 1.7] if ai_on() else [1.15, 2.6, 0.6, 2.2, 1.4]
        head = st.columns(widths, vertical_alignment="center")
        headers = [("pilnosc", "Pilność"), ("pracownik", "Pracownik"), ("arkusz", "Ark."), ("etap", "Etap · status"),
                   ("termin", "Termin")] + ([("sygnaly", "Sygnały HR")] if ai_on() else [])
        for col, (key, name) in zip(head, headers):
            arrow = (" ▲" if asc else " ▼") if key == sort_col else ""
            col.button(name + arrow, key=f"sort_{key}", type="tertiary", on_click=_toggle_sort, args=(key,),
                       help=("Jak blisko jest termin bieżącego etapu: Po terminie / Wkrótce (do 30 dni) / "
                             "W terminie / Zakończona. " if key == "pilnosc" else "")
                       + "Kliknij, aby posortować; kliknij ponownie – odwrotna kolejność.")
        for r in view:
            with st.container(border=True):
                c = st.columns(widths, vertical_alignment="center")
                c[0].markdown(ui.urgency_badge(r["Pilność"]), unsafe_allow_html=True)
                c[1].button(f"**{r['Pracownik']}** →", key=f"open_{r['id']}", type="tertiary",
                            on_click=open_evaluation, args=(r["id"],), help="Otwórz ocenę pracownika")
                c[1].caption(f"{r['Stanowisko']} · {r['Komórka']}")
                c[2].markdown(r["Arkusz"])
                c[3].markdown(f"{r['Etap']}<br><span class='lock'>{r['Status']}</span>", unsafe_allow_html=True)
                days = "" if r["Dni"] is None or r["_stage"] == DONE else \
                    f"<br><span class='lock'>{ui.days_text(r['Dni'])}</span>"
                c[4].markdown(f"{ui.fmt(r['Termin'])}{days}", unsafe_allow_html=True)
                if ai_on():
                    c[5].markdown(r["Sygnały HR"] or "<span class='lock'>—</span>", unsafe_allow_html=True)
        if not view:
            st.caption("Brak pracowników spełniających kryteria wyszukiwania.")

    with side:
        with st.container(border=True):
            st.markdown("**🗓️ Harmonogram**")
            schedule_list(state, in_progress, limit=8, key="side")
            st.button("Pełny harmonogram →", key="to_schedule", type="tertiary", on_click=go, args=("schedule",))
        with st.container(border=True):
            st.markdown(f"**📥 Wnioski do rozpatrzenia** {'❗' if pending else ''}")
            requests_list(state, in_progress, key="side")


# ---------------------------------------------------------------- shared panels and full pages

def go(view: str) -> None:
    st.session_state.view = view


def schedule_list(state: DemoState, in_progress: list[dict], limit: int | None, key: str) -> None:
    st.caption("Kliknij pozycję, aby przejść do oceny.")
    items = []
    for r in in_progress:
        if r["Termin"] is not None:
            tag = {"late": "🔴 Po terminie · ", "soon": "🟡 Wkrótce · "}.get(r["Pilność"], "")
            items.append((r["Termin"], f'{r["_label"]} – {r["Pracownik"]}', tag, r["id"], None))
    for (cycle_id, stage), when in state.invites.items():
        if when.date() >= state.today:
            emp = state.employee(state.cycle(cycle_id).employee_id)
            kind = "Rozmowa rozpoczynająca" if stage == 1 else "Rozmowa oceniająca"
            items.append((when.date(), f"{kind} {when:%H:%M} – {emp.full_name}", "📅 ", emp.id, stage))
    items = sorted(items, key=lambda x: x[0])
    for i, (due, text, icon, emp_id, stage) in enumerate(items[:limit] if limit else items):
        st.button(f"{icon}**{ui.fmt(due)}** · {text}", key=f"sched_{key}_{i}_{emp_id}", type="tertiary",
                  on_click=open_evaluation, args=(emp_id, stage))
    if not items:
        st.caption("Brak zaplanowanych terminów.")


def requests_list(state: DemoState, in_progress: list[dict], key: str) -> None:
    pending = state.pending_requests()
    if not pending:
        st.caption("Brak nowych wniosków.")
    for req in pending:
        emp = state.employee(req.employee_id)
        ui.card(f"{REQUEST_KINDS[req.kind]} – {emp.full_name}",
                f"<p>{escape(req.text)}</p><p class='lock'>złożony {ui.fmt(req.created)}</p>", "c-amber")
        a, b = st.columns(2)
        if a.button("Przyjmij", key=f"acc_{key}_{req.id}", use_container_width=True, type="primary"):
            state.decide_request(req.id, True)
            st.rerun()
        if b.button("Odrzuć", key=f"rej_{key}_{req.id}", use_container_width=True):
            state.decide_request(req.id, False)
            st.rerun()
    months = state.service.rules.absence_extends_after_months
    for r in in_progress:
        c = state.cycle_for(r["id"])
        if c and any(is_longer_than(a, months) for a in c.absences):
            ui.card(f"Nieobecność > 1 mies. – {r['Pracownik']}",
                    f"<p>Termin oceny przesunięty o czas nieobecności: {ui.fmt(r['Termin'])}.</p>", "c-blue")


def render_schedule(state: DemoState) -> None:
    st.subheader("🗓️ Harmonogram")
    st.caption("Terminy bieżących etapów i zaplanowane rozmowy, od najbliższego.")
    in_progress = [r for r in _rows(state) if 0 < r["_stage"] < DONE]
    with st.container(border=True):
        schedule_list(state, in_progress, limit=None, key="page")


def render_requests(state: DemoState) -> None:
    st.subheader("📥 Wnioski")
    in_progress = [r for r in _rows(state) if 0 < r["_stage"] < DONE]
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Do rozpatrzenia**")
            requests_list(state, in_progress, key="page")
    with right:
        with st.container(border=True):
            st.markdown("**Rozpatrzone**")
            done = sorted((r for r in state.requests if r.status != "ZLOZONY"), key=lambda r: r.decided, reverse=True)
            if not done:
                st.caption("Brak rozpatrzonych wniosków.")
            for r in done:
                ui.html(f'<div class="note"><b>{escape(REQUEST_KINDS[r.kind])}</b> – '
                        f'{escape(state.employee(r.employee_id).full_name)}<br>{escape(r.text)}<br>'
                        f'<span class="d">{REQUEST_STATUS[r.status]} · {ui.fmt(r.decided)}</span></div>')
