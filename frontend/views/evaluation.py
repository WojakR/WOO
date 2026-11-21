"""Screen 1 – one evaluation, entirely from the API (GET /api/evaluations/{id} and friends).

The server decides everything (contract rule 1): result, locks (`edytowalne_pola`), allowed steps
(`dozwolone_akcje`), validations. This view only shows them and sends the user's input back.
Session state is used only for UI things (selected stage, unsaved text, an assistant proposal on screen)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import (ACTION_DONE, ACTION_LABEL, DONE, EMPLOYMENT_LABEL, LEVEL_LABEL, SCALE_LABEL, SENTIMENTS,
                              SIGNAL_LABEL, STAGES, STATUS_LABEL, current_stage, name, to_date)
from frontend.views.team import open_evaluation

TEXT_FIELDS = {"uzasadnienie": ("Uzasadnienie oceny", "UZASADNIENIE"),
               "wnioski_iprz": ("Wnioski dotyczące indywidualnego programu rozwoju zawodowego", "IPRZ")}
CHECK_LABEL = {"UZASADNIENIE_WYMAGANE": "Uzasadnienie oceny", "IPRZ_WYMAGANE": "Wnioski do IPRZ",
               "BRAK_OCENY": "Oceny cząstkowe"}


# ---------------------------------------------------------------- small helpers

def _flash(kind: str, text: str) -> None:
    st.session_state.setdefault("flash", []).append((kind, text))


def _show_flash() -> None:
    for kind, text in st.session_state.pop("flash", []):
        (st.error if kind == "error" else st.success)(text)


def _call(fn, *args, ok: str | None = None, **kwargs):
    """Run an API call from a callback; errors and confirmations are shown after the rerun."""
    try:
        out = fn(*args, **kwargs)
    except ApiError as e:
        _flash("error", " ".join(e.messages))
        return None
    if ok:
        st.toast(ok)
    return out


def _sync(key: str, server_value) -> None:
    """Keep a widget in step with the server unless the user has typed something not yet saved."""
    src = f"{key}__srv"
    if key not in st.session_state or (st.session_state.get(src) != server_value
                                       and st.session_state.get(key) == st.session_state.get(src)):
        st.session_state[key] = server_value
    st.session_state[src] = server_value


def _cached(key: tuple, compute):
    cache = st.session_state.setdefault("ai_cache", {})
    if key not in cache:
        with st.spinner("Asystent przygotowuje propozycję…"):
            try:
                cache[key] = compute()
            except ApiError as e:
                return e
    return cache[key]


def _locked(text: str = "Pole zablokowane po zatwierdzeniu etapu.") -> None:
    ui.html(f'<p class="lock">🔒 {escape(text)}</p>')


def _crit_dict(api: Api, sheet: str) -> dict[str, dict]:
    key = ("criteria", sheet)
    cache = st.session_state.setdefault("dict_cache", {})
    if key not in cache:
        cache[key] = {c["kod"]: c for c in api.criteria(sheet)}
    return cache[key]


def _indicators(crit: dict | None) -> str:
    if not crit or not crit.get("wskazniki"):
        return ""
    return (f"**Na co patrzeć – {crit['nazwa']}** (wskaźniki z załącznika nr 1 do rozporządzenia PRM "
            "z 4.04.2016):\n\n" + "\n".join(f"- {w}" for w in crit["wskazniki"]))


def _action(api: Api, ev: dict, akcja: str, before=None, note: str = "") -> None:
    """Primary step of the process: shown only when the server allows it; two-step confirmation."""
    if akcja not in ev["dozwolone_akcje"]:
        return
    blocks = [w for w in ev["walidacje"] if w["waga"] == "BLAD"] if akcja == "ZATWIERDZ_OCENE" else []
    ckey = f"confirm_{ev['id']}_{akcja}"
    if st.session_state.get(ckey):
        st.warning(f"Czy na pewno: **{ACTION_LABEL[akcja].lower()}**? Po zatwierdzeniu pola tego etapu zostaną "
                   "zablokowane." + (f" {note}" if note else ""))
        a, b = st.columns(2)
        if a.button(f"✔ Tak, {ACTION_LABEL[akcja].lower()}", type="primary", key=f"{ckey}_yes",
                    use_container_width=True):
            st.session_state.pop(ckey, None)
            if before and not before():
                return
            if _call(api.action, ev["id"], akcja, ok=ACTION_DONE.get(akcja)):
                st.session_state.pop(f"sel_{ev['id']}", None)
            st.rerun()
        if b.button("Anuluj", key=f"{ckey}_no", use_container_width=True):
            st.session_state.pop(ckey, None)
            st.rerun()
        return
    if st.button(ACTION_LABEL.get(akcja, akcja), type="primary", key=f"{ckey}_btn", disabled=bool(blocks)):
        st.session_state[ckey] = True
        st.rerun()
    if blocks:
        st.caption("⚠️ Aby zatwierdzić, uzupełnij: " + ", ".join(CHECK_LABEL.get(w["kod"], w["komunikat"])
                                                                  for w in blocks) + ".")


# ---------------------------------------------------------------- header, person card

def _header(ev: dict, today: date) -> None:
    status = ev["status"]
    ui.html(f"<h3 style='margin:0'>Ocena okresowa – {escape(name(ev['oceniany']))} "
            f"{ui.badge('Arkusz ' + ev['arkusz'], 'b-blue')} "
            f"{ui.badge(STATUS_LABEL.get(status, status), 'b-green' if status == 'ZAKONCZONA' else 'b-grey')}</h3>")
    if status in ("KRYTERIA_DO_WYZNACZENIA", "KRYTERIA_DO_POTWIERDZENIA"):
        ui.deadline_bar("Termin wyznaczenia kryteriów", ev["czesc_i"]["termin_wyznaczenia_kryteriow"], today)
    elif status in ("OKRES_OCENY", "ROZMOWA_OCENIAJACA"):
        ui.deadline_bar("Termin sporządzenia oceny", ev["czesc_i"]["termin_oceny"], today)
    elif ev["czesc_ii"].get("termin_sprzeciwu"):
        ui.deadline_bar("Termin na sprzeciw", ev["czesc_ii"]["termin_sprzeciwu"], today)
    else:
        ui.deadline_bar(f"Ocena sporządzona {ui.fmt(ev['czesc_ii'].get('data_sporzadzenia'))}", None, today)


def _person(ev: dict) -> None:
    o, c1, c2 = ev["oceniany"], ev["czesc_i"], ev["czesc_ii"]
    start = c2.get("okres_od") or c1.get("data_wyznaczenia_kryteriow")
    end = c2.get("okres_do") or c1["termin_oceny"]
    prev = c2.get("poprzednia_ocena") or {}
    prev_text = "brak"
    if prev.get("wynik") and prev["wynik"] != "BRAK":
        prev_text = prev["wynik"].lower() + (f", {LEVEL_LABEL.get(prev.get('poziom'), '')}" if prev.get("poziom") else "")
        prev_text += f" ({ui.fmt(prev.get('data'))})" if prev.get("data") else ""
    initials = (o["imie"][:1] + o["nazwisko"][:1]).upper()
    rows = [("Typ zatrudnienia", EMPLOYMENT_LABEL.get(o.get("typ_zatrudnienia"), o.get("typ_zatrudnienia") or "—")),
            ("Okres oceny", f"{ui.fmt(start)} – {ui.fmt(end)}" if start else "od wyznaczenia kryteriów"),
            ("Poprzednia ocena", prev_text), ("Oceniający", name(ev["oceniajacy"]))]
    locks = ""
    if c1["potw_oceniany"].get("at"):
        locks = (f"<p class='lock'>🔒 Kryteria i termin zatwierdził(a) {escape(name(c1['potw_oceniajacy'].get('osoba')))} "
                 f"{ui.fmt(c1['potw_oceniajacy'].get('at'))}, oceniany potwierdził(a) {ui.fmt(c1['potw_oceniany']['at'])}.</p>")
    ui.html(f'<div class="card person-card"><div class="avatar">{escape(initials)}</div><div>'
            f'<h4>{escape(name(o))}</h4><p class="lock">{escape(o.get("stanowisko") or "")} · '
            f'{escape(o.get("komorka") or "")}</p>{ui.kv(rows)}{locks}</div></div>')


# ---------------------------------------------------------------- conversation tips (both meetings)

def _prep(api: Api, ev: dict, kind: str) -> None:
    prep = _cached(("prep", ev["id"], kind, ev["updated_at"]), lambda: api.conversation_prep(ev["id"], kind))
    if isinstance(prep, ApiError):
        st.caption(prep.komunikat)
        return
    ui.html(f"<p><b>Cel rozmowy:</b> {escape(prep['cel_rozmowy'])}</p>"
            f"<p>{ui.source_note('AI' if prep['zrodlo_tekstow'] == 'AI' else 'SZABLON')}</p>")
    if prep.get("plan_minuty"):
        total = sum(m for _, m in prep["plan_minuty"])
        ui.html(f"<p><b>Plan ({total} min):</b> " + " → ".join(
            f"{escape(p)} <span class='lock'>{m}′</span>" for p, m in prep["plan_minuty"]) + "</p>")
    if prep.get("cele"):
        ui.html("<b>Cele z rozmowy rozpoczynającej:</b>" + ui.ul(prep["cele"]))
    for c in prep["kryteria"]:
        with st.expander(f"{c['nazwa']}{'' if c.get('obowiazkowe', True) else ' (dodatkowe)'} · "
                         f"+{c['plus']} / −{c['minus']}"):
            if c.get("przyklady"):
                ui.html("<b>Obserwacje:</b>" + ui.ul(f"{ui.fmt(n['data'])}: {n['tresc']}" for n in c["przyklady"]))
            if c.get("luki"):
                ui.html("<b>Brak obserwacji – zapytaj o:</b>" + ui.ul(c["luki"]))
            if c.get("pytania"):
                ui.html("<b>Proponowane pytania:</b>" + ui.ul(c["pytania"]))
    cols = st.columns(3)
    for col, title, items in zip(cols, ("Mocne strony", "Trudne tematy", "Działania rozwojowe"),
                                 (prep.get("mocne_strony"), prep.get("trudne_tematy"), prep.get("propozycje_rozwoju"))):
        with col:
            ui.card(title, ui.ul(items or []) or "<p class='lock'>brak</p>")


def _invite(ev: dict, today: date, stage: int, title: str, minutes: int) -> None:
    """Calendar file only – sending invitations needs the backend's notifications (not in the API yet)."""
    from frontend.ics import ics_invite

    c1, c2 = st.columns(2)
    d = c1.date_input("Data rozmowy", today + timedelta(days=3), key=f"inv_d_{ev['id']}_{stage}", format="DD.MM.YYYY")
    t = c2.time_input("Godzina", time(10, 0), key=f"inv_t_{ev['id']}_{stage}", step=900)
    when = datetime.combine(d, t)
    st.download_button("📅 Pobierz zaproszenie do kalendarza (.ics – Outlook, Thunderbird)",
                       ics_invite(f"{title} – {name(ev['oceniany'])}", when, minutes,
                                  f"{title} w ramach oceny okresowej (arkusz {ev['arkusz']})."),
                       file_name=f"zaproszenie-{ev['id']}-{stage}.ics", mime="text/calendar",
                       key=f"inv_ics_{ev['id']}_{stage}")
    st.caption("Wysłanie zaproszenia do pracownika w aplikacji wymaga obsługi powiadomień w backendzie – "
               "na razie plik do kalendarza.")


