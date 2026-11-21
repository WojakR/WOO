"""Front <-> back contract (Pydantic v2). Source of truth for the OpenAPI the frontend consumes.

Field names follow the data model (docs: model-danych.md) so the API maps 1:1 onto entities.
Rules the frontend must NOT re-implement come back from the server:
  - computed values (srednia, poziom, wynik, terminy, stopien_obligatoryjny),
  - what the current user may do (dozwolone_akcje) and edit (edytowalne_pola),
  - validation problems (walidacje) – blocking or warning.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- enums (model-danych.md)

class TypZatrudnienia(str, Enum):
    URZEDNIK = "URZEDNIK"
    PRACOWNIK = "PRACOWNIK"


class Arkusz(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Rola(str, Enum):
    PRACOWNIK = "PRACOWNIK"
    KADRY = "KADRY"
    DYREKTOR_GENERALNY = "DYREKTOR_GENERALNY"
    ADMIN = "ADMIN"


class StatusOceny(str, Enum):
    KRYTERIA_DO_WYZNACZENIA = "KRYTERIA_DO_WYZNACZENIA"
    KRYTERIA_DO_POTWIERDZENIA = "KRYTERIA_DO_POTWIERDZENIA"
    OKRES_OCENY = "OKRES_OCENY"
    ROZMOWA_OCENIAJACA = "ROZMOWA_OCENIAJACA"
    OCENA_DO_ZAPOZNANIA = "OCENA_DO_ZAPOZNANIA"
    ZAKONCZONA = "ZAKONCZONA"
    SPRZECIW = "SPRZECIW"
    ANULOWANA = "ANULOWANA"


Punkty = Literal[1, 3, 5, 7, 9]


class Poziom(str, Enum):
    ZNACZNIE_PONIZEJ = "ZNACZNIE_PONIZEJ"
    PONIZEJ = "PONIZEJ"
    NA_POZIOMIE = "NA_POZIOMIE"
    POWYZEJ = "POWYZEJ"
    ZNACZNIE_POWYZEJ = "ZNACZNIE_POWYZEJ"


class Wynik(str, Enum):
    POZYTYWNA = "POZYTYWNA"
    NEGATYWNA = "NEGATYWNA"


class WniosekOStopien(str, Enum):
    TAK = "TAK"
    NIE = "NIE"
    NIE_DOTYCZY = "NIE_DOTYCZY"


class TypKryterium(str, Enum):
    OBOWIAZKOWE = "OBOWIAZKOWE"
    DODATKOWE = "DODATKOWE"


class TypNieobecnosci(str, Enum):
    L4 = "L4"
    URLOP_WYPOCZYNKOWY = "URLOP_WYPOCZYNKOWY"
    URLOP_RODZICIELSKI = "URLOP_RODZICIELSKI"
    INNA_USPRAWIEDLIWIONA = "INNA_USPRAWIEDLIWIONA"
    NIEUSPRAWIEDLIWIONA = "NIEUSPRAWIEDLIWIONA"


class PowodZmianyTerminu(str, Enum):
    NIEOBECNOSC_OCENIANEGO_AUTO = "NIEOBECNOSC_OCENIANEGO_AUTO"
    PRZEWIDYWANA_NIEOBECNOSC_OCENIANEGO = "PRZEWIDYWANA_NIEOBECNOSC_OCENIANEGO"
    PRZEWIDYWANA_NIEOBECNOSC_OCENIAJACEGO = "PRZEWIDYWANA_NIEOBECNOSC_OCENIAJACEGO"
    WNIOSEK_OCENIANEGO = "WNIOSEK_OCENIANEGO"
    INNY = "INNY"


class StatusWniosku(str, Enum):
    ZLOZONY = "ZLOZONY"
    ZAAKCEPTOWANY = "ZAAKCEPTOWANY"
    ODRZUCONY = "ODRZUCONY"
    AUTO = "AUTO"


class TypNotatki(str, Enum):
    OBSERWACJA = "OBSERWACJA"
    BIEZACY_FEEDBACK = "BIEZACY_FEEDBACK"
    ROZMOWA_ROZPOCZYNAJACA = "ROZMOWA_ROZPOCZYNAJACA"
    ROZMOWA_OCENIAJACA = "ROZMOWA_OCENIAJACA"


class Wydzwiek(str, Enum):
    POZYTYWNY = "POZYTYWNY"
    NEUTRALNY = "NEUTRALNY"
    NEGATYWNY = "NEGATYWNY"


class Akcja(str, Enum):
    """Process transitions = commands. The server checks role, status and conditions."""
    ZATWIERDZ_KRYTERIA = "ZATWIERDZ_KRYTERIA"            # oceniający: -> KRYTERIA_DO_POTWIERDZENIA
    POTWIERDZ_KRYTERIA = "POTWIERDZ_KRYTERIA"            # oceniany:   -> OKRES_OCENY
    ROZPOCZNIJ_ROZMOWE = "ROZPOCZNIJ_ROZMOWE"            # oceniający: -> ROZMOWA_OCENIAJACA
    ZATWIERDZ_OCENE = "ZATWIERDZ_OCENE"                  # oceniający: -> OCENA_DO_ZAPOZNANIA
    POTWIERDZ_ZAPOZNANIE = "POTWIERDZ_ZAPOZNANIE"        # oceniany:   -> ZAKONCZONA
    FIKCJA_ZAPOZNANIA = "FIKCJA_ZAPOZNANIA"              # oceniający: -> ZAKONCZONA (fikcja_zapoznania=true)
    ZLOZ_SPRZECIW = "ZLOZ_SPRZECIW"                      # 🟡 oceniany: -> SPRZECIW
    ROZPATRZ_SPRZECIW = "ROZPATRZ_SPRZECIW"              # 🟡 DG / kadry


class Waga(str, Enum):
    BLAD = "BLAD"            # blocks the action
    OSTRZEZENIE = "OSTRZEZENIE"  # shown, does not block


class TrybAI(str, Enum):
    OFF = "OFF"
    LOCAL = "LOCAL"
    API = "API"


# ---------------------------------------------------------------- shared

class Walidacja(_Out):
    """One problem. `pole` = field name from EvaluationOut (or `kryteria.<kod>`), null = whole record."""
    kod: str = Field(examples=["UZASADNIENIE_WYMAGANE"])
    pole: str | None = Field(None, examples=["uzasadnienie"])
    waga: Waga
    komunikat: str = Field(examples=["Przy ocenie negatywnej uzasadnienie jest obowiązkowe (§ 11 ust. 3)."])


class ApiError(_Out):
    """Body of every 4xx: 403 brak uprawnień, 404, 409 niedozwolone przejście/edycja, 422 walidacja."""
    kod: str = Field(examples=["PRZEJSCIE_NIEDOZWOLONE"])
    komunikat: str
    walidacje: list[Walidacja] = []


class OsobaRef(_Out):
    id: int
    imie: str
    nazwisko: str
    stanowisko: str | None = None


# ---------------------------------------------------------------- session / meta

class UserContext(_Out):
    """GET /api/me – who is 'logged in' (demo: X-User-Id header) and what they can see."""
    pracownik: OsobaRef
    rola: Rola
    czy_oceniajacy: bool                 # has subordinates (role of evaluator comes from hierarchy)
    podwladni_ids: list[int] = []
    urzad: str


class MetaOut(_Out):
    """GET /api/meta – everything the UI needs once at start-up."""
    dzis: date                           # from the (demo) clock, NOT the browser
    tryb_ai: TrybAI
    funkcje_ai: dict[str, bool]          # e.g. {"szkic_uzasadnienia": true, "klasyfikacja_notatek": false}
    skala_punktow: list[int] = [1, 3, 5, 7, 9]
    progi_poziomow: dict[Poziom, tuple[float, float]]
    maks_kryteriow_dodatkowych: int = 3


class CriterionOut(_Out):
    """GET /api/criteria?arkusz=C – dictionary with behavioural indicators."""
    kod: str = Field(examples=["RZETELNOSC"])
    nazwa: str
    opis: str
    wskazniki: list[str] = []            # behavioural indicators from the regulation (for UI + evidence)
    typ_dla_arkusza: TypKryterium | None = None  # set when ?arkusz= given
    kolejnosc: int


# ---------------------------------------------------------------- employees & dashboard

class EmployeeOut(_Out):
    id: int
    imie: str
    nazwisko: str
    email: str
    stanowisko: str
    komorka: str
    arkusz: Arkusz
    typ_zatrudnienia: TypZatrudnienia
    stopien_sluzbowy: int | None = None
    rok_mianowania: int | None = None
    data_przyznania_stopnia: date | None = None
    przelozony: OsobaRef | None = None
    rola: Rola
    aktywny: bool


class DashboardItem(_Out):
    """One row of the evaluator's / HR dashboard: whose evaluation, what is next, how urgent."""
    evaluation_id: int | None            # null = no cycle yet (HR can start one)
    oceniany: OsobaRef
    arkusz: Arkusz
    status: StatusOceny | None
    nastepny_krok: str | None = Field(None, examples=["Wyznacz kryteria"])
    kto_dziala: Literal["OCENIAJACY", "OCENIANY", "KADRY", "NIKT"] = "NIKT"
    termin: date | None                  # nearest relevant deadline
    dni_do_terminu: int | None
    pilnosc: Literal["PO_TERMINIE", "PILNE", "WKROTCE", "OK"] = "OK"   # PILNE ≤ 7 dni, WKROTCE ≤ 30
    sygnaly_hr: int = 0                  # count of open HR-partner signals (badge)
    # optional extras for the overview table (added with the web UI; backward compatible)
    komorka: str | None = None
    wynik: Wynik | None = None           # only once the evaluation is made
    termin_oceny: date | None = None     # evaluation deadline (termin = the deadline relevant right now)


