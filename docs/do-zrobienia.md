# Do zrobienia

Stan na 22.11.2026 (gałąź `chore/dead-code-cleanup`, po PR #36 i #37 – interfejsem aplikacji jest Streamlit,
`frontend/web` usunięty). Lista zbiera to, co jeszcze otwarte:
niezamknięte punkty z [`TODO.md`](../../TODO.md) i rzeczy znalezione przy przeglądzie demo, sprzątaniu kodu
i rozmowie o wdrożeniu w małym urzędzie. Zrobione rzeczy są w `TODO.md`; tutaj tylko to, co zostało.

Priorytet: **P1** przed prezentacją · **P2** wdrożenie pilotażowe · **P3** później.

## 0. Luki po usunięciu web UI (P1)

PR #37 usunął `frontend/web`; razem z nim zniknęły ekrany dodane w PR #36. Serwer je obsługuje, w Streamlicie
trzeba je dobudować albo sprawdzić:

- [x] UC1 „AI podpowiada kryteria” – w Streamlicie od PR #41: panel „Asystent AI: podpowiedz kryteria dodatkowe”
  przy kryteriach (`frontend/views/evaluation.py`, `_criteria_hint`), także bez AI (słowa kluczowe).
- [x] Oceniany w Streamlicie dociera do swoich kroków – sprawdzone: „Potwierdzam rozmowę i zapoznanie się
  z kryteriami”, „Potwierdzam zapoznanie się z oceną” (`frontend/views/employee.py`).

## 1. Otwarte punkty z `TODO.md`

- [ ] **P3** e-Akta: adapter HTTP (`EAKT_MODE=http`) czeka na specyfikację interfejsu od dostawcy; eksport do katalogu
  działa **[T24]**.
- [ ] **P3** Import starych ocen z PDF bez wsparcia AI przy odczycie – reguły na strukturze wzoru i ekran weryfikacji
  działają, trudne skany wymagają ręcznej poprawki **[T23]**.
- [ ] **P2** Potwierdzić z KPRM: nieobecność „ciągła, dłuższa niż miesiąc” (ustawa, tak liczy kod) czy „łącznie > 30 dni”
  (specyfikacja) – `docs/terminy.md`.
- [ ] **P2** Potwierdzić z KPRM: zmiana terminu (art. 81 ust. 8) działa od razu decyzją oceniającego; zatwierdzanie przez
  kadry to tylko ustawienie urzędu (`zmiana_terminu.zatwierdza=KADRY`).

## 2. Wdrożenie w małym urzędzie (4 osoby, bez IT, bez serwera)

Ustalony kierunek: aplikacja jako asystent jednej osoby (przełożony / kadry), podpis na papierze, przypomnienia
mailem i w kalendarzu. Jeden kod, dwa profile („małe biuro” / „duży urząd”) różniące się adapterami.

- [ ] **P2** Kreator pierwszego uruchomienia (strona w Streamlicie): nazwa urzędu, pracownicy, kto kogo ocenia, poczta; sam ustawia
  `APP_MODE=production`, `AUTH_MODE=session` i `SECRET_KEY`. Pytania z ich świata („Czy macie dział IT?”), bez żargonu.
- [ ] **P2** Zakładanie kont i reset haseł w UI dla kadr – dziś tylko `python -m app.api.auth add …` (ekran logowania
  mówi „konto nadaje dział kadr”).
- [ ] **P2** Zadanie w Harmonogramie zadań Windows dla `python -m app.application.notify_job` (codziennie 8:00,
  z opcją „uruchom po pominiętym starcie”) zakładane przez kreator; pasek „✅ terminy sprawdzone dziś / ⚠️ nie
  sprawdzano od N dni” na stronie głównej.
- [ ] **P2** Automatyczna kopia `data/app.db` przy zadaniu dziennym do wskazanego folderu (dysk sieciowy / OneDrive
  jako miejsce kopii, nigdy jako miejsce bazy) + przycisk „przywróć”.
- [ ] **P2** Przycisk „oznacz jako podpisane na papierze” kończący przypomnienia o danym kroku (sprawdzić, ile pokrywa
  już rejestracja daty podpisu z T13).
- [x] `.ics` z terminami: „Dodaj terminy do kalendarza (.ics)” w widoku „Terminy” (`GET /api/me/terminy.ics`;
  przypomnienia 7 dni i 1 dzień wcześniej, ponowny import aktualizuje wydarzenia).
- [ ] **P3** Komunikat „Termin się zmienił – pobierz kalendarz ponownie” po przesunięciu terminu (nieobecność,
  zmiana terminu); dziś użytkownik musi o tym pamiętać sam.
- [ ] **P3** „Użyj mojego Outlooka” zamiast SMTP – sprawdzić realnie: M365 często blokuje SMTP z hasłem, nowy Outlook
  nie ma COM.
