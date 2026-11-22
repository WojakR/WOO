"""Settings page – everything is stored on the server:
my assistant switch (GET/PUT /api/me/asystent), office settings and regulation terms for HR
(/api/ustawienia/urzad, /api/ustawienia/reguly), reminder schedules (/api/me/przypomnienia, office default for HR)
and deputies (/api/zastepstwa)."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import name, to_date

STAGES = [("WYZNACZENIE_KRYTERIOW", "Wyznaczenie kryteriów", "np. co 7 dni, dopóki kryteria nie są wyznaczone"),
          ("OKRES_OCENY", "Okres oceny", "np. po 50 % i 75 % okresu, 2 miesiące i 2 tygodnie przed terminem"),
          ("ZAPOZNANIE", "Zapoznanie się z oceną", "np. co 3 dni, dopóki oceniany nie potwierdzi"),
          ("ROZPATRZENIE_SPRZECIWU", "Rozpatrzenie sprzeciwu", "np. 3 dni przed terminem rozstrzygnięcia")]
KINDS = {"CO_DNI": "co … dni", "DNI_PRZED": "… dni przed terminem", "TYGODNIE_PRZED": "… tygodni przed terminem",
         "MIESIACE_PRZED": "… miesięcy przed terminem", "PROCENT_OKRESU": "po … % okresu"}


def _ok(fn, *args, ok: str, **kw) -> bool:
    try:
        fn(*args, **kw)
    except ApiError as e:
        ui.api_error(e)
        return False
    st.toast(ok)
    return True


def _assistant(api: Api, me: dict) -> None:
    hr = me["rola"] == "KADRY"
    with st.container(border=True):
        st.markdown("#### :material/smart_toy: Asystent AI i HR partner", help="Asystenta AI włączasz przełącznikiem w prawym górnym "
                    "rogu – ustawienie zapisuje się na Twoim koncie. Wyłączenie przez kadry obowiązuje cały urząd.")
        if hr:
            o = api.office()
            if o["tryb_ai_serwera"] == "OFF":
                st.caption("Serwer nie ma skonfigurowanego modelu – asystent AI działa na szablonach i regułach.")
            a = st.toggle("Asystent AI w całym urzędzie", value=o["asystent_ai"], key="office_ai",
                          help="Wyłączenie obowiązuje wszystkich – nikt nie dostanie podpowiedzi modelu językowego.")
            b = st.toggle("Wirtualny HR partner w całym urzędzie", value=o["hr_partner"], key="office_hr")
            if (a, b) != (o["asystent_ai"], o["hr_partner"]):
                if _ok(api.set_office, asystent_ai=a, hr_partner=b, ok="Zapisano ustawienia urzędu."):
                    st.rerun()
            return
        mine = api.my_assistant()
        if not mine["asystent_ai_w_urzedzie"]:
            st.info("Asystent AI jest wyłączony dla całego urzędu (decyzja kadr).")
        b = st.toggle("Wirtualny HR partner – podpowiedzi o dobrostanie i docenianiu", value=mine["hr_partner"],
                      key="my_hr", disabled=not mine["hr_partner_w_urzedzie"])
        if b != mine["hr_partner"]:
            if _ok(api.set_my_assistant, hr_partner=b, ok="Zapisano."):
                st.rerun()


def _visibility(api: Api, me: dict) -> None:
    o = api.office()
    with st.container(border=True):
        st.markdown("#### :material/visibility: Widoczność ocen")
        opts = {"PODDRZEWO": "Przełożony widzi oceny całego swojego pionu (podwładnych i ich podwładnych)",
                "BEZPOSREDNI": "Przełożony widzi tylko oceny osób, które bezpośrednio ocenia"}
        choice = st.radio("Kto widzi oceny", list(opts), format_func=opts.get,
                          index=list(opts).index(o["zakres_widocznosci"]), disabled=not o["moze_edytowac"],
                          key="office_vis", label_visibility="collapsed")
        if choice != o["zakres_widocznosci"] and st.button("Zapisz widoczność", type="primary"):
            if _ok(api.set_office, zakres_widocznosci=choice, ok="Zapisano widoczność ocen."):
                st.rerun()


def _rules(api: Api, me: dict) -> None:
    r = api.rules()
    with st.container(border=True):
        st.markdown("#### :material/policy: Wymagania z rozporządzenia", help="To, czego pilnuje system. Po nowelizacji przepisów "
                    "administrator (kadry) zmienia tu terminy – bez przebudowy aplikacji. Każda zmiana jest zapisywana "
                    "razem z podstawą prawną.")
        if r["zmienione"]:
            st.warning("Część wartości różni się od opublikowanego rozporządzenia – zobacz historię zmian poniżej.")
        for w in r["wymagania"]:
            with st.expander(w["tytul"]):
                st.markdown(w["tresc"])
                st.caption(w["podstawa"])
        values = {}
        for p in r["parametry"]:
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.markdown(f"**{p['nazwa']}** <span class='lock'>({p['podstawa']}; w rozporządzeniu: {p['domyslna']} "
                        f"{p['jednostka']})</span>", unsafe_allow_html=True)
            values[p["klucz"]] = c2.number_input(p["jednostka"], min_value=p["min"], max_value=p["max"],
                                                 value=p["wartosc"], key=f"rule_{p['klucz']}",
                                                 disabled=not r["moze_edytowac"])
        changed = {k: v for k, v in values.items() if v != next(p["wartosc"] for p in r["parametry"] if p["klucz"] == k)}
        if r["moze_edytowac"]:
            basis = st.text_input("Podstawa zmiany (wymagana)", placeholder="np. nowelizacja rozporządzenia, Dz. U. 2027 poz. 123",
                                  key="rule_basis")
            a, b = st.columns(2)
            if a.button("Zapisz zmiany wymagań", type="primary", disabled=not changed, use_container_width=True):
                if not basis.strip():
                    st.error("Wpisz podstawę zmiany, np. numer nowelizacji.")
                elif _ok(api.set_rules, changed, basis.strip(), ok="Zapisano wymagania."):
                    st.rerun()
            if r["zmienione"] and b.button("Przywróć wartości z rozporządzenia", use_container_width=True):
                if _ok(api.reset_rules, ok="Przywrócono wartości z rozporządzenia."):
                    st.rerun()
        if r["zmiany"]:
            st.markdown("**Historia zmian**")
            for z in r["zmiany"]:
                st.markdown(f"- {ui.fmt(z['kiedy'])}: {z['nazwa']} {z['stara']} → **{z['nowa']}** "
                            f"({z['podstawa_zmiany']}; {z['kto']})")


def _reminders(api: Api, me: dict) -> None:
    hr = me["rola"] == "KADRY"
    data = api.reminders(office=hr)
    with st.container(border=True):
        st.markdown("#### :material/notifications: Przypomnienia" + (" – domyślne dla urzędu" if hr else ""), help=(
            ("Domyślny harmonogram urzędu – każdy pracownik może ustawić własny. " if hr else
             ("Używasz własnego harmonogramu. " if data["wlasne"] else "Używasz domyślnego harmonogramu urzędu. "))
            + f"Przypomnienia przychodzą tylko w dni robocze, w godzinach pracy urzędu "
              f"({data['godziny_pracy'][0]}–{data['godziny_pracy'][1]})."))
        start, end = data["godziny_pracy"]
        hours = []
        hh, mm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        while hh * 60 + mm < eh * 60 + em:
            hours.append(f"{hh:02d}:{mm:02d}")
            mm += 30
            if mm == 60:
                hh, mm = hh + 1, 0
        hour = st.selectbox("Godzina przypomnień", hours, index=hours.index(data["godzina"]) if data["godzina"] in hours else 0,
                            key="rem_hour")
        key = "rem_rules"
        if key not in st.session_state:
            st.session_state[key] = {k: [dict(r) for r in data["etapy"].get(k, [])] for k, _, _ in STAGES}
        rules = st.session_state[key]
        for k, title, hint in STAGES:
            st.markdown(f"**{title}** <span class='lock'>{hint}</span>", unsafe_allow_html=True)
            for i, r in enumerate(list(rules[k])):
                c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
                r["rodzaj"] = c1.selectbox("Rodzaj", list(KINDS), index=list(KINDS).index(r["rodzaj"]),
                                           format_func=KINDS.get, key=f"rem_{k}_{i}_k", label_visibility="collapsed")
                r["wartosc"] = c2.number_input("Wartość", min_value=0, max_value=730, value=int(r["wartosc"]),
                                               key=f"rem_{k}_{i}_v", label_visibility="collapsed")
                if c3.button("Usuń", key=f"rem_{k}_{i}_del", use_container_width=True):
                    rules[k].pop(i)
                    st.rerun()
            if st.button("+ Dodaj przypomnienie", key=f"rem_{k}_add"):
                rules[k].append({"rodzaj": "DNI_PRZED", "wartosc": 7})
                st.rerun()
        a, b = st.columns(2)
        if a.button("Zapisz przypomnienia", type="primary", use_container_width=True, key="rem_save"):
            body = {"godzina": hour, "etapy": {k: [{"rodzaj": r["rodzaj"], "wartosc": r["wartosc"]} for r in v]
                                               for k, v in rules.items()}}
            if _ok(api.set_reminders, body, office=hr, ok="Zapisano przypomnienia."):
                st.session_state.pop(key, None)
                st.rerun()
        if not hr and data["wlasne"] and b.button("Przywróć domyślne urzędu", use_container_width=True):
            if _ok(api.reset_reminders, ok="Przywrócono domyślne przypomnienia urzędu."):
                st.session_state.pop(key, None)
                st.rerun()


def _deputies(api: Api, me: dict, users: list[dict], today: date) -> None:
    hr = me["rola"] == "KADRY"
    if not (hr or me["czy_oceniajacy"]):
        return
    with st.container(border=True):
        st.markdown("#### :material/handshake: Zastępstwa",
                    help="W czasie zastępstwa zastępca może prowadzić rozmowy i sporządzić ocenę za oceniającego.")
        rows = api.deputies()
        for d in rows:
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(f"**{name(d['zastepca'])}** zastępuje **{name(d['oceniajacy'])}** · {ui.fmt(d['od'])} – "
                        f"{ui.fmt(d['do'])} " + ui.badge("trwa" if d["aktywne"] else "nieaktywne",
                                                         "b-green" if d["aktywne"] else "b-grey"),
                        unsafe_allow_html=True)
            if c2.button("Usuń", key=f"dep_del_{d['id']}", use_container_width=True):
                if _ok(api.delete_deputy, d["id"], ok="Usunięto zastępstwo."):
                    st.rerun()
        if not rows:
            st.caption("Brak zastępstw.")
        people = [u for u in users if u["id"] != "kadry"]
        numbers = {u["id"]: n for n, u in enumerate(people, start=1)}  # API ids = position in the directory
        evaluators = [u for u in people if u["opis"].startswith("Oceniający")]
        mine = [u for u in evaluators if hr or u["nazwa"] == name(me["pracownik"])]
        c1, c2 = st.columns(2)
        ev = c1.selectbox("Oceniający", [u["id"] for u in mine], format_func=lambda i: next(u["nazwa"] for u in people if u["id"] == i),
                          key="dep_ev")
        dp = c2.selectbox("Zastępca", [u["id"] for u in people if u["id"] != ev],
                          format_func=lambda i: next(u["nazwa"] for u in people if u["id"] == i), key="dep_dp")
        c3, c4 = st.columns(2)
        od = c3.date_input("Od", today, format="DD.MM.YYYY", key="dep_od")
        do = c4.date_input("Do", today + timedelta(days=14), format="DD.MM.YYYY", key="dep_do")
        if st.button("Dodaj zastępstwo", type="primary", key="dep_add"):
            if _ok(api.add_deputy, numbers[ev], numbers[dp], od, do, ok="Dodano zastępstwo."):
                st.rerun()


def render(api: Api, me: dict, meta: dict, users: list[dict]) -> None:
    hr = me["rola"] == "KADRY"
    st.subheader(":material/settings: Ustawienia", help="Domyślny harmonogram przypomnień, asystent AI i wymagania urzędu." if hr
                 else "Twoje przypomnienia, asystent AI i zastępstwa.")
    _assistant(api, me)
    if hr:
        _visibility(api, me)
    _reminders(api, me)
    _deputies(api, me, users, to_date(meta["dzis"]))
    _rules(api, me)
