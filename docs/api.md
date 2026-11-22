# Kontrakt API: frontend ↔ backend

Schematy: [`app/api/schemas.py`](../app/api/schemas.py) (Pydantic v2). FastAPI generuje z nich OpenAPI pod
`/docs` i `/openapi.json`; frontend generuje klienta z OpenAPI albo używa nazw z tego pliku.
Nazwy pól i wartości enumów są zgodne z modelem danych (`model-danych.md`), żeby API mapowało się 1:1 na encje.

## Zasady

1. **Frontend nie liczy reguł.** Średnia, poziom, wynik, terminy, stopień obligatoryjny i walidacje przychodzą
   z serwera. Każda odpowiedź z oceną zawiera też `dozwolone_akcje` i `edytowalne_pola` dla bieżącego użytkownika,
   więc UI tylko pokazuje i blokuje przyciski.
2. **Przejścia procesu to komendy**, nie edycja statusu: `POST /api/evaluations/{id}/actions/{akcja}`.
3. **Edycja tylko pól z `edytowalne_pola`** (`PATCH`); inne pole → `409 POLE_ZABLOKOWANE`. W `PATCH` odsyłamy
   `updated_at` z ostatniego odczytu; nieaktualne → `409 KONFLIKT_WERSJI`.
4. **Wartości wyliczane tylko do odczytu** (`srednia`, `poziom`, `wynik`, `wnioskowany_stopien`, `stopien_obligatoryjny`).
5. **Błędy** zawsze w kształcie `ApiError {kod, komunikat, walidacje[]}`:
   `403` brak uprawnień, `404`, `409` niedozwolone przejście/edycja/konflikt, `422` walidacja (`walidacje` z `waga: BLAD`).
6. **Tożsamość na demo:** nagłówek `X-User-Id: <employee id>` zamiast logowania; rola i to, czy ktoś jest
   oceniającym (z podległości), wylicza serwer (`GET /api/me`).
7. **Czas na demo:** serwer ma własny zegar (`GET /api/meta → dzis`, `POST /api/demo/clock`). Frontend nigdy nie
   używa daty z przeglądarki do terminów.
8. **AI jest opcjonalne.** `GET /api/meta → tryb_ai, funkcje_ai` mówi, które przyciski AI pokazać. Endpointy AI
   działają też przy `OFF`: zwracają wersję z szablonu (`zrodlo: "SZABLON"` / `"REGULY"`).
9. **Daty** `YYYY-MM-DD`, znaczniki czasu ISO 8601 z strefą; identyfikatory `int`.

## Endpointy

🟢 = potrzebne do 20:00 (UC1–UC7), 🟡 = druga połowa.

### Sesja, słowniki, pulpit

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| 🟢 `GET /api/me` | – | `UserContext` | kto jest „zalogowany” (X-User-Id) |
| 🟢 `GET /api/meta` | – | `MetaOut` | data z zegara, tryb AI, skala, progi |
| 🟢 `GET /api/criteria?arkusz=C` | – | `CriterionOut[]` | słownik kryteriów ze wskaźnikami; `typ_dla_arkusza` przy `?arkusz` |
| 🟢 `GET /api/dashboard` | – | `DashboardOut` | oceniający: podwładni; KADRY/DG: cały urząd; pilność i następny krok; `moje` = własne oceny zalogowanej osoby (jako ocenianego) |
| 🟢 `GET /api/employees?zakres=podwladni` | – | `EmployeeOut[]` | |
| 🟢 `GET /api/employees/{id}` | – | `EmployeeOut` | |
| 🟡 `GET /api/notifications` | – | `NotificationOut[]` | |
| 🟡 `POST /api/notifications/{id}/read` | – | 204 | |

