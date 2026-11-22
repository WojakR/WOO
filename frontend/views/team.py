"""Overview of evaluations (GET /api/dashboard): evaluator – own subordinates, HR – whole office.
Filters, sortable list, "Wymaga uwagi", and the full schedule page."""
from __future__ import annotations

from html import escape

import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import DONE, STAGE_OF_STATUS, STAGES, STATUS_LABEL, WHO_LABEL, name

URGENCY_KEY = {"PO_TERMINIE": "late", "PILNE": "soon", "WKROTCE": "soon", "OK": "ok"}
WYNIK = {"POZYTYWNA": ("pozytywna", "b-green"), "NEGATYWNA": ("negatywna", "b-red")}
SIGNAL_SHORT = {"PRZECIAZENIE": ":material/warning: przeciążenie", "DLUGA_NIEOBECNOSC": ":material/medical_services: nieobecność",
                "ZMIANA_OBOWIAZKOW": ":material/sync: nowe obowiązki", "SPADEK_OCEN": ":material/trending_down: spadek ocen", "DO_DOCENIENIA": ":material/celebration: docenić",
                "SPADEK_PRZY_STAZU": ":material/trending_down: spadek przy stażu",
                "SPADEK_TRENDU": ":material/trending_down: wyniki spadają", "STAGNACJA": ":material/trending_flat: ten sam poziom",
                "STABILNIE_WYSOKO": ":material/star: stabilnie wysoko", "WZROST": ":material/trending_up: wzrost",
                "NOWY_PRACOWNIK": ":material/waving_hand: nowy pracownik"}


def _signals(api: Api, item: dict) -> list[str]:
    """HR partner signals of one evaluation from the server (GET /api/evaluations/{id}/hr-partner).
    The dashboard has a `sygnaly_hr` count, but the server does not fill it yet."""
    if not item["evaluation_id"] or item["status"] in ("OCENA_DO_ZAPOZNANIA", "ZAKONCZONA"):
        return []
    try:
        report = api.hr_partner(item["evaluation_id"])
    except ApiError:
        return []
    return [SIGNAL_SHORT.get(sg["typ"], sg["typ"]) for sg in report["sygnaly"] if sg["status"] != "ODRZUCONY"]


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


def _attention(items: list[dict]) -> None:
    upcoming = sorted((i for i in items if i["dni_do_terminu"] is not None and i["status"] != "ZAKONCZONA"),
                      key=lambda i: i["dni_do_terminu"])[:3]
    waiting = [i for i in items if i["kto_dziala"] == "OCENIANY"]
    not_started = [i for i in items if i["evaluation_id"] is None]
    objections = [i for i in items if i["status"] == "SPRZECIW"]
    count = len(upcoming) + len(waiting) + len(not_started) + len(objections)
    with st.expander(f":material/search: Wymaga uwagi ({count})", expanded=False):
        sections = (
            ("Najbliższe terminy", upcoming, "Brak zbliżających się terminów.",
             lambda i: f"{ui.fmt(i['termin'])} · {ui.days_text(i['dni_do_terminu'])}"),
            ("Czekają na potwierdzenie pracownika", waiting, "Nikt nie czeka.", lambda i: STATUS_LABEL[i["status"]]),
            ("Nierozpoczęte cykle oceny", not_started, "Wszystkie cykle rozpoczęte.", lambda i: f"arkusz {i['arkusz']}"),
            ("Sprzeciwy w toku", objections, "Brak sprzeciwów.", lambda i: "sprzeciw"),
        )
        for n, (col, (title, rows, empty, detail)) in enumerate(zip(st.columns(4), sections)):
            col.markdown(f"{title} {ui.badge(str(len(rows)), 'b-amber' if rows else 'b-grey')}",
                         unsafe_allow_html=True)
            if not rows:
                col.caption(empty)
            for k, i in enumerate(rows):
                label = f"{name(i['oceniany'])} · {detail(i)}"
                if i["evaluation_id"]:
                    col.button(label, key=f"att_{n}_{k}", type="tertiary", on_click=open_evaluation,
                               args=(i["evaluation_id"],))
                else:
                    col.caption(label)


TASK_KIND = {"DWIE_NEGATYWNE": ":material/warning: Dwie negatywne oceny z rzędu", "STOPIEN_OBLIGATORYJNY": ":material/military_tech: Obligatoryjny kolejny stopień",
             "WNIOSEK_O_STOPIEN": ":material/workspace_premium: Wniosek o kolejny stopień"}