# ---------------------------------------------------------------- stage 1: criteria

def _stage_criteria(api: Api, ev: dict, ai: bool, today: date) -> None:
    crit = _crit_dict(api, ev["arkusz"])
    editable = "kryteria_dodatkowe" in ev["edytowalne_pola"]
    st.markdown("#### Arkusz oceny")
    ui.html(f"<p>{ui.badge('Arkusz ' + ev['arkusz'], 'b-blue')} <span class='lock'>dobrany przez system na podstawie "
            f"stanowiska: {escape(ev['oceniany'].get('stanowisko') or '')}</span></p>")

    st.markdown("#### Kryteria oceny")
    with st.container(border=True):
        st.markdown("**Kryteria obowiązkowe** (stałe dla arkusza)")
        for k in [k for k in ev["kryteria"] if k["typ"] == "OBOWIAZKOWE"]:
            st.markdown(f"- {k['nazwa']}", help=_indicators(crit.get(k["criterion_kod"])) or None)
    chosen = [k["criterion_kod"] for k in ev["kryteria"] if k["typ"] == "DODATKOWE"]
    optional = [c["kod"] for c in crit.values() if c.get("typ_dla_arkusza") == "DODATKOWE"]
    st.markdown("**Kryteria dodatkowe** <span class='lock'>– najwyżej 3, bez powtórzeń; puste pole = brak</span>",
                unsafe_allow_html=True)
    slots = [chosen[i] if i < len(chosen) else None for i in range(3)]

    def save_slot(i: int) -> None:
        new = list(slots)
        new[i] = st.session_state[f"add_{ev['id']}_{i}"]
        _call(api.additional, ev["id"], [c for c in new if c])

    for i in range(3):
        key = f"add_{ev['id']}_{i}"
        _sync(key, slots[i])
        opts = [None] + [c for c in optional if c == slots[i] or c not in slots]
        st.selectbox(f"Kryterium dodatkowe {i + 1}", opts, key=key, disabled=not editable, placeholder="— brak —",
                     format_func=lambda c: "— brak —" if c is None else crit[c]["nazwa"],
                     on_change=save_slot, args=(i,),
                     help=_indicators(crit.get(slots[i])) or None)
    if not editable:
        _locked("Kryteria można zmieniać do zatwierdzenia ich przez oceniającego.")

    st.markdown("#### Termin sporządzenia oceny")
    st.markdown(f"**{ui.fmt(ev['czesc_i']['termin_oceny'])}** <span class='lock'>wyliczony przez system "
                "(24 miesiące od początku cyklu, z pominięciem dni wolnych)</span>", unsafe_allow_html=True)
    if "termin_oceny" in ev["edytowalne_pola"]:
        with st.popover("📆 Zmień termin oceny"):
            new = st.date_input("Nowy termin", to_date(ev["czesc_i"]["termin_oceny"]), key=f"ovr_{ev['id']}",
                                format="DD.MM.YYYY", min_value=today)
            if st.button("Zapisz termin", type="primary", key=f"ovr_save_{ev['id']}"):
                if _call(api.patch, ev, termin_oceny=new, ok=f"Nowy termin oceny: {ui.fmt(new)}"):
                    st.rerun()
                st.rerun()

    if ev["jako_oceniajacy"] and current_stage(ev) == 1:
        with st.expander("📅 Zaproszenie na rozmowę rozpoczynającą"):
            _invite(ev, today, 1, "Rozmowa rozpoczynająca ocenę okresową", 45)
        if ai:
            with st.expander("🗣️ Wskazówki do rozmowy rozpoczynającej"):
                st.caption("Podpowiedź przed rozmową: cel, plan z czasem i pytania do każdego kryterium "
                           "(§ 5 rozporządzenia).")
                _prep(api, ev, "ROZPOCZYNAJACA")
    if ev["status"] == "KRYTERIA_DO_POTWIERDZENIA":
        st.info("⏳ Kryteria przekazane ocenianemu – czeka na potwierdzenie rozmowy i zapoznania się z kryteriami.")
    st.divider()
    _action(api, ev, "ZATWIERDZ_KRYTERIA")