### Ocena (arkusz i proces): UC1, UC2, UC5, UC6

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| 🟢 `POST /api/evaluations` | `EvaluationCreate` | `EvaluationOut` 201 | start cyklu; arkusz, kryteria obowiązkowe i terminy ustala serwer |
| 🟢 `GET /api/evaluations/{id}` | – | `EvaluationOut` | cały arkusz + `dozwolone_akcje`, `edytowalne_pola`, `walidacje` |
| 🟢 `PATCH /api/evaluations/{id}` | `EvaluationPatch` | `EvaluationOut` | tylko pola z `edytowalne_pola` |
| 🟢 `PUT /api/evaluations/{id}/criteria/additional` | `AdditionalCriteriaIn` | `EvaluationOut` | 0–3 kryteria, pełna lista |
| 🟢 `PUT /api/evaluations/{id}/scores` | `ScoresIn` | `ScoresOut` | **przeliczenie na żywo** (reguły, bez AI): średnia, poziom, wynik, walidacje |
| 🟢 `POST /api/evaluations/{id}/actions/{akcja}` | `ActionIn` | `EvaluationOut` | przejście procesu; `Akcja` w schematach |
| 🟢 `GET /api/evaluations/{id}/pdf` | – | `application/pdf` | arkusz zgodny ze wzorem (`backend/sheet_pdf.py`); przed zatwierdzeniem oznaczony jako wersja robocza |
| 🟢 `GET /api/evaluations/{id}/audit` | – | wpisy dziennika zmian | kto, kiedy, co zmienił (kadry i oceniający) |

Akcje i kto je wykonuje:

| `akcja` | Kto | Ze statusu → do statusu |
|---|---|---|
| `ZATWIERDZ_KRYTERIA` | oceniający | `KRYTERIA_DO_WYZNACZENIA` → `KRYTERIA_DO_POTWIERDZENIA` |
| `POTWIERDZ_KRYTERIA` | oceniany | `KRYTERIA_DO_POTWIERDZENIA` → `OKRES_OCENY` |
| `ROZPOCZNIJ_ROZMOWE` | oceniający | `OKRES_OCENY` → `ROZMOWA_OCENIAJACA` |
| `ZATWIERDZ_OCENE` | oceniający | `ROZMOWA_OCENIAJACA` → `OCENA_DO_ZAPOZNANIA` |
| `POTWIERDZ_ZAPOZNANIE` | oceniany | `OCENA_DO_ZAPOZNANIA` → `ZAKONCZONA` |
| `FIKCJA_ZAPOZNANIA` | oceniający | `OCENA_DO_ZAPOZNANIA` → `ZAKONCZONA` |
| 🟡 `ZLOZ_SPRZECIW` | oceniany | `ZAKONCZONA` → `SPRZECIW` (do 7 dni) |
| 🟡 `ROZPATRZ_SPRZECIW` | DG / kadry | `SPRZECIW` → `ZAKONCZONA` / `ROZMOWA_OCENIAJACA` |

### Notatki i dowody: UC4, UC5

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| 🟢 `GET /api/evaluations/{id}/notes` | – | `NoteOut[]` | oceniany widzi tylko `widoczna_dla_ocenianego` |
| 🟢 `POST /api/evaluations/{id}/notes` | `NoteIn` | `NoteOut` 201 | od razu; klasyfikacja AI w tle (`status_klasyfikacji: W_TOKU`) |
| 🟢 `PATCH /api/notes/{id}` | `NotePatch` | `NoteOut` | ręczne przypisanie albo `zaakceptuj_sugestie` |
| 🟢 `DELETE /api/notes/{id}` | – | 204 | |
| 🟢 `GET /api/evaluations/{id}/evidence` | – | `EvidenceOut` | mapa dowodów i sugerowane punkty; odpytywać co ~3 s, gdy `w_toku > 0` |

### Widoczność i zastępstwa

Jedna polityka dostępu (`app/domain/access.py`, używana przez wszystkie routery przez `app/api/access.py`):

