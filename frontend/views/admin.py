"""Panel administratora (HR only): everything the server lets the administrator change – terms of the regulation
and the criteria (as dated versions), office switches and visibility, default reminders, deputies, the HR data
import, the HR archive tools, RCP and e-Akt. The server validates and stores everything; nothing is decided here."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import STAGES, to_date
from frontend.views import archive, settings

STAGE_TEXT = (
    "Przełożony wyznacza kryteria dodatkowe i omawia je z ocenianym; oceniany potwierdza kryteria.",
    "Przez okres oceny przełożony zapisuje obserwacje (notatki) przypisane do kryteriów.",
    "Rozmowa oceniająca – omówienie wyników przed sporządzeniem oceny.",
    "Przełożony wypełnia arkusz (punkty, uzasadnienie, wnioski IPRZ) i zatwierdza ocenę.",
    "Oceniany zapoznaje się z oceną i podpisuje ją (albo obieg papierowy / odmowa podpisu); potem 7 dni na sprzeciw.",
)


def _call(fn, *args, ok: str | None = None, **kw):
    try:
        out = fn(*args, **kw)
    except ApiError as e:
        ui.api_error(e)
        return None
    if ok:
        st.toast(ok)
    return out


def _version_fields(prefix: str, today: date) -> tuple[date, str]:
    a, b = st.columns([1, 2.6])
    when = a.date_input("Obowiązuje od", value=today, min_value=today, format="DD.MM.YYYY", key=f"{prefix}_from",
                        help="Nowa wersja dotyczy ocen rozpoczętych od tego dnia – trwające oceny zostają przy "
                             "wersji, z którą się zaczęły.")
    basis = b.text_input("Podstawa zmiany (wymagana)", key=f"{prefix}_basis",
                         placeholder="np. nowelizacja rozporządzenia, Dz. U. 2027 poz. 123")
    return when, basis.strip()


def _terms(api: Api, today: date) -> None:
    r = _call(api.rules)
    if r is None:
        return
    st.markdown("Terminy i częstotliwość ocen, których pilnuje system. Po nowelizacji przepisów zmieniasz je tutaj – "
                "bez przebudowy aplikacji. Każda zmiana tworzy nową wersję wymagań z datą i podstawą prawną.")
    if r["zmienione"]:
        st.warning("Część wartości różni się od opublikowanego rozporządzenia.")
    values = {}
    for p in r["parametry"]:
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.markdown(f"**{p['nazwa']}** <span class='lock'>({p['podstawa']}; w rozporządzeniu: {p['domyslna']} "
                    f"{p['jednostka']})</span>", unsafe_allow_html=True)
        values[p["klucz"]] = c2.number_input(p["jednostka"], min_value=p["min"], max_value=p["max"],
                                             value=p["wartosc"], key=f"adm_rule_{p['klucz']}")
    changed = {k: v for k, v in values.items() if v != next(p["wartosc"] for p in r["parametry"] if p["klucz"] == k)}
    when, basis = _version_fields("adm_terms", today)
    a, b = st.columns(2)
    if a.button("Zapisz nową wersję terminów", type="primary", disabled=not changed, use_container_width=True):
        if not basis:
            st.error("Wpisz podstawę zmiany, np. numer nowelizacji.")
        elif _call(api.set_rules, changed, basis, from_date=when, ok="Zapisano nową wersję wymagań.") is not None:
            st.rerun()
    if r["zmienione"] and b.button("Przywróć wartości z rozporządzenia", use_container_width=True):
        if _call(api.reset_rules, ok="Przywrócono wartości z rozporządzenia.") is not None:
            st.rerun()
    with st.expander(f"🗂️ Wersje wymagań ({len(r.get('wersje', []))})"):
        for v in reversed(r.get("wersje", [])):
            tag = " · obowiązuje" if v.get("aktualna") else " · zaplanowana" if v.get("przyszla") else ""
            st.markdown(f"**Wersja {v['id']}**{tag} · od {ui.fmt(v.get('obowiazuje_od'))} · {v['opis']} "
                        f"<span class='lock'>· ocen w tej wersji: {v.get('oceny', 0)}</span>", unsafe_allow_html=True)
            for z in v.get("zmiany", []):
                st.caption(f"{z.get('nazwa', z.get('klucz'))}: {z.get('stara')} → {z.get('nowa')}")
    with st.expander("📜 Pozostałe wymagania (z ustawy – tylko do odczytu)"):
        for w in r["wymagania"]:
            st.markdown(f"**{w['tytul']}**")
            st.markdown(w["tresc"])
            st.caption(w["podstawa"])


def _criteria(api: Api, today: date) -> None:
    r = _call(api.rules)
    if r is None:
        return
    st.markdown("**Etapy oceny** <span class='lock'>(wynikają z ustawy i rozporządzenia – stałe)</span>",
                unsafe_allow_html=True)
    for n, (stage, text) in enumerate(zip(STAGES, STAGE_TEXT), start=1):
        st.markdown(f"{n}. **{stage}** – {text}")
    st.divider()
    st.markdown("**Kryteria i arkusze A / B / C** – możesz zmienić nazwę, wskaźniki i dostępność kryterium. "
                "Zmiana tworzy nową wersję wymagań (trwające oceny jej nie dostają).")
    sheet = st.segmented_control("Pokaż arkusz", ["Wszystkie", "A", "B", "C"], default="Wszystkie", key="adm_sheet")
    edits: dict[str, dict] = {}
    for c in r.get("kryteria", []):
        if sheet not in (None, "Wszystkie") and sheet not in c.get("obowiazkowe_w", []) and not c.get("dostepne"):
            continue
        mand = c.get("obowiazkowe_w", [])
        tag = f"obowiązkowe w arkuszu {', '.join(mand)}" if mand else "dodatkowe"
        if sheet not in (None, "Wszystkie") and sheet not in mand:
            tag = "dodatkowe w tym arkuszu"
        with st.expander(f"{'✅' if c.get('dostepne') else '⛔'} {c['nazwa']} · {tag}"):
            name = st.text_input("Nazwa", value=c["nazwa"], key=f"adm_cn_{c['id']}")
            ind = st.text_area("Wskaźniki (jeden w wierszu)", value="\n".join(c.get("wskazniki", [])),
                               key=f"adm_ci_{c['id']}", height=130)
            avail = st.toggle("Dostępne do wyboru", value=bool(c.get("dostepne")), key=f"adm_ca_{c['id']}",
                              disabled=bool(mand), help="Kryteriów obowiązkowych nie można wyłączyć.")
            change = {}
            if name.strip() != c["nazwa"]:
                change["nazwa"] = name.strip()
            lines = [x.strip() for x in ind.splitlines() if x.strip()]
            if lines != c.get("wskazniki", []):
                change["wskazniki"] = lines
            if avail != bool(c.get("dostepne")):
                change["dostepne"] = avail
            if change:
                edits[c["id"]] = change
    if edits:
        st.info(f"Zmienione kryteria: {len(edits)}.")
    when, basis = _version_fields("adm_crit", today)
    if st.button("Zapisz nową wersję kryteriów", type="primary", disabled=not edits):
        if not basis:
            st.error("Wpisz podstawę zmiany.")
        elif _call(api.set_rules, {}, basis, criteria=edits, from_date=when, ok="Zapisano nową wersję kryteriów.") \
                is not None:
            st.rerun()


def _office(api: Api, me: dict, users: list[dict], today: date) -> None:
    settings._assistant(api, me)
    settings._visibility(api, me)
    settings._reminders(api, me)
    settings._deputies(api, me, users, today)


def _people(api: Api) -> None:
    st.markdown("Import z systemu kadrowego (CSV albo XLSX). Wymagane kolumny: **id, imie, nazwisko, stanowisko**; "
                "opcjonalne m.in. komorka, id_przelozonego, arkusz, email, data_zatrudnienia, data_ostatniej_oceny.")
    up = st.file_uploader("Plik z systemu kadrowego", type=["csv", "xlsx"], key="adm_hr_file")
    start = st.checkbox("Po imporcie rozpocznij oceny osobom, które mają przełożonego i nie mają otwartej oceny",
                        key="adm_hr_start")
    if up is None:
        return
    a, b = st.columns(2)
    preview = a.button("👁️ Podgląd (bez zapisu)", use_container_width=True, key="adm_hr_prev")
    save = b.button("📥 Importuj", type="primary", use_container_width=True, key="adm_hr_go")
    if not (preview or save):
        return
    out = _call(api.import_employees, up.name, up.getvalue(), preview=preview, start_cycles=start)
    if out is None:
        return
    st.markdown(f"Wierszy: **{out['liczba_wierszy']}** · nowi: **{len(out['dodani'])}** · "
                f"zaktualizowani: **{len(out['zaktualizowani'])}** · problemy: **{len(out['problemy'])}**")
    if out["problemy"]:
        st.dataframe(pd.DataFrame([{"Wiersz": p["wiersz"], "Id": p.get("id") or "", "Problem": p["komunikat"]}
                                   for p in out["problemy"]]), hide_index=True, use_container_width=True)
    if out["zapisano"]:
        st.success("Zaimportowano." + (f" Rozpoczęte oceny: {len(out['uruchomione_cykle'])}."
                                        if out["uruchomione_cykle"] else ""))
    elif not out["podglad"]:
        st.error("Nic nie zapisano – popraw problemy w pliku i spróbuj ponownie.")


def _rcp_eakt(api: Api) -> None:
    with st.container(border=True):
        st.markdown("#### ⏱️ Rejestracja czasu pracy (RCP)", help="Dane o nadgodzinach i przerwach trafiają do HR "
                    "partnera jako sygnał przeciążenia.")
        up = st.file_uploader("Plik z RCP (CSV / XLSX)", type=["csv", "xlsx"], key="adm_rcp_file")
        if up is not None and st.button("📥 Importuj RCP", type="primary", key="adm_rcp_go"):
            out = _call(api.rcp_import, up.name, up.getvalue())
            if out is not None:
                st.success(f"Zaimportowano dni: {out['zaimportowano']} (osób: {out['pracownicy']}).")
                for e in out.get("bledy", [])[:20]:
                    st.caption(f"Wiersz {e['wiersz']}: {e['komunikat']}")
        rows = _call(api.rcp_summary) or []
        if rows:
            st.dataframe(pd.DataFrame([{"Pracownik": r["pracownik"], "Dni": r["dni"], "Nadgodziny (dni)": r["dni_nadgodziny"],
                                        "Krótka przerwa (dni)": r["dni_krotka_przerwa"], "Po godzinach (dni)": r["dni_po_godzinach"],
                                        "Sygnał przeciążenia": "⚠️ tak" if r["sygnal"] else "—"} for r in rows]),
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Brak danych z RCP z ostatniego roku.")
    with st.container(border=True):
        st.markdown("#### 📁 e-Akta", help="Zatwierdzone oceny trafiają do elektronicznych akt osobowych. Status "
                    "eksportu widać w ocenie (Historia zmian).")
        if st.button("🔁 Ponów nieudane eksporty", key="adm_eakt"):
            out = _call(api.eakt_retry)
            if out is not None:
                if out.get("tryb") == "off":
                    st.info("Integracja z e-Akt jest wyłączona na serwerze.")
                elif not out["ponowiono"]:
                    st.success("Brak nieudanych eksportów.")
                for x in out.get("ponowiono", []):
                    st.caption(f"Ocena {x['evaluation_id']}: {x['status']} (próby: {x['proby']})"
                               + (f" – {x['blad']}" if x.get("blad") else ""))


def render(api: Api, me: dict, meta: dict, users: list[dict]) -> None:
    st.subheader("🛠️ Panel administratora", help="Ustawienia całego urzędu. Zmiany zapisuje serwer w bazie; "
                 "przepisy zmieniasz jako nowe wersje z datą i podstawą prawną.")
    if me["rola"] != "KADRY":
        st.info("Panel administratora jest dostępny dla działu kadr.")
        return
    today = to_date(meta["dzis"])
    tabs = st.tabs(["📜 Terminy", "📋 Kryteria i etapy", "🏢 Urząd i przypomnienia", "👥 Import pracowników",
                    "🗄️ Archiwum kadr", "⏱️ RCP i e-Akt"])
    with tabs[0]:
        _terms(api, today)
    with tabs[1]:
        _criteria(api, today)
    with tabs[2]:
        _office(api, me, users, today)
    with tabs[3]:
        _people(api)
    with tabs[4]:
        inner = st.tabs(["🧊 Zamrożone oceny", "⏳ Okresy przechowywania", "📥 Import starych ocen"])
        with inner[0]:
            archive._frozen(api)
        with inner[1]:
            archive._retention(api)
        with inner[2]:
            archive._legacy(api)
    with tabs[5]:
        _rcp_eakt(api)