def _hr_tasks(api: Api) -> None:
    """Consequences of consecutive evaluations HR must act on (server: /api/kadry/zadania) – the system decides nothing."""
    try:
        tasks = api.hr_tasks()
    except ApiError:
        return
    if not tasks:
        return
    with st.expander(f":material/push_pin: Zadania kadr ({len(tasks)})", expanded=True):
        for t in tasks:
            c = st.columns([4.5, 1], vertical_alignment="center")
            due = f" · termin {ui.fmt(t['termin'])}" if t.get("termin") else ""
            basis = f" ({t['podstawa']})" if t.get("podstawa") else ""
            c[0].markdown(f"**{TASK_KIND.get(t['rodzaj'], t['rodzaj'])}** · {name(t['oceniany'])}{due}<br>"
                          f"<span class='lock'>{escape(t['tresc'] + basis)}</span>", unsafe_allow_html=True)
            if t.get("evaluation_id"):
                c[1].button("Otwórz", key=f"task_{t['rodzaj']}_{t['evaluation_id']}", on_click=open_evaluation,
                            args=(t["evaluation_id"],), use_container_width=True)


def _deadline_requests(api: Api, own_requests_only: bool = False) -> None:
    """Requests to change the evaluation deadline waiting for a decision: HR decides the evaluators' requests
    (office setting zmiana_terminu.zatwierdza=KADRY), the evaluator decides the evaluated person's own request."""
    from frontend.views.evaluation import DEADLINE_REASON

    try:
        rows = api.deadline_requests("ZLOZONY")
    except ApiError:
        return
    if own_requests_only:  # an evaluator: only the requests the evaluated people filed themselves
        rows = [r for r in rows if (r.get("zlozyl") or {}).get("id") == (r.get("oceniany") or {}).get("id")]
    if not rows:
        return
    with st.expander(f"Wnioski o zmianę terminu oceny ({len(rows)})", icon=":material/edit_calendar:", expanded=True):
        for r in rows:
            with st.container(border=True):
                st.markdown(f"**{name(r.get('oceniany'))}** · {ui.fmt(r['stary_termin'])} → "
                            f"**{ui.fmt(r.get('nowy_termin')) if r.get('nowy_termin') else 'termin do ustalenia'}** · "
                            f"{DEADLINE_REASON.get(r['powod'], r['powod'])} · złożył(a): {name(r.get('zlozyl'))}")
                if r.get("uzasadnienie"):
                    st.caption(r["uzasadnienie"])
                c = st.columns([3, 1, 1, 1], vertical_alignment="bottom")
                note = c[0].text_input("Komentarz do decyzji", key=f"dcd_note_{r['id']}")
                for col, status, label in ((c[1], "ZAAKCEPTOWANY", "Zatwierdź"), (c[2], "ODRZUCONY", "Odrzuć")):
                    if col.button(label, key=f"dcd_{status}_{r['id']}", type="primary" if status == "ZAAKCEPTOWANY"
                                  else "secondary", use_container_width=True):
                        try:
                            api.decide_deadline_change(r["id"], status, note.strip())
                            st.toast("Zapisano decyzję.")
                        except ApiError as e:
                            ui.api_error(e)
                            continue
                        st.rerun()
                if r.get("evaluation_id"):
                    c[3].button("Otwórz ocenę", key=f"dcd_open_{r['id']}", on_click=open_evaluation,
                                args=(r["evaluation_id"],), use_container_width=True)


def _withheld_notes(api: Api) -> None:
    """After a change of the evaluator my notes on that person wait until I hand them over (§ 9 ust. 3)."""
    try:
        notes = api.withheld_notes()
    except ApiError:
        return
    if not notes:
        return
    with st.expander(f"Notatki do przekazania nowemu oceniającemu ({len(notes)})", icon=":material/forward_to_inbox:",
                     expanded=True):
        st.caption("Po zmianie oceniającego Twoje notatki o tej osobie są wstrzymane – nowy oceniający zobaczy je "
                   "dopiero, gdy je przekażesz. Notatek, których nie chcesz przekazać, nie przekazuj.")
        if st.button("Przekaż wszystkie", icon=":material/send:", key="ho_all"):
            for n in notes:
                try:
                    api.hand_over_note(n["id"])
                except ApiError as e:
                    ui.api_error(e)
                    break
            else:
                st.toast("Przekazano notatki.")
                st.rerun()
        for n in notes:
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"<span class='lock'>{ui.fmt(n['data'])}</span> {escape(n['tresc'])}", unsafe_allow_html=True)
            if c2.button("Przekaż", key=f"ho_{n['id']}", use_container_width=True):
                try:
                    api.hand_over_note(n["id"])
                    st.toast("Przekazano notatkę.")
                except ApiError as e:
                    ui.api_error(e)
                st.rerun()