| Kto | Czyta ocenę (arkusz, status, terminy) | Wypełnia ocenę i widzi materiały robocze (notatki, przygotowanie, szkice, dowody, HR partner) |
|---|---|---|
| oceniany | tylko własną | nie – z notatek tylko `widoczna_dla_ocenianego` |
| bezpośredni oceniający | swoich ocenianych | tak (art. 81 ust. 1) |
| zastępca (w okresie zastępstwa) | jak oceniający | tak; cykl zapisuje, kto działał (`deputy_actions`, `drawn_up_by`); nigdy własnej oceny |
| przełożony wyżej | całe poddrzewo (domyślnie) albo nic poza bezpośrednimi – ustawienie urzędu `zakres_widocznosci` | nie (tylko odczyt) |
| kadry (`X-User-Id: kadry` albo brak nagłówka) | cały urząd | materiały robocze tak, wypełnianie nie |

Ustawienia urzędu: `projekt/config/ustawienia_urzedu.json` (`PODDRZEWO` albo `BEZPOSREDNI`) – decyzje urzędu, oddzielone od przepisów w `reguly.json`.

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| `GET /api/zastepstwa` | – | `ZastepstwoOut[]` | kadry: wszystkie; inni: gdzie są oceniającym albo zastępcą |
| `POST /api/zastepstwa` | `ZastepstwoIn` | `ZastepstwoOut` 201 | kadry albo sam oceniający; 422: ktoś, kto nikogo nie ocenia, sam siebie, `do < od` |
| `DELETE /api/zastepstwa/{id}` | – | 204 | kadry albo oceniający |

### Przypomnienia (konfigurowalne)

Harmonogram na etap: `WYZNACZENIE_KRYTERIOW`, `OKRES_OCENY`, `ZAPOZNANIE`; dowolna liczba reguł (do 30 na etap):
`CO_DNI`, `DNI_PRZED`, `TYGODNIE_PRZED`, `MIESIACE_PRZED`, `PROCENT_OKRESU`. Domyślnie (urząd, `config/ustawienia_urzedu.json`):
kryteria co 7 dni; okres oceny po 50 % i 75 % okresu, 2 miesiące i 2 tygodnie przed terminem; zapoznanie co 3 dni; godz. 11:00.
Przypomnienia tylko w dni robocze (termin w dzień wolny → poprzedni dzień roboczy) i w godzinach pracy urzędu
(godzina spoza → 422).

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| `GET /api/me/przypomnienia` | – | `UstawieniaPrzypomnienOut` | własne albo domyślne urzędu (`wlasne`) |
| `PUT /api/me/przypomnienia` | `UstawieniaPrzypomnienIn` | `UstawieniaPrzypomnienOut` | niewysłane etapy bez zmian |
| `DELETE /api/me/przypomnienia` | – | 204 | powrót do domyślnych urzędu |
| `GET/PUT /api/ustawienia/przypomnienia` | `UstawieniaPrzypomnienIn` | `UstawieniaPrzypomnienOut` | domyślne urzędu; zmienia tylko kadry |
| `GET /api/evaluations/{id}/przypomnienia` | – | `PlanowanePrzypomnienie[]` | plan bieżącego etapu (wysłane i przyszłe) |
| `GET /api/notifications` | – | `NotificationOut[]` | moje wysłane przypomnienia (zegar serwera) |
| `POST /api/notifications/{id}/read` | – | 204 | |

### Ustawienia urzędu (administrator = kadry)

Przepisy, widoczność i przełączniki AI zmienia administrator w aplikacji; zmiany są w bazie (przetrwają restart).

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| `GET /api/ustawienia/reguly` | – | `RegulyOut` | wymagania z rozporządzenia: edytowalne terminy (`parametry`, z wartością z rozporządzenia i podstawą prawną), pozostałe wymagania tylko do odczytu, historia zmian; czyta każdy |
| `PUT /api/ustawienia/reguly` | `RegulyIn` | `RegulyOut` | po nowelizacji: nowe wartości + `podstawa_zmiany` (wymagana); zakresy sprawdza serwer (422); wszystkie terminy liczą się od razu według nowych wartości; tylko kadry |
| `DELETE /api/ustawienia/reguly` | – | `RegulyOut` | powrót do wartości z rozporządzenia (zapisany w historii) |
| `GET/PUT /api/ustawienia/urzad` | `UstawieniaUrzeduIn` | `UstawieniaUrzeduOut` | `zakres_widocznosci` (`PODDRZEWO` / `BEZPOSREDNI`), `asystent_ai`, `hr_partner` dla całego urzędu; zmienia tylko kadry |
| `GET/PUT /api/me/asystent` | `MojAsystentIn` | `MojAsystentOut` | „guzik wyłączenia”: asystent AI i HR partner tylko dla mnie; wyłączenie w urzędzie wygrywa |

