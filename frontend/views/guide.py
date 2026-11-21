"""Pomoc: the user guide from the server's knowledge base (/api/knowledge) with a search."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError

def render(api: Api) -> None:
    st.subheader("❓ Pomoc", help="Podręcznik użytkownika aplikacji.")
    try:
        docs = [d for d in api.knowledge() if d["rodzaj"] == "PODRECZNIK"]
    except ApiError as e:
        ui.api_error(e)
        return
    if not docs:
        st.info("Brak podręcznika na serwerze.")
        return
    q = st.text_input("Szukaj w podręczniku", placeholder="np. sprzeciw, termin, fikcja zapoznania",
                      key="help_q")
    if q.strip():
        res = api.knowledge_search(q)
        hits = [h for h in res.get("wyniki", []) if h["rodzaj"] == "PODRECZNIK"]
        if res.get("komunikat"):
            st.caption(res["komunikat"])
        elif not hits:
            st.caption("Nic nie znaleziono.")
        for h in hits:
            with st.container(border=True):
                st.markdown(f"**{escape(h['naglowek'])}**<br><span class='lock'>{escape(h['fragment'])}</span>",
                            unsafe_allow_html=True)
        st.divider()
    slugs = [d["slug"] for d in docs]
    if st.session_state.get("help_doc") not in slugs:
        st.session_state.help_doc = slugs[0]
    titles = {d["slug"]: d["tytul"] for d in docs}
    slug = st.selectbox("Dokument", slugs, format_func=titles.get, key="help_doc") if len(slugs) > 1 else slugs[0]
    doc = api.knowledge_doc(slug)
    with st.container(border=True, height=620):
        st.markdown(doc["tresc"])