class DashboardOut(_Out):
    """GET /api/dashboard – scope depends on role (evaluator: subordinates, KADRY/DG: whole office)."""
    pozycje: list[DashboardItem]
    nieprzeczytane_powiadomienia: int


# ---------------------------------------------------------------- evaluation (the sheet)

class EvaluationCriterionOut(_Out):
    criterion_kod: str
    nazwa: str
    typ: TypKryterium
    kolejnosc: int
    punkty: Punkty | None = None
    sugerowane_punkty: Punkty | None = None      # from evidence rule, never applied automatically
    liczba_dowodow: dict[Wydzwiek, int] = {}     # quick badge; details: GET .../evidence


class Podpis(_Out):
    """Confirmation = signature on the paper sheet. Filled by the server on the action."""
    at: datetime | None = None
    miejscowosc: str | None = None
    osoba: OsobaRef | None = None


class CzescI(_Out):
    data_wyznaczenia_kryteriow: date | None = None
    termin_oceny: date
    termin_wyznaczenia_kryteriow: date
    potw_oceniajacy: Podpis = Podpis()
    potw_oceniany: Podpis = Podpis()


class PoprzedniaOcena(_Out):
    """Only for URZEDNIK. From history when available (zrodlo=SYSTEM), else typed by evaluator (RECZNIE)."""
    zrodlo: Literal["SYSTEM", "RECZNIE"]
    wynik: Wynik | Literal["BRAK"] | None = None
    poziom: Poziom | None = None
    data: date | None = None