- Asystent AI wyłączony (w urzędzie albo dla mnie): `GET /api/meta` zwraca `tryb_ai: OFF`, żadne zapytanie nie idzie do modelu,
  a każda funkcja działa w wersji bez AI (szablony i reguły). HR partner wyłączony: `funkcje_ai.hr_partner: false`,
  `GET …/hr-partner` → `409 HR_PARTNER_WYLACZONY`.
- `EvaluationOut.terminy` (`TerminOut[]`): wszystkie terminy oceny liczone automatycznie (`app/domain/timeline.py`):
  kryteria, sporządzenie oceny, zapoznanie („niezwłocznie”), a po podpisie ocenianego – sprzeciw, kolejna ocena
  (24 mies. albo ponowna po negatywnej) i kryteria na kolejny okres. Każdy z podstawą prawną.

### Sprzeciw (art. 83)

Akcje `POST /api/evaluations/{id}/actions/{akcja}` (body `ActionIn`):

| Akcja | Kto | Body | Skutek |
|---|---|---|---|
| `ZLOZ_SPRZECIW` | oceniany, do 7 dni od zapoznania | `komentarz` (treść, wymagana) | status `SPRZECIW`; termin rozpatrzenia 14 dni (`sprzeciw.termin_rozpatrzenia`) |
| `ROZPATRZ_SPRZECIW` | rozpatrujący z ustawień urzędu (`sprzeciw.rozpatruje`, domyślnie `kadry`; ustawowo dyrektor generalny) | `uwzglednij` (wymagane), `tryb` (wymagany przy uwzględnieniu: `ZMIANA_OCENY` / `PONOWNE_SPORZADZENIE`), `komentarz` (uzasadnienie, wymagane) | uwzględniony → `ROZMOWA_OCENIAJACA` (polecenie dla oceniającego, automatycznie rozpoczęty kolejny cykl usuwany); nieuwzględniony → `ZAKONCZONA` + `sprzeciw.termin_odwolania_do_sadu` (14 dni) |

Uwzględnienie sprzeciwu (art. 83 ust. 4, przypadki użycia KPRM) – oba tryby wykonuje oceniający (Poradnik KPRM):
- `ZMIANA_OCENY`: oceniający zastępuje kwestionowane fragmenty i klika `ZATWIERDZ_OCENE` – ocena od razu wraca do
  `ZAKONCZONA` z pierwotną datą sporządzenia i zapoznania (bez ponownego zapoznania i bez kolejnego sprzeciwu);
- `PONOWNE_SPORZADZENIE`: ocena jest anulowana (`data_sporzadzenia` pusta), wraca do etapu rozmowy oceniającej;
  po `ZATWIERDZ_OCENE` → `OCENA_DO_ZAPOZNANIA`, od tej oceny przysługuje kolejny sprzeciw.

W obu trybach ocena cząstkowa nie może spaść poniżej tej sprzed sprzeciwu (walidacja `SPRZECIW_OBNIZENIE`, `BLAD`), a
zmiana musi coś zmienić (`SPRZECIW_BRAK_ZMIAN`). Termin wykonania: 14 dni od wniesienia sprzeciwu (`termin_wykonania`,
ostrzeżenie `SPRZECIW_PO_TERMINIE`). Powiadomienia (`GET /api/notifications`, e-mail z `notify_job`):
`SPRZECIW_UWZGLEDNIONY` / `SPRZECIW_NIEUWZGLEDNIONY` (oceniany), `POLECENIE_ZMIANY_OCENY` /
`POLECENIE_PONOWNEGO_SPORZADZENIA` (oceniający), `OCENA_ZMIENIONA` / `OCENA_SPORZADZONA_PONOWNIE` (oceniany i kadry).

