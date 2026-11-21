"""View 1: evaluation screen for one employee – stepper, the selected stage, summary and HR partner."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

import streamlit as st

from app.domain.cycle import Status
from app.domain.deadlines import Absence
from app.domain.notes import Note, Sentiment, evidence_by_criterion
from app.domain.scoring import Outcome, compute_result
from backend import kprm
from frontend import ui
from frontend.demo_state import (DONE, STAGES, DemoState, change_sheet, default_meeting, ics_invite, open_evaluation,
                                 safe)
from frontend.sheet_export import sheet_html

SENT_OPTS = {"POZYTYWNY": "+ pozytywna", "NEUTRALNY": "neutralna", "NEGATYWNY": "− negatywna"}


# ---------------------------------------------------------------- helpers

def _cached(state: DemoState, key: tuple, compute):
    k = repr(key)
    if k not in state.ai_cache:
        with st.spinner("Asystent przygotowuje propozycję…"):
            state.ai_cache[k] = compute()
    return state.ai_cache[k]


def _notes(state: DemoState, cycle) -> list[Note]:
    return state.notes.get(cycle.id, [])


def _criteria_names(state: DemoState, ids) -> list[str]:
    return [state.service.rules.criterion_name(c) for c in ids]


def _locked(text: str = "Pole zablokowane po zatwierdzeniu etapu – zmiana tylko w trybie korekty (kadry).") -> None:
    ui.html(f'<p class="lock">🔒 {escape(text)}</p>')


def _invite_block(state: DemoState, cycle, stage: int, title: str, minutes: int) -> None:
    emp = state.employee(cycle.employee_id)
    sent = state.invites.get((cycle.id, stage))
    current = sent or default_meeting(state.today)
    if sent:
        st.success(f"Zaproszenie wysłane do: {emp.full_name} – {sent:%d.%m.%Y, %H:%M}. "
                   "Oceniany widzi je w powiadomieniach (🔔).")
    c1, c2, c3 = st.columns([1, 1, 1.3], vertical_alignment="bottom")
    d = c1.date_input("Data rozmowy", current.date(), key=f"inv_d_{cycle.id}_{stage}", format="DD.MM.YYYY")
    t = c2.time_input("Godzina", current.time(), key=f"inv_t_{cycle.id}_{stage}", step=900)
    when = datetime.combine(d, t)
    if c3.button("✉️ Wyślij zaproszenie" if not sent else "✉️ Wyślij nowy termin", key=f"inv_s_{cycle.id}_{stage}",
                 use_container_width=True, type="primary"):
        state.invites[(cycle.id, stage)] = when
        st.toast(f"Wysłano zaproszenie do: {emp.full_name} ({when:%d.%m.%Y, %H:%M}).")
        st.rerun()
    st.download_button(
        "📅 Dodaj do kalendarza (.ics – Outlook, Thunderbird)",
        ics_invite(f"{title} – {emp.full_name}", when, minutes,
                   f"{title} w ramach oceny okresowej (arkusz {cycle.sheet})."),
        file_name=f"zaproszenie-{cycle.employee_id}-{stage}.ics", mime="text/calendar",
        key=f"inv_ics_{cycle.id}_{stage}",
    )


def _prep(state: DemoState, cycle, kind: str):
    emp = state.employee(cycle.employee_id)
    evaluator = state.employee(cycle.evaluator_id)
    notes = _notes(state, cycle)
    key = ("prep", kind, cycle.id, cycle.status.value, len(notes), state.today, tuple(cycle.scores.items()))
    return _cached(state, key, lambda: state.assistant.conversation_prep(
        cycle, emp, evaluator, notes, state.today, kind, cycle.absences))


def _render_prep(prep) -> None:
    ui.html(f"<p><b>Cel rozmowy:</b> {escape(prep.goal)} {ui.source_badge(prep.source)}</p>")
    if prep.plan_minutes:
        total = sum(m for _, m in prep.plan_minutes)
        ui.html("<p><b>Plan (" + str(total) + " min):</b> " + " → ".join(
            f"{escape(p)} <span class='lock'>{m}′</span>" for p, m in prep.plan_minutes) + "</p>")
    for c in prep.criteria:
        head = f"{c.name}{'' if c.mandatory else ' (dodatkowe)'} · +{c.positive} / −{c.negative}"
        with st.expander(head):
            if c.examples:
                ui.html("<b>Obserwacje:</b>" + ui.ul(f"{n.on:%d.%m.%Y}: {n.text}" for n in c.examples))
            if c.gaps:
                ui.html("<b>Brak obserwacji – zapytaj o:</b>" + ui.ul(c.gaps))
            if c.questions:
                ui.html("<b>Proponowane pytania:</b>" + ui.ul(c.questions))
    cols = st.columns(3)
    for col, title, items in zip(cols, ("Mocne strony", "Trudne tematy", "Działania rozwojowe"),
                                 (prep.strengths, prep.difficult_topics, prep.development)):
        with col:
            ui.card(title, ui.ul(items) or "<p class='lock'>brak</p>")


# ---------------------------------------------------------------- stage 1

def _slot_keys(cycle) -> list[str]:
    return [f"add_{cycle.id}_{i}" for i in range(3)]


def _chosen(cycle) -> list[str]:
    return [st.session_state[k] for k in _slot_keys(cycle) if st.session_state.get(k)]


def _put_in_free_slot(cycle, criterion_id: str) -> None:
    for k in _slot_keys(cycle):
        if not st.session_state.get(k):
            st.session_state[k] = criterion_id
            return


def _stage_criteria(state: DemoState, cycle, current: bool) -> None:
    rules = state.service.rules
    emp = state.employee(cycle.employee_id)
    editable = current and cycle.is_editable("additional_criteria")
    sheets = kprm.sheets()["arkusze"]

    st.markdown("#### Arkusz oceny")
    if editable:
        c1, c2 = st.columns([1, 2.2], vertical_alignment="bottom")
        new_sheet = c1.selectbox("Arkusz", list(sheets), index=list(sheets).index(cycle.sheet),
                                 format_func=lambda s: f"Arkusz {s}", key=f"sheet_{cycle.id}")
        c2.markdown(f"{escape(sheets[new_sheet]['opis'])}<br>"
                    f"<span class='lock'>Podpowiedź na podstawie stanowiska „{escape(emp.position)}”: "
                    f"arkusz {emp.sheet}. Możesz wybrać inny.</span>", unsafe_allow_html=True)
        if new_sheet != cycle.sheet:
            problems = change_sheet(state, cycle.id, new_sheet)
            if problems:
                ui.show_problems(problems)
            else:
                for k in _slot_keys(cycle):
                    if st.session_state.get(k) in rules.mandatory(new_sheet):
                        st.session_state[k] = None
                st.rerun()
    else:
        ui.html(f"<p>{ui.badge('Arkusz ' + cycle.sheet, 'b-blue')} {escape(sheets[cycle.sheet]['opis'])}</p>")

    st.markdown("#### Kryteria oceny")
    ui.card("Kryteria obowiązkowe (stałe dla arkusza)", ui.ul(_criteria_names(state, rules.mandatory(cycle.sheet))))
    st.markdown(f"**Kryteria dodatkowe** <span class='lock'>– najwyżej {rules.max_additional_criteria}, "
                "bez powtórzeń; puste pole = brak</span>", unsafe_allow_html=True)
    options = [c["id"] for c in kprm.optional_criteria(cycle.sheet)]
    keys = _slot_keys(cycle)[:rules.max_additional_criteria]
    for i, k in enumerate(keys):
        if k not in st.session_state:
            st.session_state[k] = cycle.additional_criteria[i] if i < len(cycle.additional_criteria) else None
    for i, k in enumerate(keys):
        taken = {st.session_state.get(o) for o in keys if o != k}
        opts = [None] + [o for o in options if o not in taken]
        if st.session_state.get(k) not in opts:
            st.session_state[k] = None
        st.selectbox(f"Kryterium dodatkowe {i + 1}", opts, key=k, disabled=not editable, placeholder="— brak —",
                     format_func=lambda c: "— brak —" if c is None else rules.criterion_name(c))
    if not editable:
        _locked()

    if editable:
        with st.expander("✨ Asystent: zaproponuj kryteria dodatkowe", expanded=not _chosen(cycle)):
            st.caption("Asystent dobiera kryteria dodatkowe pasujące do stanowiska i opisanych zadań, "
                       "z krótkim uzasadnieniem. To tylko propozycja – kryterium dodajesz sam przyciskiem „Dodaj”.")
            desc = st.text_area("Główne zadania na stanowisku (opcjonalnie – poprawia trafność)",
                                key=f"desc_{cycle.id}", height=70,
                                placeholder="np. obsługa interesantów, analizy, projekty unijne…")
            if st.button("Zaproponuj kryteria", key=f"sugg_{cycle.id}"):
                state.ai_cache.pop(repr(("crit", cycle.id, cycle.sheet, desc)), None)
                st.session_state[f"sugg_on_{cycle.id}"] = desc
            if f"sugg_on_{cycle.id}" in st.session_state:
                d = st.session_state[f"sugg_on_{cycle.id}"]
                sug = _cached(state, ("crit", cycle.id, cycle.sheet, d),
                              lambda: state.assistant.suggest_criteria(emp, cycle.sheet, d))
                ui.html(f"<p class='lock'>Źródło: {ui.source_badge(sug.source)} – to tylko propozycja.</p>")
                chosen = _chosen(cycle)
                for item in sug.items:
                    a, b = st.columns([4, 1], vertical_alignment="center")
                    a.markdown(f"**{item.name}** – {item.reason}")
                    b.button("Dodaj", key=f"addsug_{cycle.id}_{item.criterion_id}",
                             disabled=item.criterion_id in chosen or len(chosen) >= len(keys),
                             on_click=_put_in_free_slot, args=(cycle, item.criterion_id))

    st.markdown("#### Oczekiwania i cele na okres oceny")
    goals_key = f"goals_{cycle.id}"
    if goals_key not in st.session_state:
        st.session_state[goals_key] = "\n".join(cycle.goals)
    st.text_area("Jeden cel w wierszu", key=goals_key, height=90, disabled=not editable,
                 placeholder="np. Terminowe przygotowywanie opinii prawnych (14 dni)")

    st.markdown("#### Termin sporządzenia oceny")
    default_deadline = state.service.evaluation_deadline(cycle.id)
    override = cycle.deadline_override
    if editable:
        st.markdown(f"Termin: **{ui.fmt(default_deadline)}** <span class='lock'>"
                    + ("(ustalony przez oceniającego)" if override else
                       f"(wyliczony z przepisów: {rules.cycle_months} mies. od {ui.fmt(cycle.start_date)})")
                    + "</span>", unsafe_allow_html=True)
        with st.popover("📆 Zmień termin oceny"):
            new = st.date_input("Nowy termin sporządzenia oceny", default_deadline, key=f"ovr_{cycle.id}",
                                format="DD.MM.YYYY", min_value=state.today)
            a, b = st.columns(2)
            if a.button("Zapisz termin", type="primary", key=f"ovr_save_{cycle.id}", use_container_width=True):
                _, problems = safe(state.service.edit, cycle.id, cycle.evaluator_id, deadline_override=new)
                if problems:
                    ui.show_problems(problems)
                else:
                    st.toast(f"Nowy termin oceny: {ui.fmt(new)}")
                    st.rerun()
            if override and b.button("Przywróć wyliczony", key=f"ovr_reset_{cycle.id}", use_container_width=True):
                _, problems = safe(state.service.edit, cycle.id, cycle.evaluator_id, deadline_override=None)
                ui.show_problems(problems) if problems else st.rerun()
    else:
        st.markdown(f"**{ui.fmt(default_deadline)}**")
        _locked("Zmiana terminu po potwierdzeniu kryteriów – w trybie zmiany terminu oceny.")

    if current:
        with st.expander("📅 Zaproszenie na rozmowę rozpoczynającą"):
            _invite_block(state, cycle, 1, "Rozmowa rozpoczynająca ocenę okresową", 45)
        with st.expander("🗣️ Ściąga na rozmowę rozpoczynającą"):
            st.caption("Podpowiedź przed rozmową z pracownikiem: cel rozmowy, plan z czasem, a dla każdego kryterium "
                       "pytania i oczekiwania, które warto omówić. Na tej rozmowie ustalacie, czego oczekujesz "
                       "w okresie oceny – przepisy wymagają jej przy wyznaczaniu kryteriów (§ 5 rozporządzenia).")
            _render_prep(_prep(state, cycle, "ROZPOCZYNAJACA"))

    if not current:
        ui.html(f"<p class='lock'>Kryteria wyznaczone {ui.fmt(cycle.criteria_set_on)}, potwierdzone przez "
                f"ocenianego {ui.fmt(cycle.criteria_confirmed_on)}.</p>")
        return
    st.divider()
    if cycle.status is Status.CRITERIA_SET:
        st.info("⏳ Kryteria przekazane ocenianemu – czeka na potwierdzenie rozmowy i zapoznania się z kryteriami. "
                "Do tego czasu możesz je jeszcze poprawić.")
    label = "Zapisz zmiany i przekaż ponownie" if cycle.status is Status.CRITERIA_SET else \
        "Zatwierdź etap ✓ – przekaż ocenianemu do potwierdzenia"
    if st.button(label, type="primary", key=f"setcrit_{cycle.id}"):
        goals = [g for g in st.session_state[goals_key].splitlines() if g.strip()]
        _, problems = safe(state.service.set_criteria, cycle.id, cycle.evaluator_id,
                           _chosen(cycle), goals, override)
        if problems:
            ui.show_problems(problems)
        else:
            st.toast("Kryteria zapisane i przekazane ocenianemu.")
            st.rerun()


# ---------------------------------------------------------------- stage 2

def _note_form(state: DemoState, cycle, key: str) -> None:
    with st.form(key, clear_on_submit=True, border=False):
        text = st.text_area("Obserwacja", height=80, placeholder="Co się wydarzyło? Konkretne zachowanie i efekt.")
        c1, c2 = st.columns([1, 1])
        on = c1.date_input("Data", state.today, max_value=state.today, format="DD.MM.YYYY")
        c2.write("")
        submitted = c2.form_submit_button("Dodaj notatkę", type="primary", use_container_width=True)
    if submitted and text.strip():
        note = state.add_note(cycle.id, text, on, cycle.evaluator_id)
        emp = state.employee(cycle.employee_id)
        with st.spinner("Asystent przypisuje notatkę do kryterium…"):
            state.ai_cache[repr(("cls", note.id))] = state.assistant.classify_note(
                note, cycle.sheet, cycle.additional_criteria, [emp])
        st.toast("Notatka dodana.")
        st.rerun()


def _note_row(state: DemoState, cycle, note: Note, editable: bool) -> None:
    rules = state.service.rules
    tag = ""
    if note.criterion_id:
        cls, lab = ui.SENTIMENT.get(note.sentiment.value if note.sentiment else "", ("b-grey", "bez wydźwięku"))
        tag = ui.badge(rules.criterion_name(note.criterion_id), "b-blue") + " " + ui.badge(lab, cls)
    else:
        tag = ui.badge("do przypisania", "b-amber")
    ui.html(f'<div class="note"><span class="d">{note.on:%d.%m.%Y}</span> {tag}<br>{escape(note.text)}</div>')
    if not editable:
        return
    cls_result = None
    if not note.criterion_id:
        emp = state.employee(cycle.employee_id)
        cls_result = _cached(state, ("cls", note.id), lambda: state.assistant.classify_note(
            note, cycle.sheet, cycle.additional_criteria, [emp]))
    if not note.criterion_id and cls_result is not None and cls_result.suggestions:
        cols = st.columns(len(cls_result.suggestions[:3]) + 1)
        cols[0].caption(f"Propozycja {cls_result.source}:")
        for col, s in zip(cols[1:], cls_result.suggestions[:3]):
            sent = SENT_OPTS.get(s.sentiment.value, "") if s.sentiment else ""
            col.button(f"{s.criterion_name} {sent} ({int(s.confidence * 100)}%)", key=f"acc_{note.id}_{s.criterion_id}",
                       use_container_width=True,
                       on_click=state.tag_note, args=(cycle.id, note.id, s.criterion_id, s.sentiment, s.indicator))
    with st.popover("Przypisz / zmień", use_container_width=False):
        ids = cycle.criteria_ids(rules)
        crit = st.selectbox("Kryterium", ids, format_func=rules.criterion_name, key=f"mc_{note.id}",
                            index=ids.index(note.criterion_id) if note.criterion_id in ids else 0)
        sent = st.radio("Wydźwięk", list(SENT_OPTS), format_func=SENT_OPTS.get, horizontal=True, key=f"ms_{note.id}")
        a, b = st.columns(2)
        a.button("Zapisz", key=f"msave_{note.id}", type="primary", use_container_width=True,
                 on_click=state.tag_note, args=(cycle.id, note.id, crit, Sentiment(sent)))
        b.button("Usuń notatkę", key=f"mdel_{note.id}", use_container_width=True,
                 on_click=state.delete_note, args=(cycle.id, note.id))


def _stage_observation(state: DemoState, cycle, current: bool) -> None:
    rules = state.service.rules
    notes = sorted(_notes(state, cycle), key=lambda n: n.on, reverse=True)
    tab_notes, tab_crit, tab_period = st.tabs(["📝 Notatnik", "📊 Wg kryteriów", "📆 Zmiana okresu / nieobecności"])
    with tab_notes:
        st.caption("Zapisuj obserwacje przez cały okres oceny. Asystent proponuje kryterium – decydujesz Ty.")
        if current or state.stage(cycle) < DONE:
            _note_form(state, cycle, f"nf_{cycle.id}")
        if not notes:
            st.caption("Brak notatek.")
        for n in notes:
            _note_row(state, cycle, n, editable=state.stage(cycle) < DONE)
    with tab_crit:
        ev = evidence_by_criterion(notes, cycle.criteria_ids(rules))
        for cid, e in ev.items():
            bar = "🟩" * len(e.positive) + "⬜" * len(e.neutral) + "🟥" * len(e.negative)
            st.markdown(f"**{rules.criterion_name(cid)}** · +{len(e.positive)} / −{len(e.negative)} {bar}")
        untagged = [n for n in notes if not n.criterion_id]
        if untagged:
            st.warning(f"{len(untagged)} notatek bez kryterium – nie są brane pod uwagę.")
    with tab_period:
        deadline = state.service.evaluation_deadline(cycle.id)
        st.markdown(f"Aktualny termin oceny: **{ui.fmt(deadline)}**")
        st.caption(f"Usprawiedliwiona, ciągła nieobecność dłuższa niż {rules.absence_extends_after_months} mies. "
                   "przesuwa termin oceny o czas jej trwania.")
        for a in cycle.absences:
            st.markdown(f"- {ui.fmt(a.start)} – {ui.fmt(a.end)} · {a.kind or 'nieobecność'} ({a.days} dni)")
        if state.stage(cycle) < 5:
            with st.form(f"abs_{cycle.id}", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                start = c1.date_input("Od", state.today - timedelta(days=40), format="DD.MM.YYYY")
                end = c2.date_input("Do", state.today - timedelta(days=5), format="DD.MM.YYYY")
                kind = c3.selectbox("Rodzaj", ["zwolnienie lekarskie", "urlop wypoczynkowy", "urlop rodzicielski",
                                               "inna usprawiedliwiona"])
                if st.form_submit_button("Dodaj nieobecność"):
                    try:
                        absence = Absence(start, end, kind)
                    except Exception as e:  # ValidationError for end < start
                        ui.show_problems(getattr(e, "problems", [str(e)]))
                    else:
                        new, problems = safe(state.service.register_absence, cycle.id, absence)
                        if problems:
                            ui.show_problems(problems)
                        else:
                            st.toast(f"Termin oceny: {ui.fmt(new)}")
                            st.rerun()
    if current:
        st.divider()
        if st.button("Zatwierdź etap ✓ – przejdź do przygotowania rozmowy oceniającej", type="primary",
                     key=f"obs_done_{cycle.id}"):
            state.review_started.add(cycle.id)
            st.session_state[f"sel_{cycle.id}"] = 3
            st.rerun()


# ---------------------------------------------------------------- stage 3

def _stage_review(state: DemoState, cycle, current: bool) -> None:
    if current:
        with st.expander("📅 Zaproszenie na rozmowę oceniającą", expanded=(cycle.id, 3) not in state.invites):
            _invite_block(state, cycle, 3, "Rozmowa oceniająca", 60)
    st.markdown("#### Przygotowanie do rozmowy")
    _render_prep(_prep(state, cycle, "OCENIAJACA"))
    st.markdown("#### Odbycie rozmowy")
    if not current:
        ui.html(f"<p>Rozmowa odbyła się <b>{ui.fmt(cycle.meeting_date)}</b>; okres oceny "
                f"{ui.fmt(cycle.period_from)} – {ui.fmt(cycle.period_to)}.</p>")
        _locked()
        return
    planned = state.invites.get((cycle.id, 3))
    c1, c2, c3 = st.columns(3)
    meeting = c1.date_input("Data rozmowy oceniającej", min(planned.date(), state.today) if planned else state.today,
                            max_value=state.today, format="DD.MM.YYYY", key=f"md_{cycle.id}")
    pf = c2.date_input("Okres oceny od", cycle.criteria_set_on or cycle.start_date, format="DD.MM.YYYY",
                       key=f"pf_{cycle.id}")
    pt = c3.date_input("Okres oceny do", meeting, format="DD.MM.YYYY", key=f"pt_{cycle.id}")
    a, b = st.columns([2, 1])
    if a.button("Zatwierdź etap ✓ – rozmowa odbyta, przejdź do arkusza", type="primary", key=f"rev_{cycle.id}"):
        _, problems = safe(state.service.record_review_meeting, cycle.id, cycle.evaluator_id, meeting, pf, pt)
        if problems:
            ui.show_problems(problems)
        else:
            st.session_state[f"sel_{cycle.id}"] = 4
            st.rerun()
    if b.button("← Wróć do obserwacji", key=f"back_obs_{cycle.id}"):
        state.review_started.discard(cycle.id)
        st.session_state[f"sel_{cycle.id}"] = 2
        st.rerun()


# ---------------------------------------------------------------- stage 4

def _live_result(state: DemoState, cycle, scores: dict):
    ids = cycle.criteria_ids(state.service.rules)
    if all(scores.get(c) for c in ids):
        return compute_result([scores[c] for c in ids], state.service.rules)
    return None


def _result_box(result, rules, partial: int, total: int) -> None:
    if result is None:
        ui.html(f'<div class="result pending">Oceniono {partial} z {total} kryteriów – średnia i ocena pojawią się '
                'po uzupełnieniu wszystkich.</div>')
        return
    cls = "pos" if result.outcome is Outcome.POSITIVE else "neg"
    avg = f"{result.average_display:.2f}".replace(".", ",")
    ui.html(f'<div class="result {cls}">Średnia <b>{avg}</b> · poziom <b>{escape(result.level)}</b> · '
            f'ocena <b>{result.outcome.value.upper()}</b></div>')


def _stage_sheet(state: DemoState, cycle, current: bool) -> None:
    rules = state.service.rules
    emp = state.employee(cycle.employee_id)
    evaluator = state.employee(cycle.evaluator_id)
    ids = cycle.criteria_ids(rules)
    editable = current and cycle.is_editable("scores")
    notes = _notes(state, cycle)
    ev = evidence_by_criterion(notes, ids)

    with st.expander("Część I – dane z systemu (uzupełnione automatycznie)"):
        ui.html(ui.kv([("Urząd", emp.office), ("Oceniany", f"{emp.full_name}, {emp.position}, {emp.unit}"),
                       ("Oceniający", f"{evaluator.full_name}, {evaluator.position}" if evaluator else "—"),
                       ("Kryteria wyznaczone", ui.fmt(cycle.criteria_set_on)),
                       ("Rozmowa oceniająca", ui.fmt(cycle.meeting_date)),
                       ("Okres oceny", f"{ui.fmt(cycle.period_from)} – {ui.fmt(cycle.period_to)}")]))

    st.markdown("#### Oceny cząstkowe")
    points = sorted(rules.scale)
    ui.html("<p class='lock'>" + " · ".join(f"<b>{p}</b> {escape(rules.scale[p])}" for p in points) + "</p>")
    scores: dict[str, int] = {}
    for cid in ids:
        key = f"sc_{cycle.id}_{cid}"
        if key not in st.session_state and cid in cycle.scores:
            st.session_state[key] = cycle.scores[cid]
        e = ev[cid]
        c1, c2 = st.columns([1.4, 1.6], vertical_alignment="center")
        mand = cid in rules.mandatory(cycle.sheet)
        c1.markdown(f"**{rules.criterion_name(cid)}**{'' if mand else ' · dodatkowe'}<br>"
                    f"<span class='lock'>notatki: +{len(e.positive)} / −{len(e.negative)}</span>",
                    unsafe_allow_html=True)
        with c2:
            val = st.segmented_control(rules.criterion_name(cid), points, key=key, format_func=str,
                                       label_visibility="collapsed", disabled=not editable)
            st.caption(rules.scale[val] if val is not None else "nie oceniono")
        if val is not None:
            scores[cid] = val
    result = cycle.result or _live_result(state, cycle, scores)
    _result_box(result, rules, len(scores), len(ids))
    if any(v == rules.forbidden_partial_score for v in scores.values()):
        st.warning(f"Ocena cząstkowa „{rules.scale[rules.forbidden_partial_score]}” oznacza ocenę NEGATYWNĄ "
                   "niezależnie od średniej (§ 11 rozporządzenia).")

    def draft_into(kind: str, target_key: str) -> None:
        # the draft uses the current scores, so save them as a draft first
        safe(state.service.edit, cycle.id, cycle.evaluator_id, scores=scores)
        fresh = state.cycle(cycle.id)
        d = state.assistant.draft(kind, fresh, emp, notes)
        st.session_state[target_key] = d.text
        st.session_state[f"src_{target_key}"] = d.source

    negative = (result is not None and result.outcome is Outcome.NEGATIVE) or \
        rules.forbidden_partial_score in scores.values()
    for kind, field, title, required in (
        ("UZASADNIENIE", "justification", "Uzasadnienie oceny", negative),
        ("IPRZ", "iprz_conclusions", "Wnioski dotyczące indywidualnego programu rozwoju zawodowego", True),
    ):
        key = f"{field}_{cycle.id}"
        if key not in st.session_state:
            st.session_state[key] = getattr(cycle, field)
        h, btn = st.columns([3, 1])
        src = st.session_state.get(f"src_{key}")
        h.markdown(f"#### {title} {'*' if required else '(opcjonalne)'} "
                   + (ui.source_badge(src) if src else ""), unsafe_allow_html=True)
        if editable:
            btn.button("✨ Szkic asystenta", key=f"dr_{key}", use_container_width=True,
                       on_click=draft_into, args=(kind, key))
        st.text_area(title, key=key, height=150, disabled=not editable, label_visibility="collapsed")
    if editable and negative and not st.session_state[f"justification_{cycle.id}"].strip():
        st.error("Ocena jest negatywna – uzasadnienie jest obowiązkowe. Bez niego nie można zatwierdzić oceny.")

    st.markdown("#### Część III – wniosek o kolejny stopień służbowy")
    gr = state.grade_request.setdefault(cycle.id, {"official": False, "attach": False, "text": ""})
    gr["official"] = st.toggle("Oceniany jest urzędnikiem służby cywilnej (mianowanym)", value=gr["official"],
                               key=f"off_{cycle.id}", disabled=not editable)
    if gr["official"]:
        if result is not None and result.outcome is Outcome.POSITIVE:
            gr["attach"] = st.checkbox("Dołączam umotywowany wniosek o przyznanie kolejnego stopnia służbowego",
                                       value=gr["attach"], key=f"att_{cycle.id}", disabled=not editable)
            if gr["attach"]:
                tkey = f"grade_{cycle.id}"
                if tkey not in st.session_state:
                    st.session_state[tkey] = gr["text"]
                if editable:
                    st.button("✨ Szkic uzasadnienia wniosku", key=f"dr_{tkey}",
                              on_click=draft_into, args=("UMOTYWOWANIE_STOPNIA", tkey))
                gr["text"] = st.text_area("Umotywowanie wniosku", key=tkey, height=110, disabled=not editable)
        else:
            gr["attach"] = False
            st.caption("Wniosek można dołączyć tylko do oceny pozytywnej.")
    else:
        st.caption("Nie dotyczy – część III wypełnia się tylko dla urzędników służby cywilnej.")

    if editable:
        st.divider()
        a, b, _ = st.columns([1.6, 1, 1.4])
        payload = dict(scores=scores, justification=st.session_state[f"justification_{cycle.id}"],
                       iprz_conclusions=st.session_state[f"iprz_conclusions_{cycle.id}"])
        if b.button("Zapisz szkic", key=f"save_{cycle.id}", use_container_width=True):
            _, problems = safe(state.service.edit, cycle.id, cycle.evaluator_id, **payload)
            ui.show_problems(problems) if problems else st.toast("Szkic zapisany.")
        if a.button("Zatwierdź ocenę ✓ – przekaż do zapoznania", type="primary", key=f"submit_{cycle.id}",
                    use_container_width=True):
            _, problems = safe(state.service.submit_evaluation, cycle.id, cycle.evaluator_id, **payload)
            if problems:
                ui.show_problems(problems)
            else:
                st.session_state[f"sel_{cycle.id}"] = 5
                st.rerun()
    elif not current:
        _locked()
    _export(state, cycle)


def _export(state: DemoState, cycle) -> None:
    emp = state.employee(cycle.employee_id)
    doc = sheet_html(state.cycle(cycle.id), emp, state.employee(cycle.evaluator_id), state.service.rules,
                     state.service.evaluation_deadline(cycle.id), state.grade_request.get(cycle.id))
    st.download_button("🖨️ Pobierz arkusz do druku / PDF", doc.encode("utf-8"),
                       file_name=f"arkusz-{cycle.sheet}-{cycle.employee_id}.html", mime="text/html",
                       key=f"exp_{cycle.id}_{state.stage(cycle)}")


# ---------------------------------------------------------------- stage 5

def _stage_ack(state: DemoState, cycle, current: bool) -> None:
    rules = state.service.rules
    if cycle.result:
        _result_box(cycle.result, rules, 0, 0)
    if cycle.status is Status.EVALUATION_DONE:
        st.info(f"⏳ Ocena sporządzona {ui.fmt(cycle.evaluated_on)} i przekazana ocenianemu – czeka na potwierdzenie "
                "zapoznania się z oceną.")
    else:
        objection = state.service.objection_deadline(cycle.id)
        st.success(f"✔ Oceniany zapoznał się z oceną {ui.fmt(cycle.acknowledged_on)}.")
        if objection:
            st.markdown(f"Termin na sprzeciw do dyrektora generalnego: **{ui.fmt(objection)}** "
                        f"({ui.days_text((objection - state.today).days)}).")
        due = cycle.next_evaluation_due(rules)
        if due:
            st.warning(f"Po ocenie negatywnej ponowna ocena: {ui.fmt(due)}.")
    _export(state, cycle)


STAGE_RENDER = {1: _stage_criteria, 2: _stage_observation, 3: _stage_review, 4: _stage_sheet, 5: _stage_ack}


# ---------------------------------------------------------------- side panel

def _summary(state: DemoState, cycle) -> None:
    rules = state.service.rules
    emp = state.employee(cycle.employee_id)
    result = cycle.result
    if result is None:
        scores = {c: v for c, v in cycle.scores.items() if v}
        result = _live_result(state, cycle, scores)
    prev = cycle.previous_evaluation or emp.previous_evaluation
    rows = [("Arkusz", f"{cycle.sheet} · {len(rules.mandatory(cycle.sheet))} obowiązkowych + "
                       f"{len(cycle.additional_criteria)} dodatkowe"),
            ("Etap", ui.stage_label(state.stage(cycle))),
            ("Termin oceny", ui.fmt(state.service.evaluation_deadline(cycle.id))),
            ("Notatki", str(len(_notes(state, cycle)))),
            ("Poprzednia", f"{prev.outcome}, {ui.fmt(prev.date)}" if prev and prev.outcome else "brak")]
    with st.container(border=True):
        st.markdown("**Ocena w skrócie**")
        if result is None:
            ui.html('<div class="result pending">w trakcie</div>')
        else:
            cls = "pos" if result.outcome is Outcome.POSITIVE else "neg"
            avg = f"{result.average_display:.2f}".replace(".", ",")
            label = "" if cycle.result else " (wstępnie)"
            ui.html(f'<div class="result {cls}"><b>{result.outcome.value.upper()}</b>{label}<br>'
                    f'średnia {avg} · {escape(result.level)}</div>')
        ui.html(ui.kv(rows))


def _hr_partner(state: DemoState, cycle) -> None:
    emp = state.employee(cycle.employee_id)
    notes = _notes(state, cycle)
    key = ("hr", cycle.id, len(notes), tuple((n.id, n.criterion_id) for n in notes), len(cycle.absences),
           state.today, cycle.result is not None)
    report = _cached(state, key, lambda: state.assistant.hr_partner(cycle, emp, notes, cycle.absences, state.today))
    tones = {"PRZECIAZENIE": ("⚠️ Przeciążenie", "c-amber"), "DLUGA_NIEOBECNOSC": ("🏥 Długa nieobecność", "c-blue"),
             "ZMIANA_OBOWIAZKOW": ("🔄 Zmiana obowiązków", "c-blue"), "SPADEK_OCEN": ("📉 Spadek ocen", "c-red"),
             "DO_DOCENIENIA": ("👏 Warto docenić", "c-green")}
    with st.container(border=True):
        ui.html(f"<b>🤝 HR partner</b> {ui.source_badge(report.source)}<br>"
                "<span class='lock'>Propozycje na podstawie notatek, nieobecności i oceny. "
                "AI tylko proponuje – decyzja należy do Ciebie.</span>")
        shown = [s for s in report.signals if f"{cycle.id}:{s.kind}" not in state.dismissed]
        if not shown:
            st.caption("Brak sygnałów wymagających uwagi.")
        for s in shown:
            title, tone = tones.get(s.kind, ("💡 " + s.kind, "c-blue"))
            body = f"<p>{escape(s.description)}</p>" + ("<b>Co możesz zrobić:</b>" + ui.ul(s.recommendations)
                                                        if s.recommendations else "")
            ui.card(title, body, tone)
            with st.expander("Na podstawie"):
                ui.html(ui.ul(s.evidence))
            st.button("Oznacz jako omówione", key=f"dis_{cycle.id}_{s.kind}", use_container_width=True,
                      on_click=state.dismissed.add, args=(f"{cycle.id}:{s.kind}",))


# ---------------------------------------------------------------- page

def render(state: DemoState, employee_id: str) -> None:
    people = state.evaluated()
    ids = [e.id for e in people]
    top1, top2, _ = st.columns([1, 1.6, 2.4])
    if top1.button("← Widok 2: Mój zespół", use_container_width=True):
        st.session_state.view = "team"
        st.rerun()
    chosen = top2.selectbox("Pracownik", ids, index=ids.index(employee_id) if employee_id in ids else 0,
                            format_func=lambda i: f"{state.employee(i).full_name} – {state.employee(i).position}",
                            label_visibility="collapsed")
    if chosen != employee_id:
        open_evaluation(chosen)
        st.rerun()

    emp = state.employee(employee_id)
    cycle = state.cycle_for(employee_id)
    if cycle is None:
        st.info(f"{emp.full_name} nie ma otwartego cyklu oceny.")
        if st.button("Rozpocznij cykl oceny", type="primary"):
            _, problems = safe(state.service.start_cycle, employee_id)
            ui.show_problems(problems) if problems else st.rerun()
        return

    sel_key = f"sel_{cycle.id}"
    current = state.stage(cycle)
    seen_key = f"seen_{cycle.id}"
    if sel_key not in st.session_state or st.session_state.get(seen_key) != current:
        # default: the stage the process is at now (also after it moved on, e.g. the employee confirmed)
        st.session_state[sel_key] = min(current, len(STAGES))
        st.session_state[seen_key] = current
    st.markdown(f"### {emp.full_name} <span class='lock'>· {escape(emp.position)} · {escape(emp.unit)}</span>",
                unsafe_allow_html=True)
    selected = ui.stepper(state, cycle, st.session_state[sel_key], sel_key)
    label, due = state.deadline_hint(cycle)
    ui.deadline_bar(label, due, state.today)

    main, side = st.columns([2.6, 1.25], gap="large")
    with main:
        with st.container(border=True):
            st.markdown(f"### Etap {selected}: {STAGES[selected - 1]}")
            if selected > current:
                st.info("Ten etap jeszcze się nie rozpoczął – najpierw zatwierdź poprzednie.")
                if selected == 2 and current == 1:
                    st.caption("Notatki możesz dodawać już teraz – przycisk „+ Notatka” w panelu obok.")
            else:
                STAGE_RENDER[selected](state, cycle, current=(selected == current))
    with side:
        if current < DONE:
            with st.popover("➕ Notatka", use_container_width=True):
                _note_form(state, cycle, f"qnf_{cycle.id}")
        _summary(state, cycle)
        _hr_partner(state, cycle)
    if cycle.status is Status.ACKNOWLEDGED:
        if st.button("Rozpocznij kolejny cykl oceny"):
            _, problems = safe(state.service.start_cycle, employee_id)
            ui.show_problems(problems) if problems else st.rerun()
