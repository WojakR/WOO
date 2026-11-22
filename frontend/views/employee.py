"""View 3: the evaluated person – their own evaluation from the API (read-only sheet + their own steps)."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import ACTION_DONE, ACTION_LABEL, LEVEL_LABEL, STATUS_LABEL, name


def _mine(api: Api) -> list[dict]:
    """My own evaluations as the evaluated person – `moje` in GET /api/dashboard (oldest first)."""
    try:
        return [i for i in api.dashboard().get("moje", []) if i.get("evaluation_id")]
    except ApiError:
        return []


def _my_evaluation_id(api: Api) -> int | None:
    """The evaluation to show: the one waiting for my step, else the open one, else the newest."""
    items = _mine(api)
    for test in (lambda i: i.get("kto_dziala") == "OCENIANY", lambda i: i["status"] != "ZAKONCZONA", lambda i: True):
        hit = [i for i in items if test(i)]
        if hit:
            return hit[-1]["evaluation_id"]
    return None


def _my_evaluations(api: Api, me: dict) -> list[dict]:
    """All my evaluations, newest first (full sheets read as me – the server checks access)."""
    out = []
    for i in reversed(_mine(api)):
        try:
            out.append(api.evaluation(i["evaluation_id"]))
        except ApiError:
            continue
    return out


def _open_requests() -> None:
    st.session_state.emp_view = "wnioski"
    if st.session_state.get("view") == "my_eval":  # an evaluator looking at their own evaluation
        st.session_state.view = "my_requests"


def _requests(api: Api, me: dict) -> None:
    from frontend.views.evaluation import objection_panel

    evs = _my_evaluations(api, me)
    shown = False
    for ev in evs:
        if ev.get("sprzeciw") or "ZLOZ_SPRZECIW" in ev["dozwolone_akcje"]:
            st.markdown(f"**Ocena sporządzona {ui.fmt(ev['czesc_ii'].get('data_sporzadzenia'))}** – "
                        f"{(ev['czesc_ii'].get('wynik') or '').lower()}")
            objection_panel(api, ev)
            shown = True
    if not shown:
        st.info("Sprzeciw od oceny możesz złożyć w ciągu 7 dni od zapoznania się z oceną – teraz nie masz oceny, "
                "od której przysługuje sprzeciw.")
    _deadline_request(api, [e for e in evs if e["status"] not in ("OCENA_DO_ZAPOZNANIA", "ZAKONCZONA", "SPRZECIW")])


def _deadline_request(api: Api, open_evs: list[dict]) -> None:
    """Request another date of the evaluation (e.g. a planned absence): the evaluator decides (art. 81 ust. 8)."""
    from frontend.views.evaluation import DEADLINE_STATUS

    with st.container(border=True):
        st.markdown("**:material/edit_calendar: Wniosek o zmianę terminu oceny**",
                    help="Np. z powodu planowanej nieobecności. O zmianie decyduje Twój przełożony; decyzję dostaniesz "
                         "jako powiadomienie.")
        if not open_evs:
            st.caption("Nie masz oceny w toku, której termin można zmienić.")
            return
        ev = open_evs[0]
        eid = ev["id"]
        try:
            history = api.deadline_changes(eid)
        except ApiError:
            history = []
        for r in history:
            label, cls = DEADLINE_STATUS.get(r["status"], (r["status"], "b-grey"))
            st.markdown(f"{ui.badge(label, cls)} {ui.fmt(r['stary_termin'])} → **{ui.fmt(r.get('nowy_termin'))}**"
                        + (f" · {escape(r['komentarz_decyzji'])}" if r.get("komentarz_decyzji") else ""),
                        unsafe_allow_html=True)
        st.caption(f"Obecny termin oceny: {ui.fmt(ev['czesc_i']['termin_oceny'])}.")
        if any(r["status"] == "ZLOZONY" for r in history):
            st.info("Twój wniosek czeka na decyzję przełożonego.")
            return
        new = st.date_input("Proponowany termin", value=None, min_value=ui.to_date(api.meta()["dzis"]),
                            key=f"emp_dc_new_{eid}",
                            format="DD.MM.YYYY")
        why = st.text_area("Dlaczego prosisz o zmianę?", key=f"emp_dc_why_{eid}", height=80,
                           placeholder="np. planowany urlop rodzicielski od 1.06 do 31.08")
        if st.button("Wyślij wniosek", type="primary", key=f"emp_dc_go_{eid}"):
            if new is None or not why.strip():
                st.error("Podaj proponowany termin i powód.")
                return
            try:
                api.request_deadline_change(eid, "WNIOSEK_OCENIANEGO", new, why.strip())
            except ApiError as e:
                ui.api_error(e)
                return
            st.toast("Wysłano wniosek do przełożonego.")
            st.rerun()


def render(api: Api, me: dict, page: str = "ocena") -> None:
    person = me["pracownik"]
    st.subheader(f"Moje wnioski – {name(person)}" if page == "wnioski" else f"Moja ocena okresowa – {name(person)}")
    for kind, text in st.session_state.pop("flash", []):
        (st.error if kind == "error" else st.success)(text)
    if page == "wnioski":
        _requests(api, me)
        return
    eid = _my_evaluation_id(api)
    if eid is None:
        st.info("Nie masz jeszcze rozpoczętego cyklu oceny.")
        return
    try:
        ev = api.evaluation(eid)
    except ApiError as e:
        st.error(e.komunikat)
        return
    left, right = st.columns([1.7, 1.3], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Status oceny**")
            ui.mini_stepper(ev)
            c1, c2 = ev["czesc_i"], ev["czesc_ii"]
            ui.html(ui.kv([("Etap", STATUS_LABEL.get(ev["status"], ev["status"])),
                           ("Oceniający", name(ev["oceniajacy"])), ("Arkusz", ev["arkusz"]),
                           ("Termin oceny", ui.fmt(c1["termin_oceny"])),
                           ("Ocena", c2["wynik"].lower() if c2.get("wynik") and c2.get("data_sporzadzenia")
                            else "w trakcie")]))

        for akcja in [a for a in ev["dozwolone_akcje"] if a != "ZLOZ_SPRZECIW"]:  # objection: own page
            with st.container(border=True):
                if akcja == "POTWIERDZ_KRYTERIA":
                    st.markdown("**:material/draw: Do potwierdzenia: rozmowa i kryteria oceny**")
                    ui.html("<b>Kryteria:</b>" + ui.ul(f"{k['nazwa']}{'' if k['typ'] == 'OBOWIAZKOWE' else ' (dodatkowe)'}"
                                                         for k in ev["kryteria"])
                            + f"<p>Termin sporządzenia oceny: <b>{ui.fmt(ev['czesc_i']['termin_oceny'])}</b></p>")
                elif akcja == "POTWIERDZ_ZAPOZNANIE":
                    c2 = ev["czesc_ii"]
                    st.markdown("**:material/draw: Do potwierdzenia: zapoznanie się z oceną**")
                    if c2.get("wynik"):
                        avg = f"{c2['srednia']:.2f}".replace(".", ",")
                        ui.html(f'<div class="result {"pos" if c2["wynik"] == "POZYTYWNA" else "neg"}">Ocena '
                                f'<b>{c2["wynik"]}</b> · średnia {avg} · {escape(LEVEL_LABEL.get(c2["poziom"], ""))}</div>')
                    # keep the evaluator's line breaks and "– " lists (one string with newlines from the server)
                    if c2.get("uzasadnienie"):
                        ui.html("<b>Uzasadnienie:</b><p>" + escape(c2["uzasadnienie"]).replace("\n", "<br>") + "</p>")
                    if c2.get("wnioski_iprz"):
                        ui.html("<b>Wnioski rozwojowe (IPRZ):</b><p>" + escape(c2["wnioski_iprz"]).replace("\n", "<br>")
                                + "</p>")
                key = f"emp_confirm_{eid}_{akcja}"
                if st.session_state.get(key):
                    st.warning(f"Czy na pewno: **{ACTION_LABEL.get(akcja, akcja).lower()}**?")
                    a, b = st.columns(2)
                    if a.button("✔ Tak, potwierdzam", type="primary", key=f"{key}_yes", use_container_width=True):
                        st.session_state.pop(key, None)
                        try:
                            api.action(eid, akcja)
                            st.toast(ACTION_DONE.get(akcja, "Zapisano."))
                        except ApiError as e:
                            st.session_state.setdefault("flash", []).append(("error", " ".join(e.messages)))
                        st.rerun()
                    if b.button("Anuluj", key=f"{key}_no", use_container_width=True):
                        st.session_state.pop(key, None)
                        st.rerun()
                elif st.button(ACTION_LABEL.get(akcja, akcja), type="primary", key=f"{key}_btn",
                               use_container_width=True):
                    st.session_state[key] = True
                    st.rerun()

        # an objection can be filed against the evaluation just acknowledged, even if the next cycle is open
        objectable = [e for e in _my_evaluations(api, me) if "ZLOZ_SPRZECIW" in e["dozwolone_akcje"]]
        for e in objectable[:1]:
            with st.container(border=True):
                st.markdown(f"**:material/gavel: Nie zgadzasz się z oceną?** Sprzeciw do dyrektora generalnego możesz złożyć do "
                            f"**{ui.fmt(e['czesc_ii'].get('termin_sprzeciwu'))}**.")
                st.button("Złóż sprzeciw", type="primary", key=f"to_objection_{e['id']}", on_click=_open_requests)

    with right:
        from frontend.views.team import calendar_button

        calendar_button(api, "emp_ics")
        with st.container(border=True):
            st.markdown("**Moje kryteria**")
            ui.html(ui.ul(k["nazwa"] for k in ev["kryteria"]))
        if ev["status"] in ("OCENA_DO_ZAPOZNANIA", "ZAKONCZONA"):
            from frontend.views.evaluation import pdf_button

            pdf_button(api, ev, key="emp_pdf")
