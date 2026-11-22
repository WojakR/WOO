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


class TrybSprzeciwu(str, Enum):
    """Upheld objection (art. 83 ust. 4): what the director general orders the evaluator to do."""
    ZMIANA_OCENY = "ZMIANA_OCENY"                  # replace parts (e.g. partial scores); stays acknowledged
    PONOWNE_SPORZADZENIE = "PONOWNE_SPORZADZENIE"  # annul, back to the review meeting; new objection possible


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
    ZMIANA_STANOWISKA = "ZMIANA_STANOWISKA"  # art. 81 ust. 6, § 9 ust. 2 (see PositionChangeOut)
    ZMIANA_OCENIAJACEGO = "ZMIANA_OCENIAJACEGO"  # art. 81 ust. 8 pkt 1


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
    ZLOZ_SPRZECIW = "ZLOZ_SPRZECIW"                      # oceniany (7 dni od zapoznania): -> SPRZECIW
    ROZPATRZ_SPRZECIW = "ROZPATRZ_SPRZECIW"              # DG (ustawienia urzędu): -> ROZMOWA_OCENIAJACA / ZAKONCZONA


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
    tryb_aplikacji: Literal["DEMO", "PRODUKCJA"] = "DEMO"  # PRODUKCJA: no clock shift, no demo reset
    tryb_logowania: Literal["DEMO", "SESJA"] = "DEMO"      # SESJA: login screen, no identity switch
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
    moje: list[DashboardItem] = []              # the user's own evaluations (as the evaluated person)


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
    adnotacja_odmowy: str | None = None    # fikcja zapoznania: the evaluator's note
    data_wydruku: date | None = None       # paper flow
    data_podpisu: date | None = None       # = data zapoznania when signed on paper
    termin_sprzeciwu: date | None = None   # data_zapoznania (or return to work) + 7 dni


class CzescIII(_Out):
    """Only URZEDNIK + wniosek_o_stopien=TAK (or when the obligatory grade applies)."""
    posiadany_stopien: int | None = None
    wnioskowany_stopien: int | None = None     # computed: posiadany + 1, null at 9
    umotywowanie_wniosku: str | None = None
    stopien_obligatoryjny: bool = False         # computed (art. 89 ust. 2)


class TerminOut(_Out):
    """One deadline of the evaluation, computed by the server (app/domain/timeline.py) from what has happened."""
    rodzaj: str                                 # KRYTERIA | OCENA | ZAPOZNANIE | SPRZECIW | KOLEJNA_OCENA | KRYTERIA_NASTEPNE
    nazwa: str
    data: date | None = None                    # null = "niezwłocznie" (no fixed day)
    podstawa: str                               # legal basis
    stan: Literal["SPELNIONY", "AKTUALNY", "PO_TERMINIE", "NASTEPNY_OKRES"]
    spelniony_at: date | None = None
    opis: str = ""


class SprzeciwOut(_Out):
    """Objection (art. 83): filed within 7 days of acknowledging, decided by the director general in 14 days."""
    zlozony: date
    tresc: str
    termin_rozpatrzenia: date                   # art. 83 ust. 3
    decyzja: Literal["UWZGLEDNIONY", "NIEUWZGLEDNIONY"] | None = None
    rozstrzygnieto: date | None = None
    uzasadnienie_decyzji: str = ""
    termin_odwolania_do_sadu: date | None = None  # art. 83 ust. 5 – only when not upheld
    tryb: TrybSprzeciwu | None = None           # upheld: change or draw up again
    termin_wykonania: date | None = None        # upheld, not carried out yet: 14 days from filing (Poradnik KPRM)
    wykonano: date | None = None                # the evaluator changed it / drew it up again on this day
    przed_sprzeciwem: "OcenaPrzedSprzeciwem | None" = None  # the evaluation as it was before the decision


class OcenaPrzedSprzeciwem(_Out):
    """The evaluation before an upheld objection: annulled (drawn up again) or replaced by its change."""
    data_sporzadzenia: date | None = None
    wynik: Wynik | None = None
    srednia: float | None = None
    poziom: Poziom | None = None
    punkty: dict[str, int] = {}                 # criterion code -> partial score (the floor for the new one)
    anulowana: bool = False


