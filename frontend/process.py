"""How the UI presents the process that the server runs: 5 stages over the API statuses, Polish labels.
No rules here – statuses, dates, results and allowed actions all come from the API responses."""
from __future__ import annotations

from datetime import date, datetime

STAGES = (
    "Rozmowa inicjująca",
    "Ocenianie",
    "Rozmowa oceniająca",
    "Arkusz",
    "Zapoznanie i podpis",
)
DONE = len(STAGES) + 1

# API status -> UI stage (OKRES_OCENY covers observation and preparing the review meeting)
STAGE_OF_STATUS = {
    "KRYTERIA_DO_WYZNACZENIA": 1,
    "KRYTERIA_DO_POTWIERDZENIA": 1,
    "OKRES_OCENY": 2,
    "ROZMOWA_OCENIAJACA": 4,
    "OCENA_DO_ZAPOZNANIA": 5,
    "ZAKONCZONA": DONE,
    "SPRZECIW": 5,  # objection: the evaluation waits for the director general's decision
    "ANULOWANA": DONE,
}
WAITING_FOR_EMPLOYEE = {"KRYTERIA_DO_POTWIERDZENIA", "OCENA_DO_ZAPOZNANIA"}
WAITING_FOR_REVIEWER = {"SPRZECIW"}

STATUS_LABEL = {
    "KRYTERIA_DO_WYZNACZENIA": "Wyznaczenie kryteriów",
    "KRYTERIA_DO_POTWIERDZENIA": "Czeka na potwierdzenie kryteriów",
    "OKRES_OCENY": "Okres oceny",
    "ROZMOWA_OCENIAJACA": "Sporządzenie oceny",
    "OCENA_DO_ZAPOZNANIA": "Czeka na zapoznanie się z oceną",
    "ZAKONCZONA": "Zakończona",
    "SPRZECIW": "Sprzeciw – czeka na rozstrzygnięcie",
    "ANULOWANA": "Anulowana",
}
LEVEL_LABEL = {
    "ZNACZNIE_PONIZEJ": "znacznie poniżej oczekiwań",
    "PONIZEJ": "poniżej oczekiwań",
    "NA_POZIOMIE": "na poziomie oczekiwań",
    "POWYZEJ": "powyżej oczekiwań",
    "ZNACZNIE_POWYZEJ": "znacznie powyżej oczekiwań",
}
SCALE_LABEL = {1: "znacznie poniżej oczekiwań", 3: "poniżej oczekiwań", 5: "na poziomie oczekiwań",
               7: "powyżej oczekiwań", 9: "znacznie powyżej oczekiwań"}
ACTION_LABEL = {
    "ZATWIERDZ_KRYTERIA": "Zatwierdź kryteria i przekaż ocenianemu",
    "POTWIERDZ_KRYTERIA": "Potwierdzam rozmowę i zapoznanie się z kryteriami",
    "ROZPOCZNIJ_ROZMOWE": "Rozmowa oceniająca odbyta – przejdź do arkusza",
    "ZATWIERDZ_OCENE": "Zatwierdź ocenę i przekaż do zapoznania",
    "POTWIERDZ_ZAPOZNANIE": "Potwierdzam zapoznanie się z oceną",
    "FIKCJA_ZAPOZNANIA": "Stwierdź fikcję zapoznania",
    "ZLOZ_SPRZECIW": "Złóż sprzeciw",
    "ROZPATRZ_SPRZECIW": "Rozstrzygnij sprzeciw",
}
ACTION_DONE = {
    "ZATWIERDZ_KRYTERIA": "Kryteria zatwierdzone i przekazane ocenianemu.",
    "POTWIERDZ_KRYTERIA": "Potwierdzono rozmowę i kryteria.",
    "ROZPOCZNIJ_ROZMOWE": "Zapisano rozmowę oceniającą – można wypełnić arkusz.",
    "ZATWIERDZ_OCENE": "Ocena zatwierdzona i przekazana ocenianemu.",
    "POTWIERDZ_ZAPOZNANIE": "Potwierdzono zapoznanie się z oceną.",
    "ZLOZ_SPRZECIW": "Sprzeciw złożony – rozstrzygnie go dyrektor generalny.",
    "ROZPATRZ_SPRZECIW": "Zapisano rozstrzygnięcie sprzeciwu.",
}
WHO_LABEL = {"OCENIAJACY": "oceniający", "OCENIANY": "oceniany", "KADRY": "kadry", "NIKT": "–"}
EMPLOYMENT_LABEL = {"PRACOWNIK": "Pracownik służby cywilnej", "URZEDNIK": "Urzędnik służby cywilnej"}
SIGNAL_LABEL = {
    "PRZECIAZENIE": (":material/warning: Możliwe przeciążenie", "c-amber"),
    "DLUGA_NIEOBECNOSC": (":material/medical_services: Długa nieobecność", "c-blue"),
    "ZMIANA_OBOWIAZKOW": (":material/sync: Zmiana zakresu obowiązków", "c-blue"),
    "SPADEK_OCEN": (":material/trending_down: Wynik niższy niż poprzednio", "c-red"),
    "DO_DOCENIENIA": (":material/celebration: Warto docenić", "c-green"),
}
SENTIMENTS = {"POZYTYWNY": "+ pozytywna", "NEUTRALNY": "neutralna", "NEGATYWNY": "− negatywna"}


def to_date(value) -> date | None:
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def name(person: dict | None) -> str:
    return f"{person['imie']} {person['nazwisko']}" if person else "—"


def current_stage(ev: dict) -> int:
    return STAGE_OF_STATUS.get(ev["status"], 1)


def stage_state(ev: dict, stage: int) -> tuple[str, str]:
    """(state, label): done / active / waiting / todo."""
    cur = current_stage(ev)
    status = ev["status"]
    if status == "OKRES_OCENY" and stage == 3:  # the review meeting is prepared during the evaluation period
        return "active", "przygotowanie"
    if stage < cur:
        return "done", "zakończony"
    if stage > cur:
        return "todo", "oczekuje"
    if status in WAITING_FOR_EMPLOYEE:
        return "waiting", "czeka na ocenianego"
    if status in WAITING_FOR_REVIEWER:
        return "waiting", "sprzeciw – czeka na decyzję"
    return "active", "w trakcie"


def stage_date(ev: dict, stage: int) -> str:
    """When a stage was closed (from the server's signatures/dates), else the deadline it runs against."""
    c1, c2 = ev["czesc_i"], ev["czesc_ii"]
    state, _ = stage_state(ev, stage)
    fmt = lambda v: to_date(v).strftime("%d.%m.%Y") if v else ""  # noqa: E731
    if stage == 1:
        if state == "done":
            return fmt(c1["potw_oceniany"].get("at") or c1["potw_oceniajacy"].get("at"))
        return f"termin {fmt(c1['termin_wyznaczenia_kryteriow'])}"
    if stage == 2:
        start = c1["potw_oceniany"].get("at") or c1.get("data_wyznaczenia_kryteriow")
        if state == "done":
            return f"{fmt(start)} – {fmt(c2.get('data_rozmowy_oceniajacej'))}" if start else ""
        return f"od {fmt(start)}" if start else ""
    if stage == 3:
        if state == "done":
            return fmt(c2.get("data_rozmowy_oceniajacej"))
        return f"do {fmt(c1['termin_oceny'])}"
    if stage == 4:
        if state == "done":
            return fmt(c2.get("data_sporzadzenia"))
        return f"do {fmt(c1['termin_oceny'])}"
    if state == "done":
        return fmt(c2.get("zapoznanie", {}).get("at"))
    return ""