class CzescII(_Out):
    data_rozmowy_oceniajacej: date | None = None
    okres_od: date | None = None
    okres_do: date | None = None
    srednia: float | None = None           # computed by server
    poziom: Poziom | None = None           # computed
    wynik: Wynik | None = None             # computed: § 11 – poziom ≥ NA_POZIOMIE AND no partial score = 1
    uzasadnienie: str | None = None
    wnioski_iprz: str | None = None
    poprzednia_ocena: PoprzedniaOcena | None = None
    wniosek_o_stopien: WniosekOStopien
    data_sporzadzenia: datetime | None = None
    podpis_oceniajacego: Podpis = Podpis()
    zapoznanie: Podpis = Podpis()
    fikcja_zapoznania: bool = False
    termin_sprzeciwu: date | None = None   # data_zapoznania + 7 dni


class CzescIII(_Out):
    """Only URZEDNIK + wniosek_o_stopien=TAK (or when the obligatory grade applies)."""
    posiadany_stopien: int | None = None
    wnioskowany_stopien: int | None = None     # computed: posiadany + 1, null at 9
    umotywowanie_wniosku: str | None = None
    stopien_obligatoryjny: bool = False         # computed (art. 89 ust. 2)


class EvaluationOut(_Out):
    """GET /api/evaluations/{id} – the whole sheet + what the current user may do with it."""
    id: int
    wersja: int
    status: StatusOceny
    arkusz: Arkusz
    urzad: str
    oceniany: EmployeeOut
    oceniajacy: OsobaRef
    kryteria: list[EvaluationCriterionOut]
    czesc_i: CzescI
    czesc_ii: CzescII
    czesc_iii: CzescIII | None = None
    # --- server-side rules, so the UI does not duplicate them
    dozwolone_akcje: list[Akcja]
    edytowalne_pola: list[str] = Field(examples=[["kryteria_dodatkowe", "termin_oceny"]])
    walidacje: list[Walidacja] = []             # current problems; BLAD ones block the next action
    updated_at: datetime                        # send back as If-Unmodified-Since / `updated_at` to avoid lost updates


