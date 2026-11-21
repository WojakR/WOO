"""Absences page (UC8): register an absence of the evaluated person. Whether and how far the evaluation deadline
moves is decided by the server (art. 81 ust. 7) – this page shows what it returns."""
from __future__ import annotations

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import STATUS_LABEL, name, to_date

TYPES = {"L4": "Zwolnienie lekarskie", "URLOP_WYPOCZYNKOWY": "Urlop wypoczynkowy",
         "URLOP_RODZICIELSKI": "Urlop związany z rodzicielstwem", "INNA_USPRAWIEDLIWIONA": "Inna usprawiedliwiona",
         "NIEUSPRAWIEDLIWIONA": "Nieusprawiedliwiona"}
CHANGE_STATUS = {"AUTO": "automatycznie (nieobecność)", "ZLOZONY": "złożony", "ZAAKCEPTOWANY": "przyjęty",
                 "ODRZUCONY": "odrzucony"}


def render(api: Api, me: dict, meta: dict) -> None:
    st.subheader("🏥 Nieobecności")
    st.caption("Usprawiedliwiona, ciągła nieobecność dłuższa niż miesiąc przedłuża termin oceny o czas jej trwania. "
               "Wpisz okres – system sam sprawdzi, czy termin się przesuwa.")
    people = [i for i in api.dashboard()["pozycje"] if i["evaluation_id"] and i["status"] not in ("ZAKONCZONA",)]
    if not people:
        st.info("Brak pracowników z otwartym cyklem oceny.")
        return
    ids = [i["oceniany"]["id"] for i in people]
    pick = st.selectbox("Oceniany", ids, format_func=lambda x: next(
        f"{name(i['oceniany'])} – {STATUS_LABEL.get(i['status'], '')}" for i in people if i["oceniany"]["id"] == x),
        key="abs_person")
    item = next(i for i in people if i["oceniany"]["id"] == pick)
    ev = api.evaluation(item["evaluation_id"])
    today = to_date(meta["dzis"])

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Zgłoś nieobecność**")
            with st.form("abs_form", border=False):
                c1, c2 = st.columns(2)
                od = c1.date_input("Od", today, format="DD.MM.YYYY")
                do = c2.date_input("Do (włącznie)", today, format="DD.MM.YYYY")
                typ = st.selectbox("Rodzaj nieobecności", list(TYPES), format_func=TYPES.get)
                st.markdown(f"Termin oceny teraz: **{ui.fmt(ev['czesc_i']['termin_oceny'])}**")
                sent = st.form_submit_button("Zgłoś nieobecność", type="primary")
            if sent:
                if do < od:
                    st.error("Data „do” jest wcześniejsza niż data „od”.")
                else:
                    try:
                        r = api.add_absence(pick, od, do, typ)
                    except ApiError as e:
                        ui.api_error(e)
                    else:
                        ch = r.get("zmiana_terminu")
                        st.session_state["abs_result"] = (
                            f"Termin oceny przesunięty: {ui.fmt(ch['stary_termin'])} → {ui.fmt(ch['nowy_termin'])}."
                            if ch else f"Nieobecność zapisana ({r['dni']} dni). Termin oceny bez zmian: "
                                       f"{ui.fmt(r.get('termin_oceny'))}.")
                        st.rerun()
            if st.session_state.get("abs_result"):
                st.success(st.session_state.pop("abs_result"))
    with right:
        with st.container(border=True):
            st.markdown("**Zgłoszone nieobecności**")
            rows = api.absences(pick)
            if not rows:
                st.caption("Brak zgłoszonych nieobecności.")
            for a in sorted(rows, key=lambda a: a["od"], reverse=True):
                effect = (f"termin → {ui.fmt(a['zmiana_terminu']['nowy_termin'])}" if a.get("zmiana_terminu")
                          else "bez zmiany terminu")
                st.markdown(f"- {ui.fmt(a['od'])} – {ui.fmt(a['do'])} · {a['dni']} dni · {TYPES.get(a['typ'], a['typ'])}"
                            f" · {effect}")
            changes = api.deadline_changes(item["evaluation_id"])
            if changes:
                st.markdown("**Historia zmian terminu oceny**")
                for c in changes:
                    st.markdown(f"- {ui.fmt(c['stary_termin'])} → {ui.fmt(c['nowy_termin'])} · "
                                f"{CHANGE_STATUS.get(c['status'], c['status'])}")
