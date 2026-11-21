"""Overview of evaluations (GET /api/dashboard): evaluator – own subordinates, HR – whole office.
Stats, the stage bar, filters, sortable list, "Wymaga uwagi", and the full schedule page."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api
from frontend.process import DONE, STAGE_OF_STATUS, STAGES, STATUS_LABEL, WHO_LABEL, name

URGENCY_KEY = {"PO_TERMINIE": "late", "PILNE": "soon", "WKROTCE": "soon", "OK": "ok"}
FUNNEL = [("KRYTERIA", "Wyznaczenie kryteriów", "#9fb4d6"), ("KRYTERIA_DO_POTWIERDZENIA", "Potwierdzenie kryteriów", "#6f8fc4"),
          ("OKRES_OCENY", "Okres oceny", "#3f6db3"), ("ROZMOWA_OCENIAJACA", "Sporządzenie oceny", "#1f5fbf"),
          ("OCENA_DO_ZAPOZNANIA", "Zapoznanie z oceną", "#163f80"), ("ZAKONCZONA", "Zakończone", "#1d7444")]
WYNIK = {"POZYTYWNA": ("pozytywna", "b-green"), "NEGATYWNA": ("negatywna", "b-red")}


def open_evaluation(evaluation_id: int, stage: int | None = None) -> None:
    st.session_state.view = "eval"
    st.session_state.eval_id = evaluation_id
    if stage:
        st.session_state[f"sel_{evaluation_id}"] = stage
    else:
        st.session_state.pop(f"sel_{evaluation_id}", None)  # opens on the current stage


def _stage_of(item: dict) -> int:
    return STAGE_OF_STATUS.get(item["status"], 0) if item["status"] else 0


def _urgency(item: dict) -> str:
    if item["status"] in ("ZAKONCZONA", None) or item["dni_do_terminu"] is None:
        return "none"
    return URGENCY_KEY.get(item["pilnosc"], "ok")


SORT_KEYS = {
    "pilnosc": lambda i: (_urgency(i) == "none", i["dni_do_terminu"] if i["dni_do_terminu"] is not None else 10**6),
    "pracownik": lambda i: name(i["oceniany"]),
    "komorka": lambda i: (i.get("komorka") or "", name(i["oceniany"])),
    "etap": lambda i: (_stage_of(i), name(i["oceniany"])),
    "termin": lambda i: (i["termin"] is None, i["termin"] or ""),
    "wynik": lambda i: (i.get("wynik") or "~", name(i["oceniany"])),
}


def _toggle_sort(col: str) -> None:
    cur, asc = st.session_state.get("team_sort", ("pilnosc", True))
    st.session_state.team_sort = (col, not asc if cur == col else True)


def _stats(items: list[dict]) -> None:
    total = len(items)
    done = sum(i["status"] == "ZAKONCZONA" for i in items)
    not_started = sum(i["evaluation_id"] is None for i in items)
    running = total - done - not_started
    overdue = sum(_urgency(i) == "late" for i in items)
    negative = sum(i.get("wynik") == "NEGATYWNA" for i in items)

    def pct(n: int) -> str:
        return f"{round(n / total * 100)}% objętych oceną" if total else "0%"

    cards = [("Objęci oceną", total, "osoby w wybranym zakresie", ""),
             ("Zakończone", done, pct(done), "c-green"),
             ("W toku", running, pct(running), ""),
             ("Nierozpoczęte", not_started, pct(not_started), ""),
             ("Po terminie", overdue, "wymaga pilnej reakcji" if overdue else "brak przekroczeń",
              "c-red" if overdue else ""),
             ("Oceny negatywne", negative, "sporządzone w tym cyklu", "c-red" if negative else "")]
    ui.html('<div class="stats">' + "".join(
        f'<div class="card stat {tone}"><div class="lock">{escape(label)}</div><div class="v">{value}</div>'
        f'<div class="lock">{escape(sub)}</div></div>' for label, value, sub, tone in cards) + "</div>")


def _funnel(items: list[dict]) -> None:
    def bucket(i: dict) -> str:
        if i["status"] in (None, "KRYTERIA_DO_WYZNACZENIA"):
            return "KRYTERIA"
        return "ZAKONCZONA" if i["status"] in ("ZAKONCZONA", "SPRZECIW") else i["status"]

    counts = [(label, color, sum(bucket(i) == key for i in items)) for key, label, color in FUNNEL]
    total = sum(n for _, _, n in counts)
    bar = "".join(f'<span title="{escape(lbl)}: {n}" style="flex:{n};background:{c}"></span>'
                  for lbl, c, n in counts if n)
    legend = "".join(f'<div class="funnel-item"><span class="sw" style="background:{c}"></span>{escape(lbl)} '
                     f'<b>{n}</b></div>' for lbl, c, n in counts)
    aria = escape(", ".join(f"{lbl}: {n}" for lbl, _, n in counts))
    ui.html(f'<div class="card"><h4>Etapy procesu <span class="lock">· razem {total}'
            f'{" (w tym nierozpoczęte w pierwszym etapie)" if any(i["status"] is None for i in items) else ""}'
            f'</span></h4><div class="funnel-bar" role="img" aria-label="{aria}">{bar}</div>'
            f'<div class="funnel-legend">{legend}</div></div>')


def _attention(items: list[dict]) -> None:
    upcoming = sorted((i for i in items if i["dni_do_terminu"] is not None and i["status"] != "ZAKONCZONA"),
                      key=lambda i: i["dni_do_terminu"])[:3]
    waiting = [i for i in items if i["kto_dziala"] == "OCENIANY"]
    not_started = [i for i in items if i["evaluation_id"] is None]
    objections = [i for i in items if i["status"] == "SPRZECIW"]
    with st.container(border=True):
        st.markdown("**🔎 Wymaga uwagi**")
        sections = (
            ("Najbliższe terminy", upcoming, "Brak zbliżających się terminów.",
             lambda i: f"{ui.fmt(i['termin'])} · {ui.days_text(i['dni_do_terminu'])}"),
            ("Czekają na potwierdzenie pracownika", waiting, "Nikt nie czeka.", lambda i: STATUS_LABEL[i["status"]]),
            ("Nierozpoczęte cykle oceny", not_started, "Wszystkie cykle rozpoczęte.", lambda i: f"arkusz {i['arkusz']}"),
            ("Sprzeciwy w toku", objections, "Brak sprzeciwów.", lambda i: "sprzeciw"),
        )
        for n, (title, rows, empty, detail) in enumerate(sections):
            st.markdown(f"{title} {ui.badge(str(len(rows)), 'b-amber' if rows else 'b-grey')}",
                        unsafe_allow_html=True)
            if not rows:
                st.caption(empty)
            for k, i in enumerate(rows):
                label = f"{name(i['oceniany'])} · {detail(i)}"
                if i["evaluation_id"]:
                    st.button(label, key=f"att_{n}_{k}", type="tertiary", on_click=open_evaluation,
                              args=(i["evaluation_id"],))
                else:
                    st.caption(label)


def render(api: Api, me: dict) -> None:
    items = api.dashboard()["pozycje"]
    hr = me["rola"] == "KADRY"
    st.subheader("Oceny okresowe – cały urząd" if hr else "Mój zespół")
    st.caption("Stan ocen okresowych w urzędzie (dane przykładowe)." if hr else
               "Oceny osób, które oceniasz – termin, etap i to, kto ma teraz wykonać krok.")
    if not items:
        st.info("Nie oceniasz nikogo – brak ocen do pokazania.")
        return

    units = sorted({i.get("komorka") for i in items if i.get("komorka")})
    f0, f1, f2, f3, f4 = st.columns([1.3, 1.6, 1.4, 1.1, 1.1], vertical_alignment="bottom")
    unit = f0.selectbox("Komórka", ["Wszystkie"] + units)
    scoped = [i for i in items if unit == "Wszystkie" or i.get("komorka") == unit]
    q = f1.text_input("Szukaj pracownika", placeholder="nazwisko lub stanowisko", key="team_q")
    stage_opts = ["Wszystkie"] + [f"{n} · {s}" for n, s in enumerate(STAGES, start=1)] + ["Zakończona", "Nierozpoczęta"]
    stage = f2.selectbox("Etap", stage_opts)
    result = f3.selectbox("Wynik", ["Wszystkie", "Pozytywna", "Negatywna", "Brak wyniku"])
    due = f4.selectbox("Termin", ["Wszystkie", "Po terminie", "≤ 30 dni", "Później"])
    st.button("🔍 Szukaj", key="team_search")

    _stats(scoped)
    _funnel(scoped)

    view = scoped
    if q:
        ql = q.casefold()
        view = [i for i in view if ql in f"{name(i['oceniany'])} {i['oceniany'].get('stanowisko') or ''}".casefold()]
    if stage != "Wszystkie":
        want = int(stage[0]) if stage[0].isdigit() else {"Zakończona": DONE, "Nierozpoczęta": 0}[stage]
        view = [i for i in view if _stage_of(i) == want or (want == 3 and i["status"] == "OKRES_OCENY")]
    if result != "Wszystkie":
        want = {"Pozytywna": "POZYTYWNA", "Negatywna": "NEGATYWNA", "Brak wyniku": None}[result]
        view = [i for i in view if i.get("wynik") == want]
    if due == "Po terminie":
        view = [i for i in view if _urgency(i) == "late"]
    elif due == "≤ 30 dni":
        view = [i for i in view if _urgency(i) != "none" and 0 <= i["dni_do_terminu"] <= 30]
    elif due == "Później":
        view = [i for i in view if _urgency(i) != "none" and i["dni_do_terminu"] > 30]
    sort_col, asc = st.session_state.get("team_sort", ("pilnosc", True))
    view = sorted(view, key=SORT_KEYS[sort_col], reverse=not asc)

    main, side = st.columns([2.7, 1.3], gap="large")
    with main:
        widths = [1.1, 2.2, 1.5, 0.5, 1.8, 1.2, 1.0]
        head = st.columns(widths, vertical_alignment="center")
        headers = [("pilnosc", "Pilność"), ("pracownik", "Pracownik"), ("komorka", "Komórka"), (None, "Ark."),
                   ("etap", "Etap · kto działa"), ("termin", "Termin"), ("wynik", "Wynik")]
        for col, (key, label) in zip(head, headers):
            if key is None:
                col.markdown(f"<span class='lock'><b>{label}</b></span>", unsafe_allow_html=True)
                continue
            arrow = (" ▲" if asc else " ▼") if key == sort_col else ""
            col.button(label + arrow, key=f"sort_{key}", type="tertiary", on_click=_toggle_sort, args=(key,),
                       help=("Po terminie / Wkrótce (do 30 dni) / W terminie – termin bieżącego etapu. "
                             if key == "pilnosc" else "") + "Kliknij, aby posortować; ponownie – odwrotnie.")
        for i in view:
            eid = i["evaluation_id"]
            with st.container(border=True, key=f"row_{eid}" if eid else None):
                if eid:  # the whole row is one button (CSS stretches it over the row)
                    st.button(f"Otwórz ocenę: {name(i['oceniany'])}", key=f"rowbtn_{eid}", on_click=open_evaluation,
                              args=(eid,), help="Otwórz ocenę pracownika")
                c = st.columns(widths, vertical_alignment="center")
                c[0].markdown(ui.urgency_badge(_urgency(i)), unsafe_allow_html=True)
                c[1].markdown(f"**{name(i['oceniany'])}**" + (" →" if eid else ""))
                c[1].caption(i["oceniany"].get("stanowisko") or "")
                c[2].markdown(i.get("komorka") or "—")
                c[3].markdown(i["arkusz"])
                status = STATUS_LABEL.get(i["status"], "Nierozpoczęta") if i["status"] else "Nierozpoczęta"
                c[4].markdown(f"{escape(status)}<br><span class='lock'>działa: {WHO_LABEL[i['kto_dziala']]}</span>",
                              unsafe_allow_html=True)
                days = "" if _urgency(i) == "none" else f"<br><span class='lock'>{ui.days_text(i['dni_do_terminu'])}</span>"
                c[5].markdown(f"{ui.fmt(i['termin'])}{days}", unsafe_allow_html=True)
                w = WYNIK.get(i.get("wynik"))
                c[6].markdown(ui.badge(*w) if w else "<span class='lock'>—</span>", unsafe_allow_html=True)
        if not view:
            st.caption("Brak pozycji spełniających wybrane filtry.")
    with side:
        _attention(scoped)


def render_schedule(api: Api, me: dict) -> None:
    items = api.dashboard()["pozycje"]
    st.subheader("🗓️ Terminy")
    st.caption("Terminy liczone przez system (24 miesiące, dni wolne, nieobecności), od najbliższego. "
               "Kliknij pozycję, aby przejść do oceny.")
    rows = sorted((i for i in items if _urgency(i) != "none"), key=lambda i: i["dni_do_terminu"])
    with st.container(border=True):
        for k, i in enumerate(rows):
            tag = {"late": "🔴 Po terminie · ", "soon": "🟡 Wkrótce · "}.get(_urgency(i), "")
            step = i.get("nastepny_krok") or STATUS_LABEL.get(i["status"], "")
            st.button(f"{tag}**{ui.fmt(i['termin'])}** · {step} – {name(i['oceniany'])} "
                      f"(działa: {WHO_LABEL[i['kto_dziala']]})",
                      key=f"sched_{k}", type="tertiary", on_click=open_evaluation, args=(i["evaluation_id"],))
        if not rows:
            st.caption("Brak terminów do pilnowania.")