# ---------------------------------------------------------------- stage 2: observation

def _note_form(api: Api, ev: dict, today: date, key: str) -> None:
    with st.form(key, clear_on_submit=True, border=False):
        text = st.text_area("Obserwacja", height=80, placeholder="Co się wydarzyło? Konkretne zachowanie i efekt.")
        c1, c2 = st.columns(2, vertical_alignment="bottom")
        on = c1.date_input("Data", today, max_value=today, format="DD.MM.YYYY")
        submitted = c2.form_submit_button("Dodaj notatkę", type="primary", use_container_width=True)
    if submitted:
        if not text.strip():
            st.error("Wpisz treść obserwacji, a potem kliknij „Dodaj notatkę”.")
        elif _call(api.add_note, ev["id"], on, text.strip(), ok="Notatka zapisana."):
            st.rerun()


def _note_row(api: Api, ev: dict, n: dict, crit: dict, can_edit: bool, ai: bool) -> None:
    if n.get("criterion_kod"):
        cls = {"POZYTYWNY": "b-green", "NEGATYWNY": "b-red"}.get(n.get("wydzwiek"), "b-grey")
        tag = ui.badge(crit.get(n["criterion_kod"], {}).get("nazwa", n["criterion_kod"]), "b-blue") + " " + \
            ui.badge(SENTIMENTS.get(n.get("wydzwiek"), "bez wydźwięku"), cls)
    elif n.get("status_klasyfikacji") == "W_TOKU":
        tag = ui.badge("asystent analizuje…", "b-violet")
    else:
        tag = ui.badge("do przypisania", "b-amber")
    ui.html(f'<div class="note"><span class="d">{ui.fmt(n["data"])} · {escape(name(n.get("autor")))}</span> {tag}<br>'
            f'{escape(n["tresc"])}</div>')
    if not can_edit:
        return
    sug = n.get("sugestie_ai") or []
    if ai and not n.get("criterion_kod") and sug:
        s0 = sug[0]
        crit_name = s0.get("nazwa") or crit.get(s0["criterion_kod"], {}).get("nazwa", s0["criterion_kod"])
        source = ("model AI" if n.get("zrodlo_sugestii") == "AI"
                  else "dopasowanie słów kluczowych, bez AI")
        if s0.get("wydzwiek"):
            cols = st.columns([3, 1], vertical_alignment="center")
            cols[0].caption(f"✨ Propozycja ({source}): **{crit_name}**, {SENTIMENTS[s0['wydzwiek']]} "
                            f"({int(s0['pewnosc'] * 100)}%)")
            if cols[1].button("Przyjmij", key=f"acc_{n['id']}", use_container_width=True):
                _call(api.patch_note, n["id"], zaakceptuj_sugestie=True, ok="Przypisano notatkę.")
                st.rerun()
        else:
            # rule-based proposals name the criterion only – the evaluator picks the sentiment with one click
            st.caption(f"✨ Propozycja ({source}): **{crit_name}**. Wybierz wydźwięk, aby przyjąć:")
            cols = st.columns(3)
            for col, (val, label) in zip(cols, (("POZYTYWNY", "👍 pozytywna"), ("NEUTRALNY", "neutralna"),
                                               ("NEGATYWNY", "👎 negatywna"))):
                if col.button(f"Przyjmij – {label}", key=f"acc_{n['id']}_{val}", use_container_width=True):
                    _call(api.patch_note, n["id"], zaakceptuj_sugestie=True, wydzwiek=val, ok="Przypisano notatkę.")
                    st.rerun()
    with st.popover("Przypisz / zmień"):
        codes = [k["criterion_kod"] for k in ev["kryteria"]]
        c = st.selectbox("Kryterium", codes, key=f"mc_{n['id']}",
                         index=codes.index(n["criterion_kod"]) if n.get("criterion_kod") in codes else 0,
                         format_func=lambda x: crit.get(x, {}).get("nazwa", x))
        s = st.radio("Wydźwięk", list(SENTIMENTS), format_func=SENTIMENTS.get, horizontal=True, key=f"ms_{n['id']}")
        a, b = st.columns(2)
        if a.button("Zapisz", key=f"msave_{n['id']}", type="primary", use_container_width=True):
            _call(api.patch_note, n["id"], criterion_kod=c, wydzwiek=s, ok="Zapisano.")
            st.rerun()
        if b.button("Usuń notatkę", key=f"mdel_{n['id']}", use_container_width=True):
            _call(api.delete_note, n["id"], ok="Usunięto notatkę.")
            st.rerun()