`EvaluationOut.sprzeciw`: `zlozony`, `tresc`, `termin_rozpatrzenia`, `decyzja`, `rozstrzygnieto`, `uzasadnienie_decyzji`,
`termin_odwolania_do_sadu`, `tryb`, `termin_wykonania`, `wykonano`, `przed_sprzeciwem` (wynik, średnia, punkty i data
oceny sprzed decyzji; `anulowana` przy ponownym sporządzeniu).

### Zaproszenie na rozmowę (opcjonalne)

| Metoda i ścieżka | Kto | Wejście | Uwagi |
|---|---|---|---|
| `POST /api/evaluations/{id}/zaproszenia` | oceniający / zastępca | `rodzaj` (`ROZMOWA_KRYTERIA` na etapie kryteriów, `ROZMOWA_OCENIAJACA` od potwierdzenia kryteriów), `termin` (czas urzędu), `czas_min` (15–240), `miejsce`, `uwagi` | 201; ponowne wysłanie tego samego rodzaju = zmiana terminu (ten sam UID w kalendarzu, `wersja`+1) |
| `GET /api/evaluations/{id}/zaproszenia` | kto widzi ocenę | – | lista |
| `GET /api/evaluations/{id}/zaproszenia/{n}.ics` | kto widzi ocenę | – | plik iCalendar (RFC 5545, strefa Europe/Warsaw) |
| `POST /api/evaluations/{id}/zaproszenia/{n}/odwolaj` | oceniający / zastępca | – | `METHOD:CANCEL` |

Zaproszony dostaje powiadomienie `ZAPROSZENIE` / `ZAPROSZENIE_ODWOLANE`, a `notify_job` wysyła e-mail z plikiem .ics.

### Asystent i HR partner: UC1, UC4, UC5, UC7

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| 🟢 `POST /api/evaluations/{id}/ai/suggest-criteria` | `SuggestCriteriaIn` (opcjonalnie: `opis` obowiązków) | `SuggestCriteriaOut` | maks. 3, nic nie ustawia samo |
| 🟢 `POST /api/evaluations/{id}/ai/conversation-prep` | `?rodzaj=OCENIAJACA` | `ConversationPrepOut` | notatka na rozmowę; bez punktów |
| 🟢 `POST /api/evaluations/{id}/ai/draft` | `DraftIn` | `DraftOut` | szkic w całości; strumieniowanie (SSE) jest w `AiSuggestionService.draft_stream`, ale endpoint go jeszcze nie używa |
| 🟢 `GET /api/evaluations/{id}/hr-partner` | – | `HrPartnerOut` | podpowiedzi dla przełożonego; także sygnały z historii (staż, trend ocen) z `dzialania_rozwojowe` – docs/asystent.md |
| 🟢 `POST /api/hr-signals/{id}/decision` | `HrSignalDecision` | 204 | akceptuj / odrzuć |

### Nieobecności i terminy: UC3, UC8 🟡

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| `GET /api/employees/{id}/absences` | – | `AbsenceOut[]` | |
| `POST /api/employees/{id}/absences` | `AbsenceIn` | `AbsenceOut` 201 | kadry albo oceniający; wymaga otwartego cyklu (`409 BRAK_CYKLU`); może automatycznie przesunąć termin – wtedy `zmiana_terminu` (DeadlineChange `AUTO`), nowy termin w `termin_oceny` |
| `GET /api/evaluations/{id}/deadline-changes` | – | `DeadlineChangeOut[]` | |
| `POST /api/evaluations/{id}/deadline-changes` | `DeadlineChangeIn` | `DeadlineChangeOut` 201 | wniosek ocenianego albo zmiana przez oceniającego |
| `POST /api/deadline-changes/{id}/decision` | `{status}` | `DeadlineChangeOut` | |
| `POST /api/employees/{id}/position-changes` | `PositionChangeIn` | `PositionChangeOut` | zmiana stanowiska: nowe kryteria w 30 dni albo ocena w oknie −7/+30 dni (`EvaluationService.register_position_change`) |