def _direct_reports(api: Api, me: dict) -> set[int]:
    """People I evaluate myself (their direct supervisor is me) – the server's employee list says who reports to whom."""
    try:
        rows = api.employees(na_strone=200)["pozycje"]
    except ApiError:
        return set(me.get("podwladni_ids") or [])
    my_id = me["pracownik"]["id"]
    return {r["pracownik"]["id"] for r in rows if (r["pracownik"].get("przelozony") or {}).get("id") == my_id}


def _start(api: Api, employee_number: int) -> None:
    """Start a cycle for a person who has none (the server picks the sheet, dates and evaluator) and open it."""
    try:
        ev = api.start(employee_number)
    except ApiError as e:
        st.session_state.setdefault("flash", []).append(("error", " ".join(e.messages)))
        return
    st.toast("Rozpoczęto ocenę okresową.")
    open_evaluation(ev["id"])


def _one_row_per_case(items: list[dict]) -> list[dict]:
    """After acknowledgement the server starts the next period at once, so a person can have two evaluations.
    A finished one next to a newer one goes to Archiwum; two open ones (e.g. an evaluation drawn up again after an
    objection, a re-evaluation + the next period) both stay, numbered by deadline."""
    by_person: dict[int, list[dict]] = {}
    for i in items:
        by_person.setdefault(i["oceniany"]["id"], []).append(i)
    out = []
    for rows in by_person.values():
        if len(rows) > 1:
            rows = [r for r in rows if r["status"] != "ZAKONCZONA"] or rows[-1:]
        if len(rows) > 1:
            rows = sorted(rows, key=lambda r: r["termin"] or "")
            for n, r in enumerate(rows, start=1):
                r["_label"] = f"ocena {n} z {len(rows)} w toku"
        out.extend(rows)
    return out