def _stage_observation(api: Api, ev: dict, me: dict, ai: bool, today: date) -> None:
    crit = _crit_dict(api, ev["arkusz"])
    work = ev["jako_oceniajacy"] or me["rola"] == "KADRY"
    tab_notes, tab_crit, tab_period = st.tabs(["📝 Notatnik", "📊 Wg kryteriów", "📆 Zmiana okresu"])
    with tab_notes:
        if not work:
            st.caption("Notatki przełożonego są materiałem roboczym – widzi je oceniający i kadry.")
        else:
            st.caption("Zapisuj obserwacje przez cały okres oceny. Każdą notatkę przypisujemy do kryterium, bo arkusz "
                       "ocenia się kryterium po kryterium: przy ocenie cząstkowej widać zebrane przykłady, a szkic "
                       "uzasadnienia cytuje właściwe notatki. Asystent proponuje kryterium – decydujesz Ty.")
            if ev["jako_oceniajacy"] and ev["status"] not in ("ZAKONCZONA", "OCENA_DO_ZAPOZNANIA"):
                _note_form(api, ev, today, f"nf_{ev['id']}")
            notes = sorted(api.notes(ev["id"]), key=lambda n: n["data"], reverse=True)
            if not notes:
                st.caption("Brak notatek.")
            for n in notes:
                _note_row(api, ev, n, crit, ev["jako_oceniajacy"], ai)
    with tab_crit:
        if work:
            evid = api.evidence(ev["id"])
            for e in evid["kryteria"]:
                bar = "🟩" * e["plus"] + "⬜" * e["neutralne"] + "🟥" * e["minus"]
                st.markdown(f"**{e['nazwa']}** · +{e['plus']} / −{e['minus']} {bar}")
                if e.get("wskazniki_bez_obserwacji"):
                    st.caption("Brak obserwacji: " + "; ".join(e["wskazniki_bez_obserwacji"]))
            if evid["notatki_do_przypisania"]:
                st.warning(f"Notatki bez kryterium: {evid['notatki_do_przypisania']} – nie są brane pod uwagę.")
    with tab_period:
        c1, c2 = ev["czesc_i"], ev["czesc_ii"]
        start = to_date(c2.get("okres_od") or c1.get("data_wyznaczenia_kryteriow")) or today
        end = to_date(c2.get("okres_do") or c1["termin_oceny"])
        st.markdown(f"Okres oceny: **{ui.fmt(start)} – {ui.fmt(end)}**")
        if "okres_od" in ev["edytowalne_pola"]:
            a, b = st.columns(2)
            new_from = a.date_input("Okres oceny od", start, format="DD.MM.YYYY", key=f"per_f_{ev['id']}")
            new_to = b.date_input("Okres oceny do", end, format="DD.MM.YYYY", key=f"per_t_{ev['id']}")
            if st.button("Zapisz okres oceny", type="primary", key=f"per_save_{ev['id']}"):
                if new_to < new_from:
                    st.error("Data „do” jest wcześniejsza niż data „od”.")
                else:
                    _call(api.patch, ev, okres_od=new_from, okres_do=new_to,
                          ok=f"Okres oceny: {ui.fmt(new_from)} – {ui.fmt(new_to)}")
                    st.rerun()
        else:
            _locked("Okres oceny można zmienić od potwierdzenia kryteriów do zapisania rozmowy oceniającej.")
    if ev["status"] == "OKRES_OCENY" and ev["jako_oceniajacy"]:
        st.divider()
        if st.button("Przejdź do przygotowania rozmowy oceniającej →", type="primary", key=f"to3_{ev['id']}"):
            st.session_state[f"sel_{ev['id']}"] = 3
            st.rerun()


# ---------------------------------------------------------------- stage 3: review meeting

def _stage_review(api: Api, ev: dict, ai: bool, today: date) -> None:
    if ev["status"] != "OKRES_OCENY":
        st.markdown(f"Rozmowa oceniająca odbyła się **{ui.fmt(ev['czesc_ii'].get('data_rozmowy_oceniajacej'))}**.")
        _locked()
        return
    if ev["jako_oceniajacy"]:
        with st.expander("📅 Zaproszenie na rozmowę oceniającą"):
            _invite(ev, today, 3, "Rozmowa oceniająca", 60)
        st.markdown("#### Przygotowanie do rozmowy")
        if ai:
            _prep(api, ev, "OCENIAJACA")
        else:
            st.caption("Asystent jest wyłączony – wskazówki do rozmowy są ukryte.")
        st.divider()
    _action(api, ev, "ROZPOCZNIJ_ROZMOWE",
            note=f"Jako datę rozmowy system zapisze dzisiejszą datę ({ui.fmt(today)}).")


# ---------------------------------------------------------------- stage 4: the sheet

def _basis_hint(ev: dict, notes_by_id: dict, evid: dict | None) -> str:
    lines = ["Propozycja – na czym oprzeć uzasadnienie:"]
    by_code = {e["criterion_kod"]: e for e in (evid or {}).get("kryteria", [])}
    for k in ev["kryteria"]:
        e = by_code.get(k["criterion_kod"])
        pts = k.get("punkty")
        if pts is None and not e:
            continue
        line = f"• {k['nazwa']} – " + (f"{pts} pkt ({SCALE_LABEL.get(pts, '')})" if pts else "jeszcze nie oceniono")
        if e:
            line += f"; notatki +{e['plus']}/−{e['minus']}"
            ids = [i for i in e["notatki_ids"] if i in notes_by_id]
            if ids:
                n = notes_by_id[ids[0]]
                text = n["tresc"] if len(n["tresc"]) <= 90 else n["tresc"][:87] + "…"
                line += f" – np. {ui.fmt(n['data'])}: „{text}”"
        lines.append(line)
    lines.append("Opisz konkretne zachowania i ich skutki w okresie oceny, a nie cechy osoby.")
    return "\n".join(lines)