SprzeciwOut.model_rebuild()


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
    sprzeciw: SprzeciwOut | None = None
    jako_oceniajacy: bool = False             # current user acts as the evaluator here (evaluator or
                                              # active deputy) -> evaluator's working material in the UI
    dozwolone_akcje: list[Akcja]
    edytowalne_pola: list[str] = Field(examples=[["kryteria_dodatkowe", "termin_oceny"]])
    walidacje: list[Walidacja] = []             # current problems; BLAD ones block the next action
    terminy: list[TerminOut] = []               # every deadline so far and the ones it starts (server-computed)
    dobor_arkusza: DoborArkusza | None = None
    rozpatrujacy_sprzeciw: RozpatrujacySprzeciw | None = None
    eksport_eakt: EksportEakt | None = None     # only for HR
    zaimportowana: bool = False                 # legacy evaluation imported from a PDF (history only)
    updated_at: datetime                        # send back as If-Unmodified-Since / `updated_at` to avoid lost updates


class EvaluationCreate(BaseModel):
    """POST /api/evaluations – start a cycle. Arkusz, oceniający, terminy are derived by the server."""
    oceniany_id: int
    data_poczatku_cyklu: date | None = None     # default: previous evaluation / employment date
    arkusz: Arkusz | None = None                # default: the system's suggestion (HR may choose another one)
    uzasadnienie_arkusza: str = ""              # required when `arkusz` differs from the suggestion


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
    komentarz: str | None = None                # e.g. objection text, decision reason, refusal note
    uwzglednij: bool | None = None              # ROZPATRZ_SPRZECIW: true = upheld, false = not upheld
    tryb: TrybSprzeciwu | None = None           # ROZPATRZ_SPRZECIW upheld: required – change or draw up again
    data: date | None = None                    # FIKCJA_ZAPOZNANIA: day of the refusal (default: today)


class PaperIn(BaseModel):
    """PUT /api/evaluations/{id}/paper – paper flow: print date, signature date (= acknowledgement)."""
    data_wydruku: date | None = None
    data_podpisu: date | None = None


class SheetChangeIn(BaseModel):
    """PUT /api/evaluations/{id}/sheet – HR changes the sheet before the criteria are approved."""
    arkusz: Arkusz
    uzasadnienie: str


class ZmianaArkusza(_Out):
    data: date
    kto: str
    z: Arkusz
    na: Arkusz
    uzasadnienie: str


class DoborArkusza(_Out):
    """The system's sheet suggestion from the position (§ 3) and HR's changes."""
    sugerowany: Arkusz
    powod: str
    ostrzezenie: str | None = None
    zmiany: list[ZmianaArkusza] = []
    mozna_zmienic: bool = False                 # current user is HR and the criteria are not approved yet


class EksportEakt(_Out):
    """Last export of the sheet to the electronic personnel file (e-Akt)."""
    status: Literal["WYSLANO", "BLAD"]
    zdarzenie: str                              # ZAPOZNANIE | ROZPATRZENIE_SPRZECIWU
    proby: int
    ostatnia_proba: datetime
    miejsce: str = ""
    sha256: str = ""
    blad: str = ""


class RozpatrujacySprzeciw(_Out):
    id: str
    nazwa: str
    podstawa: str


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
    # the hint counts notes, not their weight: what one more negative / positive note would give
    sugerowane_od: Punkty | None = None
    sugerowane_do: Punkty | None = None


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


class SuggestCriteriaIn(BaseModel):
    """POST /api/evaluations/{id}/ai/suggest-criteria – optional description of the duties (body may be omitted)."""
    opis: str = Field(default="", max_length=2000)


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
    typ: Literal["PRZECIAZENIE", "DLUGA_NIEOBECNOSC", "ZMIANA_OBOWIAZKOW", "SPADEK_OCEN", "DO_DOCENIENIA",
                 # from the person's history – tenure + trend of the evaluations (app/domain/career_profile.py)
                 "SPADEK_PRZY_STAZU", "SPADEK_TRENDU", "STAGNACJA", "STABILNIE_WYSOKO", "WZROST", "NOWY_PRACOWNIK"]
    opis: str
    dowody: list[str] = []                      # e.g. note ids / absence periods in words
    rekomendacje: list[str] = []
    dzialania_rozwojowe: list[str] = []         # development ideas (IPRZ, training) – history-based signals
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
    evaluation_id: int | None = None
    oceniany: OsobaRef | None = None
    zlozyl: OsobaRef | None = None
    komentarz_decyzji: str | None = None
    pismo_pdf: bool = False                     # GET /api/deadline-changes/{id}/pdf (accepted changes)