def render(api: Api, me: dict, ai: bool = True) -> None:
    items = _one_row_per_case(api.dashboard()["pozycje"])
    hr = me["rola"] == "KADRY"
    for kind, text in st.session_state.pop("flash", []):
        (st.error if kind == "error" else st.success)(text)
    st.subheader("Oceny okresowe – cały urząd" if hr else "Mój zespół",
                 help="Stan ocen okresowych w urzędzie (dane przykładowe)." if hr else
                 "Oceny osób, które oceniasz – termin, etap i to, kto ma teraz wykonać krok. Kliknij wiersz, "
                 "aby otworzyć ocenę.")
    if not items:
        st.info("Nie oceniasz nikogo – brak ocen do pokazania.")
        return
    if hr:
        _hr_tasks(api)
        _deadline_requests(api)
    else:
        _withheld_notes(api)
        _deadline_requests(api, own_requests_only=True)
    # a supervisor higher up also sees the evaluations of their managers' teams (office setting PODDRZEWO);
    # by default only the people they evaluate themselves – the rest on demand
    mine = _direct_reports(api, me)
    others = [] if hr else [i for i in items if i["oceniany"]["id"] not in mine]
    if others:
        scope = st.segmented_control("Pokaż", ["mine", "all"], default="mine", key="team_scope",
                                     format_func={"mine": f"Osoby, które oceniam ({len(items) - len(others)})",
                                                  "all": f"Cały mój pion ({len(items)})"}.get)
        if scope != "all":
            items = [i for i in items if i["oceniany"]["id"] in mine]

    units = sorted({i.get("komorka") for i in items if i.get("komorka")})
    s1, s2, s3 = st.columns([1.4, 1.4, 0.6], vertical_alignment="bottom")
    q_name = s1.text_input("Pracownik", placeholder="imię lub nazwisko", key="team_q_name")
    q_pos = s2.text_input("Stanowisko", placeholder="np. specjalista", key="team_q_pos")
    s3.button(":material/search: Szukaj", key="team_search", use_container_width=True)
    f0, f2, f3, f4 = st.columns([1.3, 1.4, 1.1, 1.1], vertical_alignment="bottom")
    unit = f0.selectbox("Komórka", ["Wszystkie"] + units)
    scoped = [i for i in items if unit == "Wszystkie" or i.get("komorka") == unit]
    stage_opts = ["Wszystkie"] + [f"{n} · {s}" for n, s in enumerate(STAGES, start=1)] + ["Zakończona", "Nierozpoczęta"]
    stage = f2.selectbox("Etap", stage_opts)
    result = f3.selectbox("Wynik", ["Wszystkie", "Pozytywna", "Negatywna", "Brak wyniku"])
    due = f4.selectbox("Termin", ["Wszystkie", "Po terminie", "≤ 30 dni", "Później"])

    view = scoped
    if q_name.strip():
        view = [i for i in view if q_name.strip().casefold() in name(i["oceniany"]).casefold()]
    if q_pos.strip():
        view = [i for i in view if q_pos.strip().casefold() in (i["oceniany"].get("stanowisko") or "").casefold()]
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

    _attention([i for i in scoped if hr or i["oceniany"]["id"] in mine])
    main = st.container()
    with main:
        widths = [1.1, 2.0, 1.3, 0.5, 1.7, 1.2, 1.0] + ([1.4] if ai else [])
        head = st.columns(widths, vertical_alignment="center")
        headers = [("pilnosc", "Pilność"), ("pracownik", "Pracownik"), ("komorka", "Komórka"), (None, "Ark."),
                   ("etap", "Etap · kto działa"), ("termin", "Termin"), ("wynik", "Wynik")] +             ([(None, "Sygnały HR")] if ai else [])
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
            with st.container(border=True, key=f"row_{eid}" if eid else f"rowns_{i['oceniany']['id']}"):
                if eid:  # the whole row is one button (CSS stretches it over the row)
                    st.button(f"Otwórz ocenę: {name(i['oceniany'])}", key=f"rowbtn_{eid}", on_click=open_evaluation,
                              args=(eid,))
                c = st.columns(widths, vertical_alignment="center")
                c[0].markdown(ui.badge("Nierozpoczęta", "b-amber") if i["status"] is None
                              else ui.urgency_badge(_urgency(i)), unsafe_allow_html=True)
                c[1].markdown(f"**{name(i['oceniany'])}**" + (" →" if eid else ""))
                c[1].caption((i["oceniany"].get("stanowisko") or "")
                             + (f" · {i['_label']}" if i.get("_label") else "")
                             + (" · ocenia Twój podwładny" if others and i["oceniany"]["id"] not in mine else ""))
                c[2].markdown(i.get("komorka") or "—")
                c[3].markdown(i["arkusz"])
                status = STATUS_LABEL.get(i["status"], "Nierozpoczęta") if i["status"] else "Nierozpoczęta"
                c[4].markdown(f"{escape(status)}<br><span class='lock'>działa: {WHO_LABEL[i['kto_dziala']]}</span>",
                              unsafe_allow_html=True)
                days = "" if _urgency(i) == "none" else f"<br><span class='lock'>{ui.days_text(i['dni_do_terminu'])}</span>"
                c[5].markdown(f"{ui.fmt(i['termin'])}{days}", unsafe_allow_html=True)
                if ai:
                    sig = _signals(api, i)
                    c[7].markdown(ui.icons("<span class='ai-text'>" + "<br>".join(sig) + "</span>") if sig
                                  else "<span class='lock'>—</span>", unsafe_allow_html=True)
                w = WYNIK.get(i.get("wynik"))
                if eid is None and (hr or i["oceniany"]["id"] in mine):
                    c[6].button("Rozpocznij ocenę", key=f"start_{i['oceniany']['id']}", type="primary",
                                on_click=_start, args=(api, i["oceniany"]["id"]), use_container_width=True)
                else:
                    c[6].markdown(ui.badge(*w) if w else "<span class='lock'>—</span>", unsafe_allow_html=True)
        if not view:
            st.caption("Brak pozycji spełniających wybrane filtry.")


def calendar_button(api: Api, key: str) -> None:
    """All my deadlines as one calendar file (server: GET /api/me/terminy.ics) – the reminder channel for an office
    without e-mail: import it into Outlook / Thunderbird / Google; a newer file updates the events."""
    st.download_button("Dodaj terminy do kalendarza", api.deadlines_ics, icon=":material/event:",
                       file_name="terminy-ocen.ics", mime="text/calendar", on_click="ignore", key=key,
                       use_container_width=True,
                       help="Plik .ics otworzysz w Outlooku, Thunderbirdzie albo Kalendarzu Google – każdy termin "
                            "dostaje przypomnienie 7 dni i 1 dzień wcześniej. Gdy termin się zmieni, pobierz plik "
                            "ponownie: wydarzenia zostaną zaktualizowane, a nie zdublowane.")


def render_schedule(api: Api, me: dict) -> None:
    items = api.dashboard()["pozycje"]
    if me["rola"] != "KADRY":
        mine = _direct_reports(api, me)
        items = [i for i in items if i["oceniany"]["id"] in mine] or items
    head, btn = st.columns([3, 1.1], vertical_alignment="bottom")
    head.subheader(":material/calendar_month: Terminy", help="Terminy liczone przez system (24 miesiące, dni wolne, "
                   "nieobecności), od najbliższego. Kliknij pozycję, aby przejść do oceny.")
    with btn:
        calendar_button(api, "sched_ics")
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

