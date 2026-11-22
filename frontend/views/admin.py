"""Panel administratora (HR only): everything the server lets the administrator change – terms of the regulation
and the criteria (as dated versions), office switches and visibility, default reminders, deputies, the HR data
import, the HR archive tools, RCP and e-Akt. The server validates and stores everything; nothing is decided here."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import STAGES, name, to_date
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
    with st.expander(f":material/folder_open: Wersje wymagań ({len(r.get('wersje', []))})"):
        for v in reversed(r.get("wersje", [])):
            tag = " · obowiązuje" if v.get("aktualna") else " · zaplanowana" if v.get("przyszla") else ""
            st.markdown(f"**Wersja {v['id']}**{tag} · od {ui.fmt(v.get('obowiazuje_od'))} · {v['opis']} "
                        f"<span class='lock'>· ocen w tej wersji: {v.get('oceny', 0)}</span>", unsafe_allow_html=True)
            for z in v.get("zmiany", []):
                st.caption(f"{z.get('nazwa', z.get('klucz'))}: {z.get('stara')} → {z.get('nowa')}")
    with st.expander(":material/policy: Pozostałe wymagania (z ustawy – tylko do odczytu)"):
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
        with st.expander(f"{':material/check_circle:' if c.get('dostepne') else ':material/block:'} {c['nazwa']} · {tag}"):
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
    settings._evaluator_absence(api, me, today)


def _people(api: Api) -> None:
    st.markdown("Import z systemu kadrowego (CSV albo XLSX). Wymagane kolumny: **id, imie, nazwisko, stanowisko**; "
                "opcjonalne m.in. komorka, id_przelozonego, arkusz, email, data_zatrudnienia, data_ostatniej_oceny.")
    up = st.file_uploader("Plik z systemu kadrowego", type=["csv", "xlsx"], key="adm_hr_file")
    start = st.checkbox("Po imporcie rozpocznij oceny osobom, które mają przełożonego i nie mają otwartej oceny",
                        key="adm_hr_start")
    if up is None:
        return
    a, b = st.columns(2)
    preview = a.button(":material/visibility: Podgląd (bez zapisu)", use_container_width=True, key="adm_hr_prev")
    save = b.button(":material/upload_file: Importuj", type="primary", use_container_width=True, key="adm_hr_go")
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


def _staff_changes(api: Api, today: date, kind: str) -> None:
    """Change of position (§ 9) or of the evaluator (art. 81 ust. 8) for a person with an evaluation in progress.
    The server works out the consequences; the result stays on screen until the next change."""
    data = _call(api.employees, na_strone=200)
    if not data:
        return
    rows = {r["pracownik"]["id"]: r for r in data["pozycje"]
            if r.get("biezaca_ocena") and r["pracownik"].get("przelozony")}
    st.markdown("Gdy pracownik **zmienia stanowisko**, przepisy mówią, co dzieje się z jego oceną. Wpisz zmianę – "
                "system policzy skutki i pokaże je powyżej formularza." if kind == "stanowisko" else
                "Gdy pracownik **dostaje innego przełożonego (oceniającego)**, przepisy mówią, kto sporządza ocenę. "
                "Wpisz zmianę – system policzy skutki i pokaże je powyżej formularza.")
    if not rows:
        st.info("Nikt nie ma teraz oceny w toku – zmiany dotyczą osób z rozpoczętą oceną.")
        return
    rkey = f"adm_staff_result_{kind}"
    last = st.session_state.get(rkey)
    if last:
        with st.container(border=True):
            st.markdown(f"**:material/task_alt: {last['tytul']}**")
            st.markdown(last["tekst"])
            if last.get("planowana_id"):
                st.caption("Zmiana wejdzie w życie w dniu zmiany – wtedy kliknij „Wykonaj zmianę”. Dotychczasowy "
                           "oceniający dostał powiadomienie.")
                early = st.checkbox("Dotychczasowy oceniający sporządził ocenę przed zmianą",
                                    key=f"adm_apply_early_{kind}")
                if st.button("Wykonaj zmianę", icon=":material/play_arrow:", key=f"adm_apply_{kind}"):
                    done = _call(api.apply_evaluator_change, last["planowana_id"], early)
                    if done is not None:
                        st.session_state[rkey] = {"tytul": "Zmiana oceniającego wykonana",
                                                  "tekst": done.get("wyjasnienie") or "",
                                                  "evaluation_id": done.get("evaluation_id")}
                        st.rerun()
            if last.get("evaluation_id"):
                from frontend.views.team import open_evaluation

                st.button("Otwórz ocenę", icon=":material/open_in_new:", key=f"adm_staff_open_{kind}",
                          on_click=open_evaluation, args=(last["evaluation_id"],))

    def label(i: int) -> str:
        p = rows[i]["pracownik"]
        return f"{name(p)} · {p.get('stanowisko') or '—'}"

    pid = st.selectbox("1. Pracownik", list(rows), format_func=label, key=f"adm_staff_who_{kind}",
                       help="Lista pokazuje osoby, które mają ocenę w toku.")
    row = rows[pid]
    p, cur = row["pracownik"], row["biezaca_ocena"]
    ui.html(ui.kv([("Stanowisko teraz", p.get("stanowisko") or "—"), ("Arkusz", p.get("arkusz") or "—"),
                   ("Oceniający teraz", name(p["przelozony"])),
                   ("Ocena w toku", f"termin {ui.fmt(cur.get('termin_oceny'))}")]))

    if kind == "stanowisko":
        st.markdown("**2. Nowe stanowisko**")
        a, b, c = st.columns([2, 1, 1.2])
        pos = a.text_input("Nazwa nowego stanowiska", key=f"pos_new_{pid}", placeholder="np. starszy specjalista")
        on = b.date_input("Od kiedy", value=today, key=f"pos_on_{pid}", format="DD.MM.YYYY")
        sheet = c.selectbox("Arkusz oceny", [None, "A", "B", "C"], key=f"pos_sheet_{pid}",
                            format_func=lambda x: "bez zmiany" if x is None else f"zmień na {x}",
                            help="A – kierownik urzędu; B – stanowisko kierujące ludźmi; C – pozostałe stanowiska (§ 3 rozporządzenia). "
                                 "Zmień tylko, jeśli nowe stanowisko wymaga innego arkusza.")
        st.caption("Co zrobi system: jeśli od ostatniej oceny minęło mniej niż 6 miesięcy – wyznaczasz nowe kryteria "
                   "(§ 9 ust. 1); jeśli więcej – sporządzasz ocenę za dotychczasowe stanowisko (art. 81 ust. 6).")
        if st.button("Zapisz zmianę stanowiska", type="primary", key=f"pos_go_{pid}"):
            if not pos.strip():
                st.error("Wpisz nazwę nowego stanowiska.")
                return
            out = _call(api.position_change, pid, on, pos.strip(), sheet)
            if out is not None:
                ev = out.get("ocena") or {}
                st.session_state[rkey] = {
                    "tytul": f"Zmiana stanowiska zapisana: {name(p)} → {pos.strip()}",
                    "tekst": out.get("wyjasnienie") or "", "evaluation_id": ev.get("id") or cur["evaluation_id"]}
                st.rerun()
        return

    st.markdown("**2. Nowy oceniający**")
    boss = p["przelozony"]
    options = {i: r["pracownik"] for i, r in
               {x["pracownik"]["id"]: x for x in data["pozycje"]}.items() if i not in (pid, boss["id"])}
    a, b = st.columns([2, 1])
    new = a.selectbox("Kto będzie oceniał", list(options), key=f"evc_new_{pid}",
                      format_func=lambda i: f"{name(options[i])} · {options[i].get('stanowisko') or ''}")
    when = b.date_input("Od kiedy", value=today, key=f"evc_on_{pid}", format="DD.MM.YYYY")
    chk = _call(api.evaluator_change_check, pid, when)
    early = False
    if chk:
        st.info(chk["wyjasnienie"])
        if chk.get("mozliwa_wczesniejsza_ocena"):
            early = st.checkbox(f"{name(boss)} sporządza ocenę przed odejściem", key=f"evc_early_{pid}",
                                help="Zaznacz, jeśli dotychczasowy oceniający sporządzi ocenę przed zmianą "
                                     "(art. 81 ust. 8 pkt 1). Bez zaznaczenia nowy oceniający przejmuje ocenę.")
    if st.button("Zapisz zmianę oceniającego", type="primary", key=f"evc_go_{pid}"):
        out = _call(api.evaluator_change, pid, new, when, early)
        if out is not None:
            what = {"PRZEJECIE": "Nowy oceniający przejmuje trwającą ocenę.",
                    "NOWY_CYKL": "Rozpoczęto nową ocenę u nowego oceniającego."}.get(out.get("wariant"), "")
            held = (f" Notatki poprzedniego oceniającego ({out['notatki_wstrzymane']}) czekają na przekazanie."
                    if out.get("notatki_wstrzymane") else "")
            planned = out.get("status") == "PLANOWANA"
            st.session_state[rkey] = {
                "planowana_id": out.get("id") if planned else None,
                "tytul": (f"Zmiana oceniającego zaplanowana: {name(p)} – od {ui.fmt(when)} oceniać będzie "
                          f"{name(options[new])}" if planned else
                          f"Zmiana oceniającego zapisana: {name(p)} – od {ui.fmt(when)} ocenia {name(options[new])}"),
                "tekst": f"{what}{held} {out.get('wyjasnienie') or ''}",
                "evaluation_id": out.get("evaluation_id") or cur["evaluation_id"]}
            st.rerun()


def _person_form(prefix: str, form: dict, people: dict[int, dict], today: date) -> dict:
    """Fields of the server's EmployeeForm; returns the form to send."""
    a, b, c = st.columns(3)
    out = dict(form)
    out["imie"] = a.text_input("Imię *", value=form.get("imie") or "", key=f"{prefix}_imie")
    out["nazwisko"] = b.text_input("Nazwisko *", value=form.get("nazwisko") or "", key=f"{prefix}_nazwisko")
    out["email"] = c.text_input("E-mail", value=form.get("email") or "", key=f"{prefix}_email") or None
    a, b = st.columns(2)
    out["stanowisko"] = a.text_input("Stanowisko *", value=form.get("stanowisko") or "", key=f"{prefix}_stan")
    out["komorka"] = b.text_input("Komórka", value=form.get("komorka") or "", key=f"{prefix}_kom")
    boss_ids = [None] + [i for i in people if people[i]["id"] != form.get("_number")]
    cur_boss = form.get("przelozony")
    a, b, c = st.columns([1.6, 1, 1])
    out["przelozony"] = a.selectbox("Przełożony (oceniający)", boss_ids, key=f"{prefix}_boss",
                                    index=boss_ids.index(cur_boss) if cur_boss in boss_ids else 0,
                                    format_func=lambda i: "— brak —" if i is None else
                                    f"{name(people[i])} · {people[i].get('stanowisko') or ''}")
    sheets = [None, "A", "B", "C"]
    out["arkusz"] = b.selectbox("Arkusz", sheets, key=f"{prefix}_ark",
                                index=sheets.index(form.get("arkusz")) if form.get("arkusz") in sheets else 0,
                                format_func=lambda x: "dobierze system" if x is None else f"arkusz {x}",
                                help="A – kierownik urzędu, B – kieruje ludźmi, C – pozostali (§ 3 rozporządzenia).")
    out["data_zatrudnienia"] = c.date_input("Data zatrudnienia", value=to_date(form.get("data_zatrudnienia")),
                                            key=f"{prefix}_zatr", format="DD.MM.YYYY")
    a, b, c = st.columns(3)
    out["kieruje_zespolem"] = a.toggle("Kieruje zespołem", value=bool(form.get("kieruje_zespolem")), key=f"{prefix}_kz")
    out["urzednik_mianowany"] = b.toggle("Urzędnik mianowany", value=bool(form.get("urzednik_mianowany")),
                                         key=f"{prefix}_um")
    out["kierownik_urzedu"] = c.toggle("Kierownik urzędu", value=bool(form.get("kierownik_urzedu")), key=f"{prefix}_ku")
    if out["urzednik_mianowany"]:
        out["stopien_sluzbowy"] = st.number_input("Stopień służbowy", 1, 9, int(form.get("stopien_sluzbowy") or 1),
                                                  key=f"{prefix}_st")
    out["data_ostatniej_oceny"] = st.date_input("Data ostatniej oceny (jeśli była przed systemem)",
                                                value=to_date(form.get("data_ostatniej_oceny")), key=f"{prefix}_ost",
                                                format="DD.MM.YYYY")
    for k in ("data_zatrudnienia", "data_ostatniej_oceny", "data_zakonczenia_zatrudnienia", "data_przyznania_stopnia"):
        if isinstance(out.get(k), date):
            out[k] = out[k].isoformat()
    out.pop("_number", None)
    return out