def _iprz_hint(ev: dict) -> str:
    weak = [k["nazwa"] for k in ev["kryteria"] if k.get("punkty") is not None and k["punkty"] <= 3]
    strong = [k["nazwa"] for k in ev["kryteria"] if k.get("punkty") is not None and k["punkty"] >= 7]
    lines = ["Propozycja – co ująć we wnioskach rozwojowych:",
             "• Obszary do rozwoju: " + (", ".join(weak) if weak else "kryteria z najniższą oceną")]
    if strong:
        lines.append("• Mocne strony do wykorzystania: " + ", ".join(strong))
    lines.append("• Konkretne działania i termin: szkolenie, mentoring, nowe zadanie, udział w projekcie.")
    return "\n".join(lines)


def _result_box(c2: dict, scored: int, total: int) -> None:
    if c2.get("srednia") is None:
        ui.html(f'<div class="result pending">Oceniono {scored} z {total} kryteriów – średnia i ocena pojawią się po '
                'uzupełnieniu wszystkich.</div>')
        return
    cls = "pos" if c2["wynik"] == "POZYTYWNA" else "neg"
    avg = f"{c2['srednia']:.2f}".replace(".", ",")
    ui.html(f'<div class="result {cls}">Średnia <b>{avg}</b> · poziom <b>{escape(LEVEL_LABEL.get(c2["poziom"], ""))}'
            f'</b> · ocena <b>{c2["wynik"]}</b></div>')


def pdf_button(api: Api, ev: dict, key: str = "pdf") -> None:
    """One button: the server makes the PDF only when it is clicked (no waiting while the page loads)."""
    eid = ev["id"]
    surname = ev["oceniany"]["nazwisko"].lower()
    st.download_button("⬇️ Pobierz PDF arkusza", lambda: api.pdf(eid)[0], file_name=f"arkusz-{ev['arkusz']}-{surname}.pdf",
                       mime="application/pdf", key=f"{key}dl_{eid}", on_click="ignore",
                       help="Arkusz zgodny ze wzorem z rozporządzenia, z serwera")


