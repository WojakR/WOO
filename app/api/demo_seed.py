"""Demo scenario for the running app: evaluations at every stage of the process (all people are fictional).

Grzegorz Wzór (sheet C, evaluator Henryk Pryncypał) is at the review meeting: scores entered, justification
and IPRZ conclusions still missing, the team's 30 hand-tagged test notes (server/data/kprm/notatki_testowe.json)
spread over the period plus four untagged notes the HR partner rules react to (overtime, new duties).

History for the personalised hints (app/domain/career_profile.py), as if from the HR system: Grzegorz – 11 years
in the office and every evaluation lower than the one before; Monika Testowa – 9 years, the same level twice;
Agata Wzorcowa – a new employee.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

from app.domain.cycle import PreviousEvaluation
from app.domain.notes import Note, Sentiment
from backend import config

if TYPE_CHECKING:
    from .state import DemoState

_EXTRA_NOTES = [
    (date(2026, 4, 14), "Został po godzinach, żeby dokończyć pilny przekład umowy na następny dzień."),
    (date(2026, 5, 4), "Od maja przejął dodatkowe zadania: korespondencję z interesantami po odejściu koleżanki."),
    (date(2026, 5, 6), "Znowu pracował po godzinach przy zaległych tłumaczeniach."),
    (date(2026, 5, 19), "Mówił, że nie wyrabia się z terminami i pracuje w weekend."),
]


def _test_notes(author: str) -> list[Note]:
    raw = json.loads((config.KPRM_DATA_DIR / "notatki_testowe.json").read_text(encoding="utf-8"))
    start = date(2024, 7, 15).toordinal()
    notes = [
        Note("", date.fromordinal(start + i * 21), n["tresc"], author, n.get("kryterium"),
             Sentiment(n["wydzwiek"]) if n.get("wydzwiek") else None)
        for i, n in enumerate(raw["notatki"])
    ]
    return notes + [Note("", d, text, author) for d, text in _EXTRA_NOTES]


_HISTORY = {  # employee id -> (employment start, evaluations before the previous one)
    "grzegorz.wzor": (date(2015, 3, 2), (PreviousEvaluation("pozytywna", "powyżej oczekiwań", date(2022, 6, 10)),)),
    "monika.testowa": (date(2017, 2, 1), (PreviousEvaluation("pozytywna", "na poziomie oczekiwań", date(2022, 5, 25)),)),
    "agata.wzorcowa": (date(2025, 12, 1), ()),
}


def _seed_history(st: DemoState) -> None:
    people = [st.directory.get(pid) for pid in _HISTORY]
    st.import_employees([replace(e, employment_start=_HISTORY[e.id][0], earlier_evaluations=_HISTORY[e.id][1])
                         for e in people if e is not None])


def seed_scenario(st: DemoState) -> None:
    s, r, clock = st.evaluations, st.evaluations.rules, st.clock
    today = clock.today()
    _seed_history(st)

    def scores(cycle_id: str, values: list[int]) -> dict[str, int]:
        ids = s.cycles.get(cycle_id).criteria_ids(r)
        return dict(zip(ids, values, strict=True))

    # Grzegorz Wzór (C) – the demo: review meeting held, scores entered, justification missing
    clock.set(date(2024, 6, 12))
    g = s.start_cycle("grzegorz.wzor")
    clock.set(date(2024, 6, 14))
    s.set_criteria(g.id, "henryk.pryncypal", ["orientacja_na_klienta", "kreatywnosc"],
                   goals=["Terminowe przekłady bez poprawek merytorycznych", "Jasna korespondencja z interesantami"])
    clock.set(date(2024, 6, 17))
    s.confirm_criteria(g.id, "grzegorz.wzor")
    clock.set(date(2026, 5, 22))
    s.record_review_meeting(g.id, "henryk.pryncypal", period_from=date(2024, 6, 14), period_to=date(2026, 6, 12))
    s.edit(g.id, "henryk.pryncypal", scores=scores(g.id, [3, 5, 3, 3, 5, 5, 3]))
    for note in _test_notes("henryk.pryncypal"):
        st.add_note(int(g.id), note)

    # Adam Wzór (C) – negative evaluation waiting for the employee's acknowledgement
    clock.set(date(2024, 5, 20))
    a = s.start_cycle("adam.wzor")
    clock.set(date(2024, 6, 3))
    s.set_criteria(a.id, "bartlomiej.przelozony", ["myslenie_analityczne"])
    s.confirm_criteria(a.id, "adam.wzor")
    clock.set(date(2026, 5, 15))
    s.record_review_meeting(a.id, "bartlomiej.przelozony")
    s.submit_evaluation(a.id, "bartlomiej.przelozony", scores(a.id, [3, 3, 3, 5, 3, 3]),
                        justification="Powtarzające się opóźnienia w realizacji zadań i błędy w raportach.",
                        iprz_conclusions="Szkolenie z planowania pracy; comiesięczny przegląd zadań z przełożonym.")

    # Ewelina Próbka (C) – finished, positive
    clock.set(date(2024, 4, 15))
    e = s.start_cycle("ewelina.probka")
    clock.set(date(2024, 4, 29))
    s.set_criteria(e.id, "franciszek.szef")
    s.confirm_criteria(e.id, "ewelina.probka")
    clock.set(date(2026, 4, 10))
    s.record_review_meeting(e.id, "franciszek.szef")
    s.submit_evaluation(e.id, "franciszek.szef", scores(e.id, [7, 7, 7, 7, 7]),
                        iprz_conclusions="Kurs z walidacji metod badawczych; udział w audycie wewnętrznym.")
    clock.set(date(2026, 4, 14))
    s.acknowledge(e.id, "ewelina.probka")

    # Janina Kowalska (A) – review meeting started, deadline already missed
    clock.set(date(2024, 5, 6))
    k = s.start_cycle("janina.kowalska")
    clock.set(date(2024, 5, 27))
    s.set_criteria(k.id, "adam.nowak", ["negocjowanie"])
    s.confirm_criteria(k.id, "janina.kowalska")
    clock.set(date(2026, 4, 28))
    s.record_review_meeting(k.id, "adam.nowak")

    # Janina Nowak (B) – evaluation period running
    clock.set(date(2024, 10, 2))
    n = s.start_cycle("janina.nowak")
    clock.set(date(2024, 10, 21))
    s.set_criteria(n.id, "romuald.gut", ["zarzadzanie_strategiczne"])
    s.confirm_criteria(n.id, "janina.nowak")

    # Adam Kowalik (C) – criteria set, waiting for the employee's confirmation
    clock.set(date(2026, 5, 5))
    ak = s.start_cycle("adam.kowalik", start_date=date(2026, 5, 5))
    clock.set(date(2026, 5, 20))
    s.set_criteria(ak.id, "miranda.wasik", ["orientacja_na_klienta"])

    # Celina Przykładowa (C) – new cycle, criteria still to be set
    clock.set(date(2026, 5, 4))
    s.start_cycle("celina.przykladowa", start_date=date(2026, 5, 4))

    # Barbara Przełożona's team – four people at the very start of the process (criteria still to be set),
    # so one evaluator has several evaluations to try the whole process on
    for person, start in (("tomasz.probny", date(2026, 5, 18)), ("agata.wzorcowa", date(2026, 5, 11)),
                          ("piotr.przykladny", date(2026, 4, 28)), ("monika.testowa", date(2026, 5, 20))):
        clock.set(start)
        s.start_cycle(person, start_date=start)

    # Roman Kowal – no cycle yet ("nierozpoczęte")
    clock.set(today)