class EvaluationListItem(_Out):
    id: int
    oceniany: OsobaRef
    oceniajacy: OsobaRef
    arkusz: Arkusz
    status: StatusOceny
    termin_oceny: date
    wynik: Wynik | None = None
    wersja: int


class EvaluationCreate(BaseModel):
    """POST /api/evaluations – start a cycle. Arkusz, oceniający, terminy are derived by the server."""
    oceniany_id: int
    data_poczatku_cyklu: date | None = None     # default: previous evaluation / employment date


class EvaluationPatch(BaseModel):
    """PATCH /api/evaluations/{id} – only fields listed in edytowalne_pola; others -> 409 POLE_ZABLOKOWANE.
    Send only changed fields. `updated_at` = value you last read (optimistic locking)."""
    updated_at: datetime
    termin_oceny: date | None = None
    data_rozmowy_oceniajacej: date | None = None
    okres_od: date | None = None
    okres_do: date | None = None
    uzasadnienie: str | None = None
    wnioski_iprz: str | None = None
    wniosek_o_stopien: WniosekOStopien | None = None
    umotywowanie_wniosku: str | None = None
    posiadany_stopien: int | None = Field(None, ge=1, le=9)
    poprzednia_ocena: PoprzedniaOcena | None = None
    miejscowosc: str | None = None


class AdditionalCriteriaIn(BaseModel):
    """PUT /api/evaluations/{id}/criteria/additional – full list (0–3), replaces previous choice."""
    kody: list[str] = Field(max_length=3, examples=[["ORIENTACJA_NA_KLIENTA", "KREATYWNOSC"]])


class ScoresIn(BaseModel):
    """PUT /api/evaluations/{id}/scores – partial allowed (null clears). Response = ScoresOut, instant."""
    punkty: dict[str, Punkty | None] = Field(examples=[{"RZETELNOSC": 3, "KOMUNIKACJA": 1}])


class ScoresOut(_Out):
    """Live recalculation for the score matrix – rules only, no LLM, milliseconds."""
    srednia: float | None
    poziom: Poziom | None
    wynik: Wynik | None
    kryteria: list[EvaluationCriterionOut]
    walidacje: list[Walidacja]                  # e.g. NEGATYWNA -> UZASADNIENIE_WYMAGANE; score vs evidence warnings