def _stage_sheet(api: Api, ev: dict, me: dict, ai: bool, meta: dict) -> None:
    eid = ev["id"]
    crit = _crit_dict(api, ev["arkusz"])
    can_score = "punkty" in ev["edytowalne_pola"]
    work = ev["jako_oceniajacy"] or me["rola"] == "KADRY"
    evid = api.evidence(eid) if work else None
    notes_by_id = {n["id"]: n for n in api.notes(eid)} if work else {}
    by_code = {e["criterion_kod"]: e for e in (evid or {}).get("kryteria", [])}
    scale = meta.get("skala_punktow", [1, 3, 5, 7, 9])

    def set_score(code: str, key: str) -> None:
        _call(api.scores, eid, {code: st.session_state[key]})

    def accept(code: str, key: str, pts: int) -> None:
        st.session_state[key] = pts
        _call(api.scores, eid, {code: pts}, ok="Przyjęto sugerowaną ocenę.")

    bands = "\n".join(f"- {LEVEL_LABEL[k]}: średnia {lo:g}–{hi:g} pkt" for k, (lo, hi) in meta["progi_poziomow"].items())
    st.markdown("#### Oceny cząstkowe", help=(
        "**Jak ocenić (§ 11 rozporządzenia PRM z 4.04.2016):**\n\n"
        + "\n".join(f"- **{p} pkt** – {SCALE_LABEL.get(p, '')}" for p in scale)
        + "\n\nŚrednia wyznacza poziom:\n" + bands
        + "\n\nOcena jest **negatywna**, gdy poziom jest poniżej oczekiwań albo choć jedno kryterium ma 1 pkt. "
          "Znak **?** przy kryterium pokazuje, czego ono dotyczy."))
    ui.html("<p class='lock'>" + " · ".join(f"<b>{p}</b> {escape(SCALE_LABEL.get(p, ''))}" for p in scale) + "</p>")
    box = st.container(key="scores")
    for k in ev["kryteria"]:
        code = k["criterion_kod"]
        key = f"sc_{eid}_{code}"
        _sync(key, k.get("punkty"))
        e = by_code.get(code)
        counts = k.get("liczba_dowodow") or {}
        c1, c2 = box.columns([1.4, 1.6], vertical_alignment="center")
        c1.markdown(f"**{k['nazwa']}**{'' if k['typ'] == 'OBOWIAZKOWE' else ' · dodatkowe'}<br>"
                    f"<span class='lock'>notatki: +{counts.get('POZYTYWNY', 0)} / −{counts.get('NEGATYWNY', 0)}</span>",
                    unsafe_allow_html=True, help=_indicators(crit.get(code)) or None)
        with c2:
            val = st.segmented_control(k["nazwa"], scale, key=key, format_func=str, label_visibility="collapsed",
                                       disabled=not can_score, on_change=set_score, args=(code, key))
            st.caption(SCALE_LABEL.get(val, "") if val is not None else "nie oceniono")
        sug = k.get("sugerowane_punkty")
        if work and sug is not None:
            s1, s2 = box.columns([3, 1], vertical_alignment="center")
            why = (e or {}).get("uzasadnienie_sugestii") or ""
            s1.caption(f"✨ Sugerowane: **{sug} pkt** · {why}" + (" · zgodne z oceną" if val == sug else ""))
            if can_score and val != sug:
                s2.button("Przyjmij", key=f"acc_sc_{eid}_{code}", on_click=accept, args=(code, key, sug),
                          help=f"Ustaw ocenę {sug} pkt dla kryterium {k['nazwa']}")
        ids = [i for i in (e or {}).get("notatki_ids", []) if i in notes_by_id]
        if ids:
            with box.expander(f"Pokaż notatki ({len(ids)})"):
                for i in ids[:5]:
                    n = notes_by_id[i]
                    ui.html(f'<div class="note"><span class="d">{ui.fmt(n["data"])}</span> '
                            f'{ui.badge(SENTIMENTS.get(n.get("wydzwiek"), "—"), "b-grey")}<br>{escape(n["tresc"])}</div>')
    scored = sum(k.get("punkty") is not None for k in ev["kryteria"])
    _result_box(ev["czesc_ii"], scored, len(ev["kryteria"]))
    st.caption("Ocena jest negatywna także wtedy, gdy którekolwiek kryterium ma 1 punkt (§ 11 rozporządzenia).")

    # ---- texts + assistant drafts (proposal: Wstaw / Edytuj / Odrzuć)
    blocks = {w["pole"] for w in ev["walidacje"] if w["waga"] == "BLAD"}
    drafts_on = ai and ev["jako_oceniajacy"] and meta.get("funkcje_ai", {}).get("szkic_uzasadnienia", True)
    hints = {"uzasadnienie": _basis_hint(ev, notes_by_id, evid), "wnioski_iprz": _iprz_hint(ev)}

    def request_draft(kind: str, dkey: str) -> None:
        out = _call(api.draft, eid, kind)
        if out:
            st.session_state[dkey] = out

    for field, (title, kind) in TEXT_FIELDS.items():
        tkey = f"tx_{eid}_{field}"
        dkey = f"draft_{eid}_{field}"
        _sync(tkey, ev["czesc_ii"].get(field) or "")
        editable = field in ev["edytowalne_pola"]
        required = field in blocks or field == "wnioski_iprz" or ev["czesc_ii"].get("wynik") == "NEGATYWNA"
        h, btn = st.columns([3, 1], vertical_alignment="bottom")
        h.markdown(f"#### {title} " + ("*" if required else "<span class='lock'>(opcjonalne przy ocenie pozytywnej)</span>"),
                   unsafe_allow_html=True)
        if editable and drafts_on:
            btn.button("✨ Szkic od asystenta", key=f"dr_{tkey}", use_container_width=True,
                       on_click=request_draft, args=(kind, dkey))
        # a negative result needs a justification: offer the assistant's draft straight away (once)
        if (field == "uzasadnienie" and editable and drafts_on and ev["czesc_ii"].get("wynik") == "NEGATYWNA"
                and not st.session_state[tkey].strip() and not st.session_state.get(f"auto_{eid}")):
            st.session_state[f"auto_{eid}"] = True
            request_draft(kind, dkey)
        d = st.session_state.get(dkey)
        if d and editable:
            with st.container(border=True):
                src = "Wygenerowane przez model lokalny" if d["zrodlo"] == "AI" else "Szablon z danych (model niedostępny)"
                based = f" · na podstawie {len(d.get('oparte_na_notatkach') or [])} notatek" if d.get("oparte_na_notatkach") else ""
                ui.html(f"{ui.badge('✨ Propozycja asystenta', 'b-violet')} <span class='lock'>{src}{based} · nic nie "
                        f"zostanie zapisane bez Twojej decyzji.</span>")
                st.markdown(d["tekst"])
                a, b, c = st.columns(3)

                def use(save: bool, field=field, tkey=tkey, dkey=dkey) -> None:
                    st.session_state[tkey] = st.session_state[dkey]["tekst"]
                    st.session_state.pop(dkey, None)
                    if save:
                        fresh = api.evaluation(eid)
                        _call(api.patch, fresh, **{field: st.session_state[tkey]}, ok="Wstawiono i zapisano.")

                a.button("Wstaw", key=f"use_{dkey}", type="primary", use_container_width=True, on_click=use, args=(True,))
                b.button("✏️ Edytuj", key=f"edit_{dkey}", use_container_width=True, on_click=use, args=(False,))
                c.button("✖ Odrzuć", key=f"rej_{dkey}", use_container_width=True,
                         on_click=lambda dkey=dkey: st.session_state.pop(dkey, None))
        st.text_area(title, key=tkey, height=170, disabled=not editable, label_visibility="collapsed",
                     placeholder=hints[field] if editable else "")
        if field in blocks and editable and not st.session_state[tkey].strip():
            st.error(next(w["komunikat"] for w in ev["walidacje"] if w["pole"] == field))
        if not editable and ev["czesc_ii"].get("podpis_oceniajacego", {}).get("at"):
            _locked("Zablokowane po zatwierdzeniu oceny.")

    def dirty() -> dict:
        return {f: st.session_state[f"tx_{eid}_{f}"] for f in TEXT_FIELDS
                if f in ev["edytowalne_pola"] and st.session_state[f"tx_{eid}_{f}"] != (ev["czesc_ii"].get(f) or "")}

    def save_texts() -> bool:
        changes = dirty()
        if not changes:
            return True
        return _call(api.patch, api.evaluation(eid), **changes) is not None

    st.markdown("#### Część III – wniosek o kolejny stopień służbowy")
    c3 = ev.get("czesc_iii")
    if ev["oceniany"].get("typ_zatrudnienia") != "URZEDNIK":
        st.caption("Nie dotyczy – oceniany jest pracownikiem służby cywilnej (część III dotyczy urzędników).")
    elif c3:
        st.markdown(f"Wnioskowany stopień: **{c3.get('wnioskowany_stopien') or '—'}**"
                    + (" · stopień obligatoryjny" if c3.get("stopien_obligatoryjny") else ""))
    else:
        st.caption(f"Wniosek o stopień: {ev['czesc_ii'].get('wniosek_o_stopien', 'NIE_DOTYCZY').replace('_', ' ').lower()}.")

    st.divider()
    a, b = st.columns([1, 1.6], vertical_alignment="top")
    if any(f in ev["edytowalne_pola"] for f in TEXT_FIELDS):
        if a.button("💾 Zapisz roboczo", key=f"save_{eid}", use_container_width=True):
            if not dirty():
                st.toast("Brak zmian do zapisania.")
            elif save_texts():
                st.toast("Zapisano roboczo.")
                st.rerun()
    with b:
        _action(api, ev, "ZATWIERDZ_OCENE", before=save_texts)
    pdf_button(api, ev)


# ---------------------------------------------------------------- stage 5

def _stage_ack(api: Api, ev: dict) -> None:
    c2 = ev["czesc_ii"]
    scored = sum(k.get("punkty") is not None for k in ev["kryteria"])
    _result_box(c2, scored, len(ev["kryteria"]))
    if ev["status"] == "OCENA_DO_ZAPOZNANIA":
        st.info(f"⏳ Ocena sporządzona {ui.fmt(c2.get('data_sporzadzenia'))} i przekazana ocenianemu – czeka na "
                "potwierdzenie zapoznania się z oceną.")
    elif c2.get("zapoznanie", {}).get("at"):
        st.success(f"✔ Oceniany zapoznał się z oceną {ui.fmt(c2['zapoznanie']['at'])}"
                   + (" (fikcja zapoznania)." if c2.get("fikcja_zapoznania") else "."))
        if c2.get("termin_sprzeciwu"):
            st.markdown(f"Termin na sprzeciw do dyrektora generalnego: **{ui.fmt(c2['termin_sprzeciwu'])}**.")
    for akcja in ("FIKCJA_ZAPOZNANIA", "POTWIERDZ_ZAPOZNANIE"):
        _action(api, ev, akcja)
    objection_panel(api, ev)
    pdf_button(api, ev)


