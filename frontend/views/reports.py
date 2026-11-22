"""Dashboard: statistics from /api/reports – progress, outcomes, training needs. The server decides the scope (HR: the
whole office, a supervisor: their people) and hides groups smaller than the office minimum."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from frontend import ui
from frontend.api_client import Api, ApiError
from frontend.process import LEVEL_LABEL, STATUS_LABEL

BAR = "#4a72c4"
LEVEL_ORDER = ["ZNACZNIE_PONIZEJ", "PONIZEJ", "NA_POZIOMIE", "POWYZEJ", "ZNACZNIE_POWYZEJ"]


def _get(fn, **kw):
    try:
        return fn(**kw)
    except ApiError as e:
        ui.api_error(e)
        return None


def _bars(rows: dict[str, float], label: str, horizontal: bool = True) -> None:
    """Bar chart with full category names (Altair: no cut labels, order as given, value at the end of the bar)."""
    import altair as alt

    rows = {k: v for k, v in rows.items() if v is not None}
    if not rows:
        st.caption("Brak danych.")
        return
    df = pd.DataFrame({"kat": list(rows), "val": list(rows.values())})
    order = list(rows)
    tip = [alt.Tooltip("kat:N", title=""), alt.Tooltip("val:Q", title=label)]
    if horizontal:
        base = alt.Chart(df).encode(
            y=alt.Y("kat:N", sort=order, title=None, axis=alt.Axis(labelLimit=320, labelFontSize=13),
                    scale=alt.Scale(paddingInner=0.35)),
            x=alt.X("val:Q", title=label, axis=alt.Axis(grid=False, tickMinStep=1)), tooltip=tip)
        chart = base.mark_bar(color=BAR, cornerRadiusEnd=3) + base.mark_text(
            align="left", dx=4, fontSize=12).encode(text=alt.Text("val:Q", format="~g"))
        height = 44 * len(rows) + 80  # axis and its title need ~80 px; each bar gets its own row
    else:
        base = alt.Chart(df).encode(
            x=alt.X("kat:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelLimit=200)),
            y=alt.Y("val:Q", title=label, axis=alt.Axis(grid=False)), tooltip=tip)
        chart = base.mark_bar(color=BAR, cornerRadiusEnd=3, size=36) + base.mark_text(
            dy=-8, fontSize=12).encode(text=alt.Text("val:Q", format="~g"))
        height = 260
    st.altair_chart(chart.properties(height=height), use_container_width=True)


def _metrics(items: list[tuple[str, str, str | None]]) -> None:
    for col, (label, value, hint) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.metric(label, value, help=hint)


def _progress(api: Api, rok: int | None, unit: str | None) -> None:
    p = _get(api.report_progress, rok=rok, komorka=unit)
    if p is None:
        return
    pct = p.get("w_terminie_proc")
    _metrics([("Objęci oceną", str(p["objeci_ocena"]), "Osoby w zakresie raportu"),
              ("Oceny w toku", str(p["w_toku"]), None),
              ("Sporządzone", str(p["sporzadzone"]), None),
              ("Po terminie", str(p["po_terminie"]), "Oceny, których termin minął, a nie są sporządzone"),
              ("W terminie", f"{pct:.0f}%" if pct is not None else "—", "Odsetek ocen sporządzonych w terminie")])
    if p.get("oczekuje_na_ocenianego") or p.get("bez_cyklu"):
        st.caption(f"Czeka na krok ocenianego: {p.get('oczekuje_na_ocenianego', 0)} · "
                   f"bez rozpoczętej oceny: {p.get('bez_cyklu', 0)}")
    a, b = st.columns(2, gap="large")
    with a:
        st.markdown("**Oceny według etapu**")
        _bars({STATUS_LABEL.get(k, k): v for k, v in p["statusy"].items()}, "Liczba ocen")
    with b:
        st.markdown("**Średni czas etapu (dni)**")
        _bars({STATUS_LABEL.get(k, k): v for k, v in p["sredni_czas_etapow_dni"].items()}, "Dni")
    if p.get("komorki"):
        st.markdown("**Porównanie komórek**")
        df = pd.DataFrame([{"Komórka": u["komorka"], "Objęci": u["objeci_ocena"], "W toku": u["w_toku"],
                            "Sporządzone": u["sporzadzone"], "Po terminie": u["po_terminie"],
                            "W terminie %": u["w_terminie_proc"]} for u in p["komorki"]])
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config={"W terminie %": st.column_config.ProgressColumn(
                         "W terminie", min_value=0, max_value=100, format="%.0f%%")})


def _outcomes(api: Api, rok: int | None, unit: str | None) -> None:
    f1, f2, _ = st.columns([1.3, 1, 1.7])
    lv = f1.selectbox("Pokaż osoby z poziomem", ["—"] + LEVEL_ORDER, key="rep_level",
                      format_func=lambda k: "—" if k == "—" else LEVEL_LABEL[k])
    res = f2.selectbox("…albo z wynikiem", ["—", "POZYTYWNA", "NEGATYWNA"], key="rep_result",
                       format_func=lambda k: {"—": "—", "POZYTYWNA": "pozytywny", "NEGATYWNA": "negatywny"}[k])
    o = _get(api.report_outcomes, rok=rok, komorka=unit, poziom=None if lv == "—" else lv,
             wynik=None if res == "—" else res)
    if o is None:
        return
    if o.get("ukryte"):
        st.info(f":material/lock: Ocenionych osób: {o['ocenieni']}. Wyniki pokazujemy dopiero dla grup od {o['minimalna_grupa']} "
                "osób – mniejsze grupy są ukryte, żeby nie dało się rozpoznać ocen konkretnych osób.")
    else:
        a, b = st.columns(2, gap="large")
        with a:
            st.markdown("**Rozkład poziomów**")
            counts = {x["poziom"]: x["liczba"] for x in o["poziomy"]}
            _bars({LEVEL_LABEL[k]: counts.get(k, 0) for k in LEVEL_ORDER}, "Osoby")
        with b:
            st.markdown("**Średnia według kryterium**")
            _bars({g["nazwa"]: g["srednia"] for g in o["kryteria"] if not g["ukryte"]}, "Średnia (1–5)")
        c, d = st.columns(2, gap="large")
        with c:
            st.markdown("**Komórki – odsetek ocen pozytywnych**")
            _bars({g["nazwa"]: g["pozytywne_proc"] for g in o["komorki"] if not g["ukryte"]}, "%")
        with d:
            st.markdown("**Trend między cyklami (średnia)**")
            _bars({g["nazwa"]: g["srednia"] for g in o["trend"] if not g["ukryte"]}, "Średnia", horizontal=False)
    people = o.get("pracownicy") or []
    if lv != "—" or res != "—":
        st.markdown(f"**Osoby ({len(people)})**")
        if not people:
            st.caption("Brak osób dla tego filtra (albo grupa jest za mała, żeby ją pokazać).")
        for p in people:
            c = st.columns([2, 2, 2, 1, 1], vertical_alignment="center")
            c[0].markdown(f"**{escape(p['pracownik'])}**")
            c[1].markdown(p.get("komorka") or "—")
            c[2].markdown(LEVEL_LABEL.get(p.get("poziom"), "—"))
            c[3].markdown(ui.fmt(p.get("data_oceny")))
            if p.get("evaluation_id"):
                from frontend.views.team import open_evaluation

                c[4].button("Otwórz", key=f"rep_open_{p['evaluation_id']}", on_click=open_evaluation,
                            args=(p["evaluation_id"],), use_container_width=True)


def _training(api: Api, unit: str | None, ai: bool) -> None:
    t = _get(api.report_training, komorka=unit)
    if t is None:
        return
    st.caption(f"Niska ocena cząstkowa = poniżej {t['prog']} pkt. Zakres: {t['zakres']}.")
    a, b = st.columns([1.2, 1], gap="large")
    with a:
        st.markdown("**Obszary szkoleń – liczba niskich ocen**")
        _bars({r["obszar"]: r["niskie_oceny"] for r in t["ranking"]}, "Niskie oceny")
    with b:
        if ai and t.get("rekomendacja"):
            with st.container(key="aibox_training"):
                ui.html(f"<b class='ai-text'>:material/smart_toy: Rekomendacja asystenta AI</b><br>{ui.source_note(t.get('zrodlo') or 'SZABLON')}")
                st.markdown(t["rekomendacja"])
        st.download_button(":material/download: Pobierz CSV (osoby i potrzeby)", lambda: api.report_training_csv(unit),
                           file_name="potrzeby-szkoleniowe.csv", mime="text/csv", on_click="ignore",
                           use_container_width=True)
    if t.get("osoby"):
        st.markdown("**Osoby i obszary do rozwoju**")
        rows = [{"Pracownik": p["pracownik"], "Komórka": p.get("komorka") or "—",
                 "Obszary": ", ".join(n.get("area") or n.get("criterion", "") for n in p["potrzeby"]),
                 "Wnioski IPRZ": p.get("wnioski_iprz") or ""} for p in t["osoby"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render(api: Api, me: dict, ai: bool = True) -> None:
    st.subheader(":material/bar_chart: Dashboard", help="Statystyki ocen z serwera. Kadry widzą cały urząd, przełożony – osoby, których "
                 "oceny widzi. Wyniki małych grup są ukryte (ochrona prywatności).")
    base = _get(api.report_progress)
    if base is None:
        return
    years = sorted({y for y in range(2024, ui.to_date(api.meta()["dzis"]).year + 1)}, reverse=True)
    f1, f2, _ = st.columns([1, 1.4, 2])
    year = f1.selectbox("Rok", ["Wszystkie"] + years, key="rep_year")
    units = base.get("dostepne_komorki") or []
    unit = f2.selectbox("Komórka", ["Wszystkie"] + units, key="rep_unit") if len(units) > 1 else "Wszystkie"
    rok = None if year == "Wszystkie" else int(year)
    komorka = None if unit == "Wszystkie" else unit
    st.caption(f"Zakres: {base['zakres']}.")
    tabs = st.tabs([":material/trending_up: Postęp ocen", ":material/track_changes: Wyniki", ":material/school: Potrzeby szkoleniowe"])
    with tabs[0]:
        _progress(api, rok, komorka)
    with tabs[1]:
        _outcomes(api, rok, komorka)
    with tabs[2]:
        _training(api, komorka, ai)