class PositionChangeIn(BaseModel):
    """POST /api/employees/{id}/position-changes – change of position with a significant change of duties."""
    data_zmiany: date
    nowe_stanowisko: str = Field(min_length=1)
    nowy_arkusz: Arkusz | None = None           # the sheet the new position needs (None = keep)


class PositionChangeOut(_Out):
    """NOWE_KRYTERIA (§ 9 ust. 1): criteria + opening conversation again by `termin`, evaluation deadline unchanged.
    OCENA (art. 81 ust. 6, § 9 ust. 2): evaluation between `najwczesniej` and `termin`."""
    rodzaj: Literal["NOWE_KRYTERIA", "OCENA"]
    data_zmiany: date
    data_odniesienia: date               # last evaluation, or criteria date for a first evaluation
    termin: date
    najwczesniej: date | None = None
    wyjasnienie: str = ""                # what it means, in Polish, for the UI
    arkusz_zmieniony: bool = False
    ocena: "EvaluationOut | None" = None  # the cycle after the change


class AbsenceOut(_Out):
    id: int
    od: date
    do: date
    typ: TypNieobecnosci
    usprawiedliwiona: bool
    dni: int                                    # calendar days, inclusive
    evaluation_id: int | None = None            # the cycle it was registered against
    termin_oceny: date | None = None            # evaluation deadline after this absence (server-computed)
    zmiana_terminu: DeadlineChangeOut | None = None  # set when this absence moved the deadline (AUTO)


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
PositionChangeOut.model_rebuild()


# ---------------------------------------------------------------- zastępstwa (deputy evaluator)

class ZastepstwoIn(BaseModel):
    """POST /api/zastepstwa – `zastepca_id` stands in for evaluator `oceniajacy_id` from `od` to `do`:
    may hold the conversations and draw up the evaluation (KPRM mentor, 21.11.2026)."""
    oceniajacy_id: int
    zastepca_id: int
    od: date
    do: date


class ZastepstwoOut(_Out):
    id: int
    oceniajacy: OsobaRef
    zastepca: OsobaRef
    od: date
    do: date
    aktywne: bool                               # on the server's today


# ---------------------------------------------------------------- configurable reminders

class RegulaPrzypomnienia(BaseModel):
    rodzaj: Literal["CO_DNI", "DNI_PRZED", "TYGODNIE_PRZED", "MIESIACE_PRZED", "PROCENT_OKRESU"]
    wartosc: int
    opis: str = ""                              # filled by the server, e.g. "po 50 % okresu"


class UstawieniaPrzypomnienIn(BaseModel):
    """PUT /api/me/przypomnienia (own) or /api/ustawienia/przypomnienia (office default, HR). Stages not sent
    stay as they were. The hour must be inside office working hours; dates never fall on days off."""
    godzina: str | None = Field(None, examples=["11:00"])
    etapy: dict[Literal["WYZNACZENIE_KRYTERIOW", "OKRES_OCENY", "ZAPOZNANIE", "ROZPATRZENIE_SPRZECIWU"],
                list[RegulaPrzypomnienia]] = {}
    email: bool | None = None                   # own settings only: false = no e-mails, in-app notifications only


class UstawieniaPrzypomnienOut(_Out):
    godzina: str
    godziny_pracy: tuple[str, str]              # ("08:00", "16:00") – reminders only inside, only on working days
    etapy: dict[str, list[RegulaPrzypomnienia]]
    wlasne: bool                                # true = the user's own schedule, false = office default
    email: bool = True                          # reminders also by e-mail (when the person has an address)
    adres_email: str | None = None              # from the HR data; None = in-app notifications only


