"""Frontend demo (Streamlit). Uruchom z głównego folderu: streamlit run frontend/app.py

Woła funkcje backendu bezpośrednio (bez HTTP) – dzięki temu całość deployuje się
jednym kliknięciem na Streamlit Cloud. FastAPI jest obok, jeśli zadanie wymaga API.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from backend import config, db
from backend.llm import ask_llm
from backend.parsers import parse_file, to_llm_text

st.set_page_config(page_title="HackNation 2026", page_icon="🏛️", layout="wide")
st.title("🏛️ Nazwa projektu")
st.caption("Jedno zdanie: dla kogo i jaki problem rozwiązujemy.")

with st.sidebar:
    st.subheader("Status")
    st.write("Modele:", ", ".join(config.LLM_MODELS))
    if config.LLM_MOCK:
        st.warning("Tryb MOCK – LLM zwraca atrapy")
    st.subheader("Ostatnie dokumenty")
    for d in db.list_documents(10):
        st.write(f"#{d['id']} {d['filename']}")

tab1, tab2 = st.tabs(["📄 Dokument", "💬 Zapytaj"])

with tab1:
    up = st.file_uploader("Wrzuć plik (PDF, XML, CSV, XLSX, TXT, obraz)")
    if up:
        kind, content = parse_file(up.getvalue(), up.name)
        text = to_llm_text(kind, content)
        if kind == "table":
            st.dataframe(content, use_container_width=True)
        elif kind == "xml":
            st.json(content, expanded=False)
        else:
            st.text_area("Treść", text[:5000], height=250)

        task = st.text_input("Co zrobić z dokumentem?", "Streść najważniejsze informacje w 5 punktach.")
        if st.button("Analizuj", type="primary"):
            with st.spinner("Myślę..."):
                answer = ask_llm(f"Dokument:\n{text}\n\nZadanie: {task}")
            st.markdown(answer)
            db.save_document(up.name, kind, text, {"task": task, "answer": answer})

with tab2:
    q = st.chat_input("Zadaj pytanie")
    if q:
        st.chat_message("user").write(q)
        with st.spinner("Myślę..."):
            st.chat_message("assistant").write(ask_llm(q))
