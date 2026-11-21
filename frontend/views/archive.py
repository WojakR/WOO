"""Archiwum: history of evaluations (GET /api/employees/{id}/evaluations) for everyone who may see it, and for HR
the frozen evaluations, retention periods and the import of old (paper) evaluations – /api/archive, /api/legacy-import.
Everything comes from the server; nothing is decided here."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import LEVEL_LABEL, STATUS_LABEL, name

SOURCE = {"SYSTEM": "w systemie", "IMPORT": "zaimportowana z PDF", "DANE_KADROWE": "z danych kadrowych"}
OBJECTION = {"ZLOZONY": "sprzeciw złożony", "UWZGLEDNIONY": "sprzeciw uwzględniony",
             "NIEUWZGLEDNIONY": "sprzeciw nieuwzględniony"}


def _call(fn, *args, ok: str | None = None, **kw):
    try:
        out = fn(*args, **kw)
    except ApiError as e:
        ui.api_error(e)
        return None
    if ok:
        st.toast(ok)
    return out


def _result(item: dict) -> str:
    w = item.get("wynik")
    if not w:
        return "<span class='lock'>—</span>"
    cls = "b-green" if w == "POZYTYWNA" else "b-red"
    return ui.badge("pozytywna" if w == "POZYTYWNA" else "negatywna", cls)


def _open(eid: int) -> None:
    from frontend.views.team import open_evaluation

    open_evaluation(eid)


def _history_table(api: Api, items: list[dict], key: str, can_open: bool) -> None:
    if not items:
        st.caption("Brak ocen w historii.")
        return
    widths = [1.4, 1.8, 0.5, 1.4, 1.5, 1.1, 1.4, 1.1]
    head = st.columns(widths)
    for col, title in zip(head, ["Data oceny", "Okres oceny", "Ark.", "Oceniający", "Poziom", "Wynik", "Uwagi", ""]):
        col.markdown(f"<span class='lock'><b>{title}</b></span>", unsafe_allow_html=True)
    for item in reversed(items):  # newest first
        c = st.columns(widths, vertical_alignment="center")
        done = item.get("data_sporzadzenia")
        c[0].markdown(ui.fmt(done) if done else f"<i>{STATUS_LABEL.get(item.get('status'), 'w toku').lower()}</i>",
                      unsafe_allow_html=True)
        period = (f"{ui.fmt(item['okres_od'])} – {ui.fmt(item['okres_do'])}" if item.get("okres_od") else "—")
        c[1].markdown(period)
        c[2].markdown(item.get("arkusz") or "—")
        c[3].markdown(name(item.get("oceniajacy")))
        c[4].markdown(LEVEL_LABEL.get(item.get("poziom"), "—"))
        c[5].markdown(_result(item), unsafe_allow_html=True)
        notes = [SOURCE.get(item.get("zrodlo"), "")]
        if item.get("sprzeciw"):
            notes.append(OBJECTION.get(item["sprzeciw"], "sprzeciw"))
        if item.get("srednia") is not None:
            notes.insert(0, f"średnia {item['srednia']}")
        c[6].markdown(f"<span class='lock'>{escape(' · '.join(n for n in notes if n))}</span>", unsafe_allow_html=True)
        eid = item.get("evaluation_id")
        if eid:
            with c[7]:
                if can_open:
                    st.button("Otwórz", key=f"{key}_open_{eid}", on_click=_open, args=(eid,), use_container_width=True)
                st.download_button("⬇️ PDF", lambda eid=eid: api.pdf(eid)[0], file_name=f"ocena-{eid}.pdf",
                                   mime="application/pdf", key=f"{key}_pdf_{eid}", on_click="ignore",
                                   use_container_width=True)


def _team_history(api: Api, me: dict, hr: bool) -> None:
    a, b = st.columns([2, 1])
    q = a.text_input("Pracownik", placeholder="imię lub nazwisko", key="arch_q")
    data = _call(api.employees, szukaj=q or None, na_strone=200)
    if data is None:
        return
    units = data.get("komorki") or []
    unit = b.selectbox("Komórka", ["Wszystkie"] + units, key="arch_unit") if len(units) > 1 else "Wszystkie"
    people = [p for p in data["pozycje"] if p["pracownik"]["id"] != me["pracownik"]["id"] or hr]
    if unit != "Wszystkie":
        people = [p for p in people if p["pracownik"].get("komorka") == unit]
    if not people:
        st.info("Brak osób do pokazania.")
        return
    for row in people:
        p = row["pracownik"]
        last = row.get("ostatnia_ocena")
        label = f"{p['imie']} {p['nazwisko']} · {p.get('stanowisko') or ''}"
        if last and last.get("data"):
            label += f" · ostatnia ocena {ui.fmt(last['data'])}" + (
                f" ({'pozytywna' if last.get('wynik') == 'POZYTYWNA' else 'negatywna'})" if last.get("wynik") else "")
        with st.expander(label):
            items = _call(api.history, p["id"])
            if items is not None:
                _history_table(api, items, f"h{p['id']}", can_open=True)


def _frozen(api: Api) -> None:
    a, b = st.columns([3, 1.3], vertical_alignment="center")
    a.markdown("Zamknięte oceny zamrożone razem z PDF. Suma kontrolna (SHA-256) pokazuje, że nikt ich później "
               "nie zmienił.")
    if b.button("🧊 Zamroź zakończone oceny", use_container_width=True, key="arch_run"):
        out = _call(api.archive_run)
        if out is not None:
            st.toast(f"Zamrożono: {len(out['zamrozono'])}.")
            st.rerun()
    records = _call(api.archive)
    if records is None:
        return
    if not records:
        st.caption("Archiwum jest puste – kliknij „Zamroź zakończone oceny”.")
        return
    widths = [2, 1.2, 1.2, 2.2, 1]
    head = st.columns(widths)
    for col, title in zip(head, ["Pracownik", "Ocena", "Zamrożono", "Spójność", ""]):
        col.markdown(f"<span class='lock'><b>{title}</b></span>", unsafe_allow_html=True)
    for r in records:
        c = st.columns(widths, vertical_alignment="center")
        c[0].markdown(r["pracownik"])
        c[1].markdown(f"nr {r['evaluation_id']}")
        c[2].markdown(ui.fmt(r["zamrozono"]))
        c[3].markdown((ui.badge("✓ zgodna", "b-green") if r["zgodny"] else ui.badge("⚠ niezgodna", "b-red"))
                      + f" <span class='lock'>{r['sha256_pdf'][:12]}…</span>", unsafe_allow_html=True)
        c[4].download_button("⬇️ PDF", lambda rid=r["id"]: api.archive_pdf(rid)[0],
                             file_name=f"archiwum-ocena-{r['evaluation_id']}.pdf", mime="application/pdf",
                             key=f"arch_pdf_{r['id']}", on_click="ignore", use_container_width=True)


def _retention(api: Api) -> None:
    st.markdown("Pozycje, którym minął okres przechowywania. System niczego nie usuwa sam – decyzję podejmuje "
                "administrator.")
    items = _call(api.archive_review)
    if items is None:
        return
    if not items:
        st.success("Nic nie czeka na usunięcie.")
        return
    for i in items:
        with st.container(border=True):
            kind = "akta oceny" if i["rodzaj"] == "AKTA" else "notatki robocze"
            st.markdown(f"**{i['pracownik']}** · {kind} · termin przechowywania minął {ui.fmt(i['termin_przechowywania'])}")
            st.caption(i["powod"])
            sure = st.checkbox("Potwierdzam trwałe usunięcie (nie da się cofnąć)", key=f"ret_ok_{i['rodzaj']}_{i['id']}")
            if st.button("🗑️ Usuń", key=f"ret_del_{i['rodzaj']}_{i['id']}", disabled=not sure):
                fn = api.archive_delete if i["rodzaj"] == "AKTA" else api.archive_delete_notes
                arg = i["id"] if i["rodzaj"] == "AKTA" else i["evaluation_id"]
                if _call(fn, arg, ok="Usunięto.") is not None:
                    st.rerun()


def _legacy(api: Api) -> None:
    st.markdown("Wgraj stary arkusz (PDF albo tekst). System odczyta pola, przeliczy wynik według § 11 i pokaże "
                "rozbieżności. Po zatwierdzeniu ocena trafia do historii pracownika.")
    up = st.file_uploader("Arkusz oceny", type=["pdf", "txt"], key="legacy_up")
    if up is not None and st.button("📥 Odczytaj arkusz", type="primary", key="legacy_go"):
        if _call(api.legacy_upload, up.name, up.getvalue(), ok="Odczytano arkusz.") is not None:
            st.rerun()
    drafts = _call(api.legacy_imports)
    if not drafts:
        return
    for d in reversed(drafts):
        f = d["pola"]
        done = d["status"] == "ZATWIERDZONY"
        title = f"{'✅' if done else '📝'} {d['plik']} · {f.get('pracownik') or f.get('oceniany') or 'nie rozpoznano osoby'}"
        with st.expander(title, expanded=not done):
            ui.html(ui.kv([("Arkusz", f.get("arkusz") or "—"), ("Okres", f"{ui.fmt(f.get('okres_od'))} – {ui.fmt(f.get('okres_do'))}"),
                           ("Data oceny", ui.fmt(f.get("data_sporzadzenia"))),
                           ("Średnia w arkuszu", str(f.get("srednia") or "—")),
                           ("Wyliczona przez system", (d.get("wyliczone") or {}).get("srednia") or "—"),
                           ("Poziom", LEVEL_LABEL.get(f.get("poziom"), "—")),
                           ("Wynik", (f.get("wynik") or "—").lower())]))
            for p in d.get("rozbieznosci", []):
                (st.error if p["waga"] == "BLAD" else st.warning)(p["komunikat"])
            if done:
                st.success("Zatwierdzona – jest w historii pracownika.")
                continue
            blocking = any(p["waga"] == "BLAD" for p in d.get("rozbieznosci", []))
            accept = st.checkbox("Zatwierdzam zgodnie z oryginałem mimo rozbieżności", key=f"legacy_acc_{d['id']}") \
                if blocking else False
            if st.button("Zatwierdź import", key=f"legacy_ok_{d['id']}", type="primary",
                         disabled=blocking and not accept):
                if _call(api.legacy_approve, d["id"], accept, ok="Ocena dodana do historii.") is not None:
                    st.rerun()


def render(api: Api, me: dict) -> None:
    hr = me["rola"] == "KADRY"
    evaluator = hr or me.get("czy_oceniajacy")
    st.subheader("🗄️ Archiwum", help="Historia ocen z serwera: oceny z systemu, zaimportowane z PDF i wpisane w danych "
                 "kadrowych." + (" Zamrażanie ocen, okresy przechowywania i import starych ocen są w panelu administratora."
                                 if hr else ""))
    if not evaluator:
        items = _call(api.history, me["pracownik"]["id"])
        if items is not None:
            _history_table(api, items, "mine", can_open=False)
        return
    _team_history(api, me, hr)