class PlanowanePrzypomnienie(_Out):
    kiedy: datetime
    etap: str
    do_kogo: OsobaRef
    tresc: str
    termin: date
    minelo: bool                                # already sent (on the server clock)


# ---------------------------------------------------------------- office settings (administrator = HR)

class RegulaOut(_Out):
    """One editable requirement of the regulation (e.g. after an amendment the administrator changes it)."""
    klucz: str
    nazwa: str
    wartosc: int
    domyslna: int                               # value from reguly.json (the regulation as published)
    jednostka: str
    podstawa: str
    min: int
    max: int


class WymaganieOut(_Out):
    tytul: str
    tresc: str
    podstawa: str


class ZmianaRegulyOut(_Out):
    klucz: str
    nazwa: str
    stara: int
    nowa: int
    podstawa_zmiany: str
    kto: str
    kiedy: date


class ZmianaKryteriumOut(_Out):
    kryterium: str
    nazwa: str
    pole: Literal["nazwa", "wskazniki", "dostepne"]
    stara: str | bool | list[str] | None = None
    nowa: str | bool | list[str] | None = None


class WersjaRegulOut(_Out):
    """One version of the requirements. Each evaluation follows the version in force when its criteria were set."""
    id: int                                     # 0 = the regulation as published (reguly.json)
    obowiazuje_od: date | None = None           # None = since forever (version 0)
    opis: str
    autor: str = ""
    utworzono: date | None = None
    aktualna: bool = False                      # in force today
    przyszla: bool = False                      # comes into force later
    oceny: int = 0                              # evaluations computed by this version
    zmiany: list[ZmianaRegulyOut] = []          # against the previous version
    zmiany_kryteriow: list[ZmianaKryteriumOut] = []


class KryteriumWersjiOut(_Out):
    id: str
    nazwa: str
    wskazniki: list[str]
    dostepne: bool                              # offered as an additional criterion
    obowiazkowe_w: list[str]                    # sheets where it is mandatory (cannot be withdrawn)


class RegulyOut(_Out):
    """GET /api/ustawienia/reguly – what the system enforces, with the administrator's changes and their log."""
    parametry: list[RegulaOut]
    wymagania: list[WymaganieOut]
    zmiany: list[ZmianaRegulyOut]
    zmienione: bool                             # any value differs from the published regulation
    moze_edytowac: bool
    wersje: list[WersjaRegulOut] = []
    aktualna_wersja: int = 0
    kryteria: list[KryteriumWersjiOut] = []     # criteria list of the latest version (to edit)


class RegulyIn(BaseModel):
    """PUT /api/ustawienia/reguly (administrator): a new version of the requirements. Only the keys sent are
    changed (against the latest version). In force from `obowiazuje_od` (default: today, never earlier)."""
    wartosci: dict[str, int] = {}
    kryteria: dict[str, dict] = {}              # {"negocjowanie": {"nazwa": ..., "wskazniki": [...], "dostepne": false}}
    obowiazuje_od: date | None = None
    podstawa_zmiany: str = Field(min_length=3, examples=["nowelizacja rozporządzenia, Dz. U. 2027 poz. 123"])


class UstawieniaUrzeduOut(_Out):
    zakres_widocznosci: Literal["PODDRZEWO", "BEZPOSREDNI"]
    asystent_ai: bool                           # office-wide switch of the language model
    hr_partner: bool                            # office-wide switch of the virtual HR partner
    tryb_ai_serwera: TrybAI                     # AI_MODE of the server (OFF = no model configured at all)
    moze_edytowac: bool


class UstawieniaUrzeduIn(BaseModel):
    zakres_widocznosci: Literal["PODDRZEWO", "BEZPOSREDNI"] | None = None
    asystent_ai: bool | None = None
    hr_partner: bool | None = None


class MojAsystentOut(_Out):
    """GET/PUT /api/me/asystent – my own switch; the office switch wins when it is off."""
    asystent_ai: bool
    hr_partner: bool
    asystent_ai_w_urzedzie: bool
    hr_partner_w_urzedzie: bool


class MojAsystentIn(BaseModel):
    asystent_ai: bool | None = None
    hr_partner: bool | None = None
