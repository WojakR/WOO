"""View 3: the evaluated person – their own evaluation from the API (read-only sheet + their own steps)."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError, as_hr
from frontend.process import ACTION_DONE, ACTION_LABEL, LEVEL_LABEL, STATUS_LABEL, name


def _my_evaluation_id(me: dict) -> int | None:
    """The contract has no "my evaluations" endpoint yet (docs/api.md: GET /api/evaluations?oceniany_id=):
    look the id up in the office list, then read the evaluation as the user (the server checks access)."""
    mine = [i for i in as_hr().dashboard()["pozycje"] if i["oceniany"]["id"] == me["pracownik"]["id"]]
    return mine[0]["evaluation_id"] if mine else None


def render(api: Api, me: dict, page: str = "ocena") -> None:
    person = me["pracownik"]
    st.subheader(f"Moje wnioski – {name(person)}" if page == "wnioski" else f"Moja ocena okresowa – {name(person)}")
    if page == "wnioski":
        st.info("Wnioski pracownika (zmiana terminu oceny, sprzeciw) czekają na obsługę w backendzie – w API nie ma "
                "jeszcze endpointów do ich składania. Gdy koledzy je dodadzą, pojawią się tutaj.")
        return
    eid = _my_evaluation_id(me)
    if eid is None:
        st.info("Nie masz jeszcze rozpoczętego cyklu oceny.")
        return
    try:
        ev = api.evaluation(eid)
    except ApiError as e:
        st.error(e.komunikat)
        return
    for kind, text in st.session_state.pop("flash", []):
        (st.error if kind == "error" else st.success)(text)

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

        for akcja in ev["dozwolone_akcje"]:
            with st.container(border=True):
                if akcja == "POTWIERDZ_KRYTERIA":
                    st.markdown("**✍️ Do potwierdzenia: rozmowa i kryteria oceny**")
                    ui.html("<b>Kryteria:</b>" + ui.ul(f"{k['nazwa']}{'' if k['typ'] == 'OBOWIAZKOWE' else ' (dodatkowe)'}"
                                                         for k in ev["kryteria"])
                            + f"<p>Termin sporządzenia oceny: <b>{ui.fmt(ev['czesc_i']['termin_oceny'])}</b></p>")
                elif akcja == "POTWIERDZ_ZAPOZNANIE":
                    c2 = ev["czesc_ii"]
                    st.markdown("**✍️ Do potwierdzenia: zapoznanie się z oceną**")
                    if c2.get("wynik"):
                        avg = f"{c2['srednia']:.2f}".replace(".", ",")
                        ui.html(f'<div class="result {"pos" if c2["wynik"] == "POZYTYWNA" else "neg"}">Ocena '
                                f'<b>{c2["wynik"]}</b> · średnia {avg} · {escape(LEVEL_LABEL.get(c2["poziom"], ""))}</div>')
                    if c2.get("uzasadnienie"):
                        ui.html(f"<b>Uzasadnienie:</b><p>{escape(c2['uzasadnienie'])}</p>")
                    if c2.get("wnioski_iprz"):
                        ui.html(f"<b>Wnioski rozwojowe (IPRZ):</b><p>{escape(c2['wnioski_iprz'])}</p>")
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

        if ev["status"] == "ZAKONCZONA" and ev["czesc_ii"].get("termin_sprzeciwu"):
            st.info(f"Jeśli nie zgadzasz się z oceną, możesz złożyć sprzeciw do dyrektora generalnego do "
                    f"**{ui.fmt(ev['czesc_ii']['termin_sprzeciwu'])}**.")

    with right:
        with st.container(border=True):
            st.markdown("**Moje kryteria**")
            ui.html(ui.ul(k["nazwa"] for k in ev["kryteria"]))
        if ev["status"] in ("OCENA_DO_ZAPOZNANIA", "ZAKONCZONA"):
            from frontend.views.evaluation import pdf_button

            pdf_button(api, ev, key="emp_pdf")
