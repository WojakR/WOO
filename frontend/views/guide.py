"""Pomoc: the user guide and the regulations from the server's knowledge base (/api/knowledge) with a search."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError

KIND = {"PODRECZNIK": "📘 Podręcznik", "PRZEPISY": "⚖️ Przepisy"}


def _pick(slug: str) -> None:
    st.session_state.help_doc = slug


def render(api: Api) -> None:
    st.subheader("❓ Pomoc", help="Podręcznik użytkownika i przepisy o ocenach okresowych – te same teksty, z których "
                 "korzysta asystent AI.")
    try:
        docs = api.knowledge()
    except ApiError as e:
        ui.api_error(e)
        return
    if not docs:
        st.info("Baza wiedzy jest pusta.")
        return
    q = st.text_input("Szukaj w podręczniku i przepisach", placeholder="np. sprzeciw, termin, fikcja zapoznania",
                      key="help_q")
    if q.strip():
        res = api.knowledge_search(q)
        hits = res.get("wyniki", [])
        if res.get("komunikat"):
            st.caption(res["komunikat"])
        elif not hits:
            st.caption("Nic nie znaleziono.")
        for h in hits:
            with st.container(border=True):
                c = st.columns([5, 1], vertical_alignment="center")
                c[0].markdown(f"**{escape(h['tytul'])}** · {escape(h['naglowek'])}<br>"
                              f"<span class='lock'>{escape(h['fragment'])}</span>", unsafe_allow_html=True)
                c[1].button("Otwórz", key=f"help_hit_{h['slug']}_{h['kotwica']}", on_click=_pick, args=(h["slug"],),
                            use_container_width=True)
        st.divider()
    slugs = [d["slug"] for d in docs]
    if st.session_state.get("help_doc") not in slugs:
        st.session_state.help_doc = slugs[0]
    titles = {d["slug"]: f"{KIND.get(d['rodzaj'], '📄')} · {d['tytul']}" for d in docs}
    slug = st.selectbox("Dokument", slugs, format_func=titles.get, key="help_doc")
    doc = api.knowledge_doc(slug)
    with st.container(border=True, height=620):
        st.markdown(doc["tresc"])