- [ ] **P3** Paczka offline: Python embedded + biblioteki w jednym ZIP / instalatorze, bez pobierania z internetu
  i bez uprawnień administratora. Niepodpisany `.exe` wywoła SmartScreen – do rozważenia podpis kodu.
- [ ] **P3** Profil „duży urząd”: PostgreSQL (`DATABASE_URL` już działa), SSO (AD / Entra ID / Keycloak), osobny proces
  schedulera.
- [ ] **P3** AI na słabym laptopie: Bielik 11B Q4 potrzebuje ~7 GB RAM i jest za wolny na CPU. Dla małych urzędów
  `AI_MODE=off` albo centralny endpoint z anonimizacją; sprawdzić jakość mniejszych modeli po polsku.
- [ ] **P3** Dokumentacja dla urzędu: włączyć szyfrowanie urządzenia (Windows Home nie ma pełnego BitLockera).

## 3. Kod podłączony tylko częściowo – podłączyć albo usunąć

Przy sprzątaniu zostawione celowo: działa i ma testy, ale nic z aplikacji tego nie wywołuje.

- [ ] **P2** Strumieniowanie szkicu (SSE): `AiSuggestionService.draft_stream` i `backend.llm.stream_ollama` są gotowe,
  endpoint `POST /api/evaluations/{id}/ai/draft` zwraca tylko całość. Przy wolnym modelu lokalnym strumień bardzo
  poprawia odczucia – warto podłączyć (endpoint + `st.write_stream` w Streamlicie).
- [ ] **P3** `EvaluationService.meeting_prep` (UC4 w use case'ach) dubluje `AiSuggestionService.conversation_prep`,
  którego używa API – zostawić jedno.
- [ ] **P3** `backend.llm.ask_llm_json` – opisane w `CLAUDE.md`, używane tylko w testach (asystent idzie przez
  `app/infrastructure/ai_models.py`).
- [ ] **P3** Porty `WorkTimeSource` i `DocumentRegistry` w `app/application/ports.py` – adaptery istnieją, ale nikt nie
  odwołuje się do typów (opis interfejsu, nie kod) – zostawić jako dokumentację albo użyć w adnotacjach.
- [ ] **P3** Endpointy, z których nie korzysta już żaden interfejs po usunięciu `frontend/web` – porównać trasy z
  `app.openapi()` z wywołaniami w `frontend/api_client.py` i zdecydować: dobudować ekran albo zostawić jako API.
- [ ] **P3** `nieprzeczytane_powiadomienia` w `GET /api/dashboard` jest zawsze `0` – policzyć albo usunąć pole.

## 4. Dokumentacja i porządek

- [ ] **P2** `docs/api.md` nie opisuje ~40 istniejących endpointów (m.in. `/api/auth/*`, `/api/users`, raporty,
  `/api/knowledge`, `/api/ustawienia/urzad`, `/api/evaluations/{id}/wellbeing`, `…/sheet`, `…/paper`,
  `/api/employees/{id}/evaluations`, `/api/evaluator-absences`, `/api/admin/rcp/*`). Lista do odtworzenia skryptem
  porównującym `app.openapi()` z tabelą w `docs/api.md`.
- [ ] **P3** `app/api/state.py:329` – adnotacja `"RuleBook"` bez importu (ruff F821); dodać import pod
  `TYPE_CHECKING`.
- [ ] **P3** Testy `server/` wymagają pakietu `mcp`, którego nie ma w środowisku aplikacji – opisać w README osobne
  środowisko albo dodać do instrukcji.
- [ ] **P3** Teksty szablonów: „realizował(a)”, „wyróżnił(a) się” – płeć z danych kadrowych zamiast nawiasów.
- [ ] **P3** `docs/design.md` (w katalogu głównym) opisuje design system usuniętego `frontend/web/styles.css` –
  przepisać pod Streamlit (`frontend/ui.py`) albo usunąć.
- [ ] **P3** Start Streamlita na słabym laptopie: zmierzyć czas i pamięć `streamlit run frontend/app.py` (pomiar
  ~125 MB / 3–5 s dotyczył samego API przez uvicorn).

## 5. Prezentacja (P1)

- [ ] Ujednolicić historię podpisu przed pitchem: wiążący jest podpis na papierze (PDF do druku); podpis
  elektroniczny / Profil Zaufany tylko jako opcja dla urzędów z e-aktami. Notatka o architekturze wdrożenia
  (PIN ocenianego, Profil Zaufany) mówi inaczej niż ustalenia zespołu.
- [ ] Slajd „od 4 do 2000 osób”: tabela modułów (baza, logowanie, przypomnienia, dokumenty, AI) – ten sam kod,
  inne adaptery. Liczby do slajdu (samo API, i5 12. gen.): ~125 MB RAM, start 3–5 s, arkusz w ~45 ms – dla Streamlita
  zmierzyć osobno.
- [ ] Przejść cały scenariusz demo w Streamlicie na `main` po scaleniu tego PR (Henryk → Grzegorz → PDF, Barbara →
  Monika: kryteria i notatka na rozmowę).