def _missing(form: dict) -> list[str]:
    return [label for key, label in (("imie", "imię"), ("nazwisko", "nazwisko"), ("stanowisko", "stanowisko"))
            if not (form.get(key) or "").strip()]


def _people_admin(api: Api, today: date) -> None:
    """Employees entered by hand (HR): add, edit, remove the data of a person – the same rules as the HR import."""
    data = _call(api.employees, na_strone=200)
    if data is None:
        return
    people = {r["pracownik"]["id"]: r["pracownik"] for r in data["pozycje"]}
    last = st.session_state.get("adm_people_msg")
    if last:
        st.success(last)
        st.session_state.pop("adm_people_msg", None)
    mode = st.segmented_control("Co chcesz zrobić?", ["dodaj", "edytuj", "usun"], default="dodaj", key="adm_people_mode",
                                format_func={"dodaj": "Dodaj pracownika", "edytuj": "Edytuj dane",
                                             "usun": "Usuń dane pracownika"}.get)
    if mode == "dodaj":
        st.caption("Pola z * są wymagane. Identyfikator (login) system utworzy z imienia i nazwiska.")
        form = _person_form("add", {}, people, today)
        start = st.checkbox("Od razu rozpocznij ocenę okresową (gdy ma przełożonego)", key="add_start")
        if st.button("Dodaj pracownika", type="primary", icon=":material/person_add:", key="add_go"):
            if _missing(form):
                st.error("Uzupełnij: " + ", ".join(_missing(form)) + ".")
                return
            out = _call(api.add_employee, form, start)
            if out is not None:
                st.session_state.adm_people_msg = (f"Dodano: {name(out['pracownik'])}."
                                                   + (" Rozpoczęto ocenę okresową." if out.get("uruchomiony_cykl") else ""))
                for k in [k for k in st.session_state if isinstance(k, str) and k.startswith("add_")]:
                    del st.session_state[k]
                st.rerun()
        return
    pid = st.selectbox("Pracownik", list(people), key=f"adm_people_who_{mode}",
                       format_func=lambda i: f"{name(people[i])} · {people[i].get('stanowisko') or ''}")
    if mode == "edytuj":
        form = _call(api.employee_form, pid)
        if form is None:
            return
        form["_number"] = pid
        new = _person_form(f"edit_{pid}", form, people, today)
        st.caption("Przełożonego osoby z oceną w toku zmienisz w zakładce „Zmiana oceniającego” – tam system "
                   "rozstrzyga, co dzieje się z trwającą oceną.")
        if st.button("Zapisz zmiany", type="primary", icon=":material/save:", key=f"edit_go_{pid}"):
            if _missing(new):
                st.error("Uzupełnij: " + ", ".join(_missing(new)) + ".")
            elif _call(api.update_employee, pid, new) is not None:
                st.session_state.adm_people_msg = f"Zapisano dane: {new['imie']} {new['nazwisko']}."
                st.rerun()
        return
    st.markdown("Usunięcie danych (np. po ustaniu zatrudnienia): zamknięte oceny trafią do archiwum, pozostałe dane "
                "i konto zostaną usunięte, zostaje zapis bez danych osobowych.")
    end = st.date_input("Data ustania zatrudnienia", value=today, key=f"del_end_{pid}", format="DD.MM.YYYY")
    plan = _call(api.removal_preview, pid, end)
    if plan is None:
        return
    ui.html(ui.kv([("Do archiwum (zamknięte oceny)", str(len(plan["do_archiwum"]))),
                   ("Do usunięcia (oceny nie sporządzone)", str(len(plan["do_usuniecia"])))]))
    for p in plan["przeszkody"]:
        st.error(p)
    if not plan["mozna_usunac"]:
        st.caption("Najpierw usuń przeszkody wymienione wyżej.")
        return
    sure = st.checkbox(f"Potwierdzam usunięcie danych: {name(people[pid])} (nie da się cofnąć)", key=f"del_ok_{pid}")
    if st.button("Usuń dane pracownika", icon=":material/person_remove:", disabled=not sure, key=f"del_go_{pid}"):
        out = _call(api.remove_employee, pid, end)
        if out is not None and out.get("usunieto"):
            st.session_state.adm_people_msg = (f"Usunięto dane: {name(people[pid])} · do archiwum: "
                                               f"{len(out['do_archiwum'])} · usunięte konta: {out.get('usuniete_konta', 0)}.")
            st.rerun()