Termin sprzeciwu (`CzescII.termin_sprzeciwu`) = `EvaluationService.objection_deadline(id)`; zasady wszystkich
terminów i ich źródła: [`terminy.md`](terminy.md).

### Kadry: import starych ocen, archiwum, e-Akt

Wszystkie tylko dla `kadry` (inni: 403). Widoki: `#/import`, `#/archiwum`; status e-Akt w widoku oceny.

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| `POST /api/legacy-import` | plik (multipart: PDF / tekst arkusza) | szkic 201 | odczyt pól, przeliczenie § 11, `rozbieznosci` (`BLAD` blokuje) |
| `GET /api/legacy-import`, `GET /api/legacy-import/{id}` | – | szkice | |
| `PUT /api/legacy-import/{id}` | poprawione pola (`pracownik_id`, daty, `srednia`, `poziom`, `wynik`, `punkty`) | szkic | sprawdzany ponownie |
| `POST /api/legacy-import/{id}/approve` | `{akceptuje_rozbieznosci}` | szkic `ZATWIERDZONY` | zakończony cykl z `zaimportowana: true`; w historii pracownika `zrodlo: IMPORT`; poza raportem postępu |
| `GET /api/legacy-import/{id}/file` | – | oryginalny plik | |
| `POST /api/archive/run` | – | `{zamrozono: [...]}` | zamraża zamknięte oceny (dane + PDF, SHA-256) |
| `GET /api/archive` | – | rekordy (`pracownik`, `sha256_pdf`, `zgodny`) | |
| `GET /api/archive/review` | – | pozycje po okresie przechowywania (`AKTA` / `NOTATKI`) | nic nie jest usuwane samo |
| `GET /api/archive/{id}/pdf` | – | PDF | |
| `POST /api/archive/{id}/delete`, `POST /api/archive/notes/{evaluation_id}/delete` | `{zatwierdzam: true}` | | tylko po okresie przechowywania (409), bez zgody 422 |
| `POST /api/admin/eakt/retry` | – | `{ponowiono: [...]}` | ponawia nieudane eksporty; status: `eksport_eakt` w `GET /api/evaluations/{id}` |
| `GET /api/admin/ezd` | – | `{tryb, jrwa, dokumenty: [...]}` | rejestracje w EZD: arkusz po zapoznaniu / rozpatrzeniu sprzeciwu, pismo o zmianie terminu |
| `POST /api/admin/ezd/retry` | – | `{ponowiono: [...]}` | ponawia nieudane rejestracje (`EZD_MODE`: off / katalog / http) |
| `GET /api/kadry/zadania` | – | zadania | `DWIE_NEGATYWNE`, `STOPIEN_OBLIGATORYJNY`, `WNIOSEK_O_STOPIEN` (wniosek z części III; kadry dostają też powiadomienie przy sporządzeniu oceny) |

### Kadry: pracownicy wprowadzani ręcznie

Te same reguły co import z systemu kadrowego (`app/infrastructure/hr_import.py`). Widok: `#/pracownicy` („Dodaj
pracownika”, na karcie „Edytuj dane” i „Usuń dane pracownika”).