class ActionIn(BaseModel):
    """POST /api/evaluations/{id}/actions/{akcja}. Response: EvaluationOut (200) or ApiError (409/422)."""
    miejscowosc: str | None = None
    komentarz: str | None = None                # e.g. objection text, decision reason


# ---------------------------------------------------------------- notes & evidence

class NoteIn(BaseModel):
    """POST /api/evaluations/{id}/notes – 201 immediately; AI classification runs in background."""
    data: date
    typ: TypNotatki = TypNotatki.OBSERWACJA
    tresc: str = Field(min_length=1)
    criterion_kod: str | None = None            # manual tagging (also the no-AI path)
    wydzwiek: Wydzwiek | None = None
    widoczna_dla_ocenianego: bool = False


class NotePatch(BaseModel):
    """PATCH /api/notes/{id} – also used to accept/correct an AI suggestion."""
    tresc: str | None = None
    criterion_kod: str | None = None
    wydzwiek: Wydzwiek | None = None
    widoczna_dla_ocenianego: bool | None = None
    zaakceptuj_sugestie: bool | None = None     # true = copy sugestia_ai into criterion_kod/wydzwiek


class SugestiaKlasyfikacji(_Out):
    criterion_kod: str
    nazwa: str = ""
    wskaznik: str | None = None                 # behavioural indicator text
    wydzwiek: Wydzwiek | None = None            # null when the suggestion comes from the no-AI fallback
    pewnosc: float = Field(ge=0, le=1)
    fragment: str = ""                          # quote from the note that justifies it (empty in fallback)


class NoteOut(_Out):
    id: int
    evaluation_id: int
    autor: OsobaRef
    data: date
    typ: TypNotatki
    tresc: str
    criterion_kod: str | None = None
    wydzwiek: Wydzwiek | None = None
    widoczna_dla_ocenianego: bool
    # SUGESTIA = confident AI proposal; DO_PRZYPISANIA = low confidence or no AI -> evaluator picks
    status_klasyfikacji: Literal["BRAK", "W_TOKU", "SUGESTIA", "DO_PRZYPISANIA", "ZATWIERDZONA", "RECZNA", "BLAD"] = "BRAK"
    zrodlo_sugestii: Literal["AI", "REGULY"] | None = None
    sugestie_ai: list[SugestiaKlasyfikacji] = []


class EvidenceCriterion(_Out):
    criterion_kod: str
    nazwa: str
    plus: int
    neutralne: int
    minus: int
    notatki_ids: list[int]
    wskazniki_bez_obserwacji: list[str] = []    # "ask about it in the conversation"
    sugerowane_punkty: Punkty | None = None
    uzasadnienie_sugestii: str | None = None    # rule-based, readable


class EvidenceOut(_Out):
    """GET /api/evaluations/{id}/evidence – evidence map; poll every few seconds while notes are W_TOKU."""
    kryteria: list[EvidenceCriterion]
    notatki_do_przypisania: int
    w_toku: int


# ---------------------------------------------------------------- AI-assisted outputs (all optional)

class KryteriumSugestia(_Out):
    kod: str
    nazwa: str = ""
    uzasadnienie: str


class SuggestCriteriaOut(_Out):
    """POST /api/evaluations/{id}/ai/suggest-criteria – max 3; never applied automatically."""
    sugestie: list[KryteriumSugestia]
    zrodlo: Literal["AI", "REGULY"]             # REGULY when AI is off


class PrzykladNotatki(_Out):
    """A note quoted as an example in the conversation prep (no author/visibility details needed)."""
    id: int | str
    data: date
    tresc: str
    wydzwiek: Wydzwiek | None = None


class PrepKryterium(_Out):
    criterion_kod: str
    nazwa: str
    obowiazkowe: bool = True
    plus: int
    minus: int
    przyklady: list[PrzykladNotatki] = []
    luki: list[str] = []                        # behavioural indicators without any observation -> ask
    pytania: list[str] = []