ABSENCE_TYPES = {"L4": "zwolnienie lekarskie", "URLOP_WYPOCZYNKOWY": "urlop wypoczynkowy",
                 "URLOP_RODZICIELSKI": "urlop rodzicielski", "INNA_USPRAWIEDLIWIONA": "inna usprawiedliwiona",
                 "NIEUSPRAWIEDLIWIONA": "nieusprawiedliwiona"}


def _absences(api: Api, today: date) -> None:
    """Absences of the evaluated people: a justified one longer than a month moves the evaluation deadline
    (art. 81 ust. 7) – the server decides and tells the person."""
    data = _call(api.employees, na_strone=200)
    if not data:
        return
    rows = {r["pracownik"]["id"]: r for r in data["pozycje"] if r.get("biezaca_ocena")}
    st.markdown("Nieobecność pracownika z oceną w toku. Usprawiedliwiona nieobecność **dłuższa niż miesiąc** sama "
                "przesuwa termin oceny o czas nieobecności (art. 81 ust. 7) – pracownik dostaje powiadomienie.")
    if not rows:
        st.info("Nikt nie ma teraz oceny w toku.")
        return
    last = st.session_state.pop("adm_abs_msg", None)
    if last:
        st.success(last)
    pid = st.selectbox("Pracownik", list(rows), key="adm_abs_who",
                       format_func=lambda i: f"{name(rows[i]['pracownik'])} · termin oceny "
                                             f"{ui.fmt(rows[i]['biezaca_ocena'].get('termin_oceny'))}")
    a, b, c = st.columns([1, 1, 1.4])
    od = a.date_input("Od", today, key="adm_abs_od", format="DD.MM.YYYY")
    do = b.date_input("Do", today + timedelta(days=30), key="adm_abs_do", format="DD.MM.YYYY")
    kind = c.selectbox("Rodzaj", list(ABSENCE_TYPES), format_func=ABSENCE_TYPES.get, key="adm_abs_type")
    if st.button("Zapisz nieobecność", type="primary", icon=":material/event_busy:", key="adm_abs_go"):
        if do < od:
            st.error("Koniec nieobecności nie może być wcześniejszy niż jej początek.")
        else:
            out = _call(api.add_absence, pid, od, do, kind)
            if out is not None:
                moved = out.get("zmiana_terminu")
                st.session_state.adm_abs_msg = (
                    f"Zapisano nieobecność ({out['dni']} dni). "
                    + (f"Termin oceny przesunięty: {ui.fmt(moved['stary_termin'])} → {ui.fmt(moved['nowy_termin'])}."
                       if moved else f"Termin oceny bez zmian: {ui.fmt(out.get('termin_oceny'))}."))
                st.rerun()
    hist = _call(api.absences, pid) or []
    if hist:
        st.markdown("**Zapisane nieobecności**")
        for h in reversed(hist):
            moved = h.get("zmiana_terminu")
            st.markdown(f"- {ui.fmt(h['od'])} – {ui.fmt(h['do'])} · {ABSENCE_TYPES.get(h['typ'], h['typ'])} · "
                        f"{h['dni']} dni" + (f" · termin przesunięty na {ui.fmt(moved['nowy_termin'])}" if moved else ""))