def _inline_action(api: Api, eid: int, akcja: str, **body) -> None:
    """Run a step and show the server's answer right here (not at the top of the page)."""
    try:
        api.action(eid, akcja, **body)
    except ApiError as e:
        ui.api_error(e)
        return
    st.toast(ACTION_DONE.get(akcja, "Zapisano."))
    st.rerun()


def objection_panel(api: Api, ev: dict) -> None:
    """Objection (art. 83): its state from the server; filing (evaluated person) and the decision (director general /
    the person set in the office settings) only when the server allows it (`dozwolone_akcje`)."""
    o = ev.get("sprzeciw")
    eid = ev["id"]
    if o:
        with st.container(border=True):
            st.markdown("**⚖️ Sprzeciw od oceny**")
            ui.html(ui.kv([("Złożony", ui.fmt(o["zlozony"])), ("Termin rozstrzygnięcia", ui.fmt(o["termin_rozpatrzenia"])),
                           ("Rozstrzygnięcie", {"UWZGLEDNIONY": "uwzględniony", "NIEUWZGLEDNIONY": "nieuwzględniony"}
                            .get(o.get("decyzja"), "czeka na decyzję dyrektora generalnego"))]))
            ui.html(f"<p><b>Treść:</b> {escape(o['tresc'])}</p>")
            if o.get("uzasadnienie_decyzji"):
                ui.html(f"<p><b>Uzasadnienie decyzji:</b> {escape(o['uzasadnienie_decyzji'])}</p>")
            if o.get("termin_odwolania_do_sadu"):
                st.caption(f"Odwołanie do sądu pracy możliwe do {ui.fmt(o['termin_odwolania_do_sadu'])} (art. 83 ust. 5).")
    if "ZLOZ_SPRZECIW" in ev["dozwolone_akcje"]:
        with st.container(border=True):
            st.markdown(f"**⚖️ Sprzeciw od oceny** <span class='lock'>– możesz złożyć do "
                        f"{ui.fmt(ev['czesc_ii'].get('termin_sprzeciwu'))}, rozstrzyga dyrektor generalny</span>",
                        unsafe_allow_html=True)
            text = st.text_area("Treść sprzeciwu", key=f"obj_text_{eid}",
                                placeholder="Napisz, z czym się nie zgadzasz i dlaczego.")
            if st.button("Złóż sprzeciw", type="primary", key=f"obj_file_{eid}"):
                if not text.strip():
                    st.error("Wpisz treść sprzeciwu, a potem kliknij „Złóż sprzeciw”.")
                else:
                    _inline_action(api, eid, "ZLOZ_SPRZECIW", komentarz=text.strip())
    if "ROZPATRZ_SPRZECIW" in ev["dozwolone_akcje"]:
        with st.container(border=True):
            st.markdown("**⚖️ Rozstrzygnięcie sprzeciwu**")
            reason = st.text_area("Uzasadnienie rozstrzygnięcia", key=f"obj_dec_{eid}")
            a, b = st.columns(2)
            for col, upheld, label in ((a, True, "Uwzględnij sprzeciw"), (b, False, "Nie uwzględniaj")):
                if col.button(label, key=f"obj_{upheld}_{eid}", type="primary" if upheld else "secondary",
                              use_container_width=True):
                    _inline_action(api, eid, "ROZPATRZ_SPRZECIW", komentarz=reason.strip() or None, uwzglednij=upheld)
            st.caption("Uwzględniony sprzeciw: oceniający sporządza ocenę ponownie. Nieuwzględniony: oceniany może "
                       "odwołać się do sądu pracy.")


# ---------------------------------------------------------------- side panel

def _progress(ev: dict) -> None:
    cur = current_stage(ev)
    done = cur == DONE
    with st.container(border=True):
        st.markdown("**🧭 Postęp**" + (" · proces zakończony" if done else f" · krok {cur} z {len(STAGES)}"))
        st.progress(min(cur - 1, len(STAGES)) / len(STAGES) if not done else 1.0)
        st.caption(STATUS_LABEL.get(ev["status"], ev["status"]))
        if ev["status"] == "ROZMOWA_OCENIAJACA" and ev["jako_oceniajacy"]:
            st.markdown("**Do uzupełnienia przed zatwierdzeniem**")
            blocks = [w for w in ev["walidacje"] if w["waga"] == "BLAD"]
            missing = sum(k.get("punkty") is None for k in ev["kryteria"])
            items = ([f"🔴 Oceny cząstkowe: brakuje {missing}"] if missing else []) + \
                [f"🔴 {CHECK_LABEL.get(w['kod'], w['komunikat'])}" for w in blocks if w["kod"] != "BRAK_OCENY"]
            for line in items or ["✅ Wszystko gotowe do zatwierdzenia."]:
                st.markdown(line)
        for w in [w for w in ev["walidacje"] if w["waga"] == "OSTRZEZENIE"]:
            st.caption(f"⚠️ {w['komunikat']}")


TIMELINE_STATE = {"SPELNIONY": ("✅", "spełniony"), "AKTUALNY": ("🕒", "bieżący"), "PO_TERMINIE": ("🔴", "po terminie"),
                  "NASTEPNY_OKRES": ("⏭️", "następny okres")}


def _timeline(api: Api, ev: dict) -> None:
    """Every deadline of the evaluation as computed by the server, and the reminder plan of the current stage."""
    with st.container(border=True):
        st.markdown("**🗓️ Terminy oceny**")
        for t in ev.get("terminy") or []:
            icon, label = TIMELINE_STATE.get(t["stan"], ("•", t["stan"]))
            when = ui.fmt(t["data"]) if t.get("data") else "niezwłocznie"
            done = f" · spełniony {ui.fmt(t['spelniony_at'])}" if t.get("spelniony_at") else ""
            st.markdown(f"{icon} **{t['nazwa']}** – {when}  \n<span class='lock'>{label}{done} · {escape(t['podstawa'])}"
                        f"</span>", unsafe_allow_html=True)
        if ev["jako_oceniajacy"]:
            with st.expander("Plan przypomnień"):
                try:
                    plan = api.reminder_plan(ev["id"])
                except ApiError as e:
                    st.caption(e.komunikat)
                    plan = []
                for r in plan[:12]:
                    st.markdown(f"{'✔' if r['minelo'] else '○'} {ui.fmt(r['kiedy'])} – {name(r['do_kogo'])}: "
                                f"{r['tresc']}")
                if not plan:
                    st.caption("Brak przypomnień na tym etapie.")