class ConversationPrepOut(_Out):
    """POST /api/evaluations/{id}/ai/conversation-prep – the evaluator's one-page conversation note.
    Skeleton from data (works with AI off), texts from AI when available. No scores in it."""
    rodzaj: Literal["ROZPOCZYNAJACA", "OCENIAJACA"]
    cel_rozmowy: str
    termin_oceny: date
    poprzednia_ocena: PoprzedniaOcena | None = None
    kryteria: list[PrepKryterium]
    mocne_strony: list[str] = []
    trudne_tematy: list[str] = []
    sygnaly_hr: list["HrSignal"] = []
    propozycje_rozwoju: list[str] = []
    plan_minuty: list[tuple[str, int]] = Field(default_factory=list, examples=[[["Otwarcie", 5], ["Kryteria", 20]]])
    cele: list[str] = []                        # goals agreed at the opening conversation
    dni_do_terminu: int | None = None
    zrodlo_tekstow: Literal["AI", "SZABLON"]


class DraftIn(BaseModel):
    """POST /api/evaluations/{id}/ai/draft – Accept: text/event-stream for streaming, else JSON DraftOut."""
    rodzaj: Literal["UZASADNIENIE", "IPRZ", "UMOTYWOWANIE_STOPNIA"]


class DraftOut(_Out):
    rodzaj: Literal["UZASADNIENIE", "IPRZ", "UMOTYWOWANIE_STOPNIA"]
    tekst: str
    zrodlo: Literal["AI", "SZABLON"]
    oparte_na_notatkach: list[int] = []
    nieaktualny: bool = False                   # data changed since generation


class HrSignal(_Out):
    id: int
    typ: Literal["PRZECIAZENIE", "DLUGA_NIEOBECNOSC", "ZMIANA_OBOWIAZKOW", "SPADEK_OCEN", "DO_DOCENIENIA"]
    opis: str
    dowody: list[str] = []                      # e.g. note ids / absence periods in words
    rekomendacje: list[str] = []
    status: Literal["NOWY", "ZAAKCEPTOWANY", "ODRZUCONY"] = "NOWY"


class HrPartnerOut(_Out):
    """GET /api/evaluations/{id}/hr-partner – hints for the manager, never a diagnosis of the employee."""
    sygnaly: list[HrSignal]
    zrodlo_tekstow: Literal["AI", "REGULY"]     # signals always come from rules; AI only words them


class HrSignalDecision(BaseModel):
    """POST /api/hr-signals/{id}/decision"""
    status: Literal["ZAAKCEPTOWANY", "ODRZUCONY"]


# ---------------------------------------------------------------- 🟡 absences, deadline changes, notifications

class AbsenceIn(BaseModel):
    od: date
    do: date
    typ: TypNieobecnosci


class AbsenceOut(_Out):
    id: int
    od: date
    do: date
    typ: TypNieobecnosci
    usprawiedliwiona: bool


class DeadlineChangeIn(BaseModel):
    powod: PowodZmianyTerminu
    nowy_termin: date | None = None             # null for WNIOSEK_OCENIANEGO (evaluator decides)
    uzasadnienie: str | None = None


class DeadlineChangeOut(_Out):
    id: int
    powod: PowodZmianyTerminu
    stary_termin: date
    nowy_termin: date | None
    status: StatusWniosku
    uzasadnienie: str | None = None
    decyzja_at: datetime | None = None


class NotificationOut(_Out):
    id: int
    typ: str
    tresc: str
    evaluation_id: int | None = None
    zaplanowane_na: datetime
    wyslane_at: datetime | None = None
    przeczytane: bool = False


# ---------------------------------------------------------------- demo only

class ClockIn(BaseModel):
    """POST /api/demo/clock – move the server clock; schedulers run and create notifications."""
    przesun_dni: int | None = None
    ustaw_date: date | None = None


class ClockOut(_Out):
    dzis: date
    nowe_powiadomienia: int


ConversationPrepOut.model_rebuild()