def _rcp_eakt(api: Api) -> None:
    with st.container(border=True):
        st.markdown("#### :material/timer: Rejestracja czasu pracy (RCP)", help="Dane o nadgodzinach i przerwach trafiają do HR "
                    "partnera jako sygnał przeciążenia.")
        up = st.file_uploader("Plik z RCP (CSV / XLSX)", type=["csv", "xlsx"], key="adm_rcp_file")
        if up is not None and st.button(":material/upload_file: Importuj RCP", type="primary", key="adm_rcp_go"):
            out = _call(api.rcp_import, up.name, up.getvalue())
            if out is not None:
                st.success(f"Zaimportowano dni: {out['zaimportowano']} (osób: {out['pracownicy']}).")
                for e in out.get("bledy", [])[:20]:
                    st.caption(f"Wiersz {e['wiersz']}: {e['komunikat']}")
        rows = _call(api.rcp_summary) or []
        if rows:
            st.dataframe(pd.DataFrame([{"Pracownik": r["pracownik"], "Dni": r["dni"], "Nadgodziny (dni)": r["dni_nadgodziny"],
                                        "Krótka przerwa (dni)": r["dni_krotka_przerwa"], "Po godzinach (dni)": r["dni_po_godzinach"],
                                        "Sygnał przeciążenia": ":material/warning: tak" if r["sygnal"] else "—"} for r in rows]),
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Brak danych z RCP z ostatniego roku.")
    with st.container(border=True):
        st.markdown("#### :material/folder: e-Akta", help="Zatwierdzone oceny trafiają do elektronicznych akt osobowych. Status "
                    "eksportu widać w ocenie (Historia zmian).")
        if st.button(":material/refresh: Ponów nieudane eksporty", key="adm_eakt"):
            out = _call(api.eakt_retry)
            if out is not None:
                if out.get("tryb") == "off":
                    st.info("Integracja z e-Akt jest wyłączona na serwerze.")
                elif not out["ponowiono"]:
                    st.success("Brak nieudanych eksportów.")
                for x in out.get("ponowiono", []):
                    st.caption(f"Ocena {x['evaluation_id']}: {x['status']} (próby: {x['proby']})"
                               + (f" – {x['blad']}" if x.get("blad") else ""))


def _ezd(api: Api) -> None:
    with st.container(border=True):
        st.markdown("#### :material/folder_shared: EZD – elektroniczne zarządzanie dokumentacją",
                    help="Arkusz po zapoznaniu lub po rozpatrzeniu sprzeciwu i pismo o zmianie terminu są rejestrowane "
                         "w systemie obiegu dokumentów urzędu.")
        data = _call(api.ezd)
        if data is None:
            return
        if data.get("tryb") == "off":
            st.info("Integracja z EZD jest wyłączona na serwerze (EZD_MODE=off).")
        else:
            st.caption(f"Tryb: {data.get('tryb')} · JRWA: {data.get('jrwa') or '—'}")
        docs = data.get("dokumenty") or []
        if docs:
            st.dataframe(pd.DataFrame(docs), hide_index=True, use_container_width=True)
        elif data.get("tryb") != "off":
            st.caption("Brak zarejestrowanych dokumentów.")
        if st.button("Ponów nieudane rejestracje", icon=":material/refresh:", key="adm_ezd"):
            out = _call(api.ezd_retry)
            if out is not None:
                st.success(f"Ponowiono: {len(out.get('ponowiono', []))}.")


def render(api: Api, me: dict, meta: dict, users: list[dict]) -> None:
    st.subheader(":material/admin_panel_settings: Panel administratora", help="Ustawienia całego urzędu. Zmiany zapisuje serwer w bazie; "
                 "przepisy zmieniasz jako nowe wersje z datą i podstawą prawną.")
    if me["rola"] != "KADRY":
        st.info("Panel administratora jest dostępny dla działu kadr.")
        return
    today = to_date(meta["dzis"])
    tabs = st.tabs([":material/policy: Terminy", ":material/checklist: Kryteria i etapy", ":material/apartment: Urząd i przypomnienia", ":material/person: Pracownicy", ":material/event_busy: Nieobecności", ":material/upload_file: Import pracowników",
                    ":material/badge: Zmiana stanowiska", ":material/supervisor_account: Zmiana oceniającego", ":material/inventory_2: Archiwum kadr", ":material/timer: RCP, e-Akt i EZD"])
    with tabs[0]:
        _terms(api, today)
    with tabs[1]:
        _criteria(api, today)
    with tabs[2]:
        _office(api, me, users, today)
    with tabs[3]:
        _people_admin(api, today)
    with tabs[4]:
        _absences(api, today)
    with tabs[5]:
        _people(api)
    with tabs[6]:
        _staff_changes(api, today, "stanowisko")
    with tabs[7]:
        _staff_changes(api, today, "oceniajacy")
    with tabs[8]:
        inner = st.tabs([":material/ac_unit: Zamrożone oceny", ":material/hourglass_top: Okresy przechowywania", ":material/upload_file: Import starych ocen"])
        with inner[0]:
            archive._frozen(api)
        with inner[1]:
            archive._retention(api)
        with inner[2]:
            archive._legacy(api)
    with tabs[9]:
        _rcp_eakt(api)
        _ezd(api)