| Metoda i ścieżka | Wejście | Uwagi |
|---|---|---|
| `GET /api/admin/employees/{id}` | – | dane w kształcie formularza (`EmployeeForm`) |
| `POST /api/admin/employees?uruchom_cykl=` | `EmployeeForm` (`imie`, `nazwisko`, `stanowisko` wymagane; `przelozony` = id z kontraktu) | 201; `id` tworzone z imienia i nazwiska; 422 z listą problemów |
| `PUT /api/admin/employees/{id}` | `EmployeeForm` | zmiana podległości; osoba z oceną w toku → 409 (`Zmiana oceniającego`, art. 81 ust. 8 pkt 1) |
| `GET /api/admin/employees/{id}/usuniecie?data_ustania_zatrudnienia=` | – | co zostanie zarchiwizowane / usunięte i co blokuje |
| `POST /api/admin/employees/{id}/usuniecie` | `{data_ustania_zatrudnienia, zatwierdzam: true}` | zamknięte oceny do archiwum, reszta danych i konta usunięte, zostaje zapis bez danych osobowych; blokady → 409 |

### Raporty: zestawienie dla systemu sprawozdawczego

| Metoda i ścieżka | Parametry | Uwagi |
|---|---|---|
| `GET /api/reports/zestawienie.csv` | `rok`, `komorka`, `od`, `do` (data sporządzenia), `dane_osobowe` | jedna ocena = jeden wiersz (terminy i ich dotrzymanie, wynik, sprzeciw i tryb, wniosek o stopień); CSV `;` z BOM |
| `GET /api/reports/zestawienie.json` | jw. | pakiet z `wersja_formatu`, zakresem i datą wygenerowania |

Bez `dane_osobowe=true` osoby mają stały pseudonim `P-…` (HMAC z `SECRET_KEY`); nazwiska tylko dla kadr (403 dla innych).
Zakres jak w pozostałych raportach (kadry – urząd, przełożony – jego zespół).

### Tylko demo

| Metoda i ścieżka | Wejście | Wyjście | Uwagi |
|---|---|---|---|
| 🟢 `GET /api/demo/clock` | – | `ClockOut` | |
| 🟢 `POST /api/demo/clock` | `ClockIn` | `ClockOut` | „przewiń czas”: uruchamia przypomnienia |
| 🟢 `POST /api/demo/reset` | – | 204 | seed od nowa |

## Do uzgodnienia między zespołami

1. **Trzy słowniki statusów.** Model danych ma `StatusOceny` (`KRYTERIA_DO_WYZNACZENIA` … `ZAKONCZONA`, `SPRZECIW`,
   `ANULOWANA`), domena (`app/domain/cycle.py`) ma `Status` z wartościami z `server/data/kprm/reguly.json`
   (`cykl_rozpoczety` … `ocena_zapoznana`). **Propozycja:** kanoniczny jest `StatusOceny` z modelu danych
   (ma etapy oczekiwania i sprzeciw); aktualizujemy `reguly.json["statusy_procesu"]` i `Status` w domenie.
   Do tego czasu mapowanie w warstwie `app/api`.
2. **Identyfikatory:** domena używa `str`, model danych `int` – API wystawia `int`.
3. **Kryteria:** model danych zakłada `config/kryteria.yaml`, a dane leżą w `server/data/kprm/kryteria.json`
   (ze wskaźnikami behawioralnymi). Propozycja: jedno źródło – JSON z `server/data/kprm`, kody wielkimi literami
   (`RZETELNOSC`) jako alias `id` (`rzetelnosc`).
4. **Wynik oceny:** w modelu danych `wynik = POZYTYWNA dla NA_POZIOMIE i wyżej` – brakuje warunku § 11 ust. 1 pkt 4:
   **jakakolwiek ocena cząstkowa = 1 → NEGATYWNA** (domena liczy to poprawnie).
5. **Notatka a sugestie AI:** `Note` ma jedno `criterion_kod` + `wydzwiek`. Na sugestie AI (`sugestie_ai`,
   `status_klasyfikacji`) potrzebna jest osobna tabela albo kolumna JSON w `Note`.
6. **Sygnały HR partnera** (`HrSignal`) nie mają encji w modelu danych – na demo mogą być liczone w locie
   (bez zapisu decyzji) albo dostać tabelę 🟡.