def _summary(ev: dict) -> None:
    c2 = ev["czesc_ii"]
    with st.container(border=True):
        st.markdown("**Ocena w skrócie**")
        if c2.get("wynik"):
            cls = "pos" if c2["wynik"] == "POZYTYWNA" else "neg"
            avg = f"{c2['srednia']:.2f}".replace(".", ",")
            ui.html(f'<div class="result {cls}"><b>{c2["wynik"]}</b>'
                    f'{"" if c2.get("data_sporzadzenia") else " (wstępnie)"}<br>średnia {avg} · '
                    f'{escape(LEVEL_LABEL.get(c2["poziom"], ""))}</div>')
        else:
            ui.html('<div class="result pending">w trakcie</div>')
        add = sum(k["typ"] == "DODATKOWE" for k in ev["kryteria"])
        ui.html(ui.kv([("Arkusz", f"{ev['arkusz']} · {len(ev['kryteria']) - add} obowiązkowych + {add} dodatkowe"),
                       ("Termin oceny", ui.fmt(ev["czesc_i"]["termin_oceny"])),
                       ("Oceniający", name(ev["oceniajacy"]))]))


def _hr_partner(api: Api, ev: dict) -> None:
    report = _cached(("hr", ev["id"], ev["updated_at"]), lambda: api.hr_partner(ev["id"]))
    with st.container(border=True):
        if isinstance(report, ApiError):
            st.markdown("**🤝 HR partner**")
            st.caption(report.komunikat)
            return
        ui.html(f"<b>🤝 HR partner</b><br>{ui.source_note('AI' if report['zrodlo_tekstow'] == 'AI' else 'REGULY')}<br>"
                "<span class='lock'>Podpowiedzi dla przełożonego przed rozmową – nie są oceną pracownika.</span>")
        if not report["sygnaly"]:
            st.caption("Brak sygnałów w notatkach z ostatnich miesięcy.")
        for sg in report["sygnaly"]:
            title, tone = SIGNAL_LABEL.get(sg["typ"], (sg["typ"], "c-blue"))
            body = f"<p>{escape(sg['opis'])}</p>" + ("<b>Co możesz zrobić:</b>" + ui.ul(sg["rekomendacje"])
                                                    if sg.get("rekomendacje") else "")
            ui.card(title, body, tone)
            if sg.get("dowody"):
                with st.expander("Na podstawie"):
                    ui.html(ui.ul(sg["dowody"]))
            if sg["status"] != "NOWY":
                st.markdown(ui.badge("✔ Przyjęto" if sg["status"] == "ZAAKCEPTOWANY" else "✖ Odrzucono",
                                     "b-green" if sg["status"] == "ZAAKCEPTOWANY" else "b-grey"),
                            unsafe_allow_html=True)
            else:
                a, b = st.columns(2)

                def decide(sid: int, status: str) -> None:
                    if _call(api.hr_decision, sid, status, ok="Zapisano decyzję."):
                        pass
                    st.session_state.get("ai_cache", {}).pop(("hr", ev["id"], ev["updated_at"]), None)

                a.button("Przyjmij", key=f"hr_ok_{sg['id']}", type="primary", use_container_width=True,
                         on_click=decide, args=(sg["id"], "ZAAKCEPTOWANY"))
                b.button("Odrzuć", key=f"hr_no_{sg['id']}", use_container_width=True,
                         on_click=decide, args=(sg["id"], "ODRZUCONY"))
        st.caption("Asystent tylko podpowiada. Ocenę wystawia przełożony.")


# ---------------------------------------------------------------- page

def render(api: Api, me: dict, meta: dict, evaluation_id: int, ai: bool) -> None:
    today = to_date(meta["dzis"])
    try:
        ev = api.evaluation(evaluation_id)
    except ApiError as e:
        st.error(e.komunikat)
        return
    items = [i for i in api.dashboard()["pozycje"] if i["evaluation_id"]]
    ids = [i["evaluation_id"] for i in items]
    labels = {i["evaluation_id"]: f"{name(i['oceniany'])} – {STATUS_LABEL.get(i['status'], '')}" for i in items}
    if evaluation_id not in ids:  # e.g. an earlier evaluation (objection) while the next cycle is already open
        ids.insert(0, evaluation_id)
        labels[evaluation_id] = (f"{name(ev['oceniany'])} – ocena z {ui.fmt(ev['czesc_ii'].get('data_sporzadzenia'))}"
                                 if ev["czesc_ii"].get("data_sporzadzenia") else name(ev["oceniany"]))
    top1, top2, _ = st.columns([1, 1.6, 2.4])
    if top1.button("← Mój zespół", use_container_width=True):
        st.session_state.view = "team"
        st.rerun()
    chosen = top2.selectbox("Pracownik", ids, index=ids.index(evaluation_id), format_func=labels.get,
                            label_visibility="collapsed", key=f"pick_{evaluation_id}")
    if chosen != evaluation_id:
        open_evaluation(chosen)
        st.rerun()
    _show_flash()
    _header(ev, today)

    sel_key = f"sel_{evaluation_id}"
    cur = current_stage(ev)
    if sel_key not in st.session_state:
        st.session_state[sel_key] = min(cur, len(STAGES))
    selected = ui.stepper(ev, st.session_state[sel_key], sel_key)

    main, side = st.columns([2.6, 1.25], gap="large")
    with main:
        _person(ev)
        with st.container(border=True):
            st.markdown(f"### Etap {selected}: {STAGES[selected - 1]}")
            reachable = selected <= cur or (selected == 3 and ev["status"] == "OKRES_OCENY")
            if not reachable:
                st.info("Ten etap jeszcze się nie rozpoczął – najpierw zakończ poprzednie.")
            elif selected == 1:
                _stage_criteria(api, ev, ai, today)
            elif selected == 2:
                _stage_observation(api, ev, me, ai, today)
            elif selected == 3:
                _stage_review(api, ev, ai, today)
            elif selected == 4:
                _stage_sheet(api, ev, me, ai, meta)
            else:
                _stage_ack(api, ev)
    with side:
        _progress(ev)
        _summary(ev)
        _timeline(api, ev)
        if (ai and ev["jako_oceniajacy"] and meta.get("funkcje_ai", {}).get("hr_partner")
                and ev["status"] not in ("OCENA_DO_ZAPOZNANIA", "ZAKONCZONA")):
            _hr_partner(api, ev)
