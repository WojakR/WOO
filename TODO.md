# TODO – dalsze wdrażanie systemu ocen okresowych (wg `specyfikacja_systemu_ocen_okresowych.txt`)

Wszystkie pozycje poniżej są zrealizowane. Stan sprawdzony na `main` (76b248d, PR #35) 22.11.2026.
Co zostaje na dalsze wdrożenie (po hackathonie) – sekcja 5 na końcu.
Legenda: `[x]` zrobione · `[ ]` do zrobienia

## 0. Fundamenty wdrożenia
- [x] Trwała baza danych – SQLModel, `app/infrastructure/sql_store.py`, stan przeżywa restart (PR #19)
- [x] Logowanie i sesja (`AUTH_MODE=session`, `app/api/auth.py`, konta: `python -m app.api.auth add`; z PR #28) **[T1]**
- [x] Tryb produkcyjny (`APP_MODE=production`): zegar Europe/Warsaw, bez `/api/demo/*` i bez seeda **[T2]**
- [x] Dziennik zmian – tabela `dziennik_zmian` (tylko dopisywanie), `GET /api/evaluations/{id}/audit` dla kadr, zakładka „Historia zmian” **[T3]**
- [x] Przypomnienia e-mailem – `python -m app.application.notify_job` (SMTP z `.env`, bez duplikatów, w godzinach pracy, wyłącznik użytkownika) **[T4]**
- [x] Import z systemu kadrowego CSV/XLSX z podglądem i raportem błędów (`POST /api/admin/employees/import`) **[T5]**

## 1. Proces i harmonogram

### Cykl standardowy (24 mies.)
- [x] Kryteria do 30 dni, potwierdzenie przez ocenianego, blokady pól, rozmowa, ocena, zapoznanie
- [x] Przypomnienia przed terminami (konfigurowalne – PR #21)
- [x] Wstępny arkusz – PDF z oznaczeniem wersji roboczej przed zatwierdzeniem
- [x] Kolejny cykl startuje sam po zapoznaniu, od daty sporządzenia oceny (PR #22)
- [x] Termin w dzień wolny → pierwszy dzień roboczy
- [x] Historia ocen – `GET /api/employees/{id}/evaluations`, karta pracownika **[T6]**

### Wyjątki / przesunięcia terminów
- [x] Nieobecność > 1 mies. przesuwa termin (art. 81 ust. 7; reguła „ciągła, dłuższa niż miesiąc” opisana i przetestowana w `docs/terminy.md`). Uwaga: specyfikacja mówi o **łącznej > 30 dni** – kod idzie za ustawą; potwierdzić z KPRM, czy to zostaje
- [x] Zmiana terminu (art. 81 ust. 8) + pismo PDF (§ 8); planowana nieobecność oceniającego z podpowiedziami **[T7]**. Uwaga: ustawa daje decyzję oceniającemu – domyślnie działa od razu; zatwierdzanie przez kadry to ustawienie urzędu `zmiana_terminu.zatwierdza=KADRY`
- [x] Nieobecność przełożonego – zastępca albo zmiana terminu (`POST /api/evaluator-absences`) **[T7]**
- [x] Zmiana stanowiska – `POST /api/employees/{id}/position-changes`, zmiana arkusza przed kryteriami, przycisk w ocenie **[T8]**
- [x] Zmiana oceniającego – `POST /api/employees/{id}/evaluator-change` (art. 81 ust. 8 pkt 1, § 9 ust. 3; próg liczony od ostatniej oceny, jak w ustawie), notatki poprzednika wstrzymane do przekazania **[T9]**

### Skutki oceny
- [x] Po negatywnej: kryteria w 7 dni, ponowna ocena po 6 mies. od zapoznania (PR #13, #22)
- [x] 2 negatywne z rzędu – ostrzeżenie przy zatwierdzaniu i zadanie dla kadr (art. 71 ust. 1 pkt 1, nie art. 72) **[T10]**
- [x] Wniosek o kolejny stopień (część III, art. 89 ust. 1) z blokadą przy negatywnej i przy stopniu 9, część III w PDF **[T11]**
- [x] 2 kolejne oceny w dwóch najwyższych poziomach → obligatoryjny kolejny stopień (art. 89 ust. 2), zadanie i powiadomienie dla kadr (w aplikacji i e-mailem) + przypomnienia 7 dni i 1 dzień przed terminem 30 dni, do wpisania nowego stopnia **[T12]**
- [x] Status urzędnik / pracownik z danych kadrowych (API i PDF) **[T5]**

### Odwołania (sprzeciw)
- [x] Złożenie sprzeciwu w 7 dni od zapoznania, rozpatruje dyrektor generalny (ustawienie urzędu), uchylenie wraca do oceniającego (PR #23)
- [x] Termin sprzeciwu liczony od powrotu do pracy, gdy pracownik był nieobecny (`EvaluationCycle.objection_start`) **[T13]**
- [x] Przypadek brzegowy: oceniany = kierownik urzędu / brak organu w urzędzie → organ nadrzędny lub ponowne rozpatrzenie (`app/domain/objection.py`) **[T13]**
- [x] Uwzględnienie sprzeciwu: zmiana oceny albo ponowne sporządzenie (art. 83 ust. 4), z powiadomieniami (PR #34)

## 2. Arkusze, kryteria, punktacja
- [x] Arkusze A/B/C, kryteria dodatkowe (maks. 3, bez powtórzeń), § 11, uzasadnienie obowiązkowe przy negatywnej
- [x] AI: propozycje kryteriów dodatkowych, szkic uzasadnienia i IPRZ
- [x] Automatyczny dobór arkusza ze stanowiska (C > B > A), zmiana tylko przez kadry z uzasadnieniem (`app/domain/sheet_choice.py`) **[T14]**

## 3. Wellbeing / wypalenie
- [x] Sygnały przeciążenia – HR partner z notatek, nieobecności i wskaźników RCP **[T16]**
- [x] Lista kontrolna 8 objawów podczas rozmowy (karta „Dobrostan”, niewidoczna dla ocenianego) **[T15]**

## 4. Wymagania funkcjonalne

### Panele, raporty, AI
- [x] Panel postępu – przełożony i cała organizacja (Raporty → Postęp ocen) **[T17]**
- [x] Dashboard analityczny z wykresami i filtrem po ocenach (Raporty → Wyniki ocen, grupy < 5 osób ukryte) **[T18]**
- [x] Analiza potrzeb szkoleniowych z eksportem CSV **[T19]**
- [x] Zestawienie ocen dla sprawozdawczości i kontroli (`/api/reports/zestawienie.csv|json`, pseudonimy) (PR #34)
- [x] AI: kryteria, sformułowania do uzasadnień, wskazówki HR partnera
- [x] „Guzik wyłączenia” AI – dla urzędu i dla użytkownika (PR #24)
- [x] Notatki przełożonego – dodawanie, edycja, usuwanie (PR #14)

### Obieg papierowy, integracje, archiwum
- [x] Wydruk formularza zgodnego ze wzorem (PDF)
- [x] Rejestracja daty wydruku i daty podpisu na papierze → termin sprzeciwu + przypomnienia; fikcja zapoznania (`FIKCJA_ZAPOZNANIA`) **[T13]**
- [x] Zaproszenia na rozmowy z plikiem .ics (PR #34)
- [x] Integracja RCP – import CSV/XLSX, do HR partnera trafiają tylko wskaźniki zbiorcze **[T16]**
- [x] Integracja e-Akt i EZD – tryb katalogowy z metadanymi i ponawianiem (PR #34) **[T24]**
- [x] Archiwizacja i okresy przechowywania – zamrożona kopia + PDF z SHA-256, usuwanie tylko za zgodą administratora **[T22]**
- [x] Import starych ocen z PDF / tekstu z weryfikacją wg § 11 **[T23]**

### Administracja i hierarchia
- [x] Baza wiedzy – przepisy, podręcznik i samouczek w zakładce „Pomoc”, znak „?” przy polach arkusza **[T21]**
- [x] Edycja wymagań przez administratora z wersjonowaniem i datą wejścia w życie – trwające oceny liczą się wg swojej wersji **[T20]**
- [x] Progi i częstotliwość przypomnień – urząd i użytkownik (PR #21)
- [x] Wgląd hierarchiczny – poddrzewo albo bezpośredni (ustawienie urzędu), zastępcy, `AccessPolicy` (PR #18)
- [x] Pracownicy i podległość wprowadzane ręcznie w UI (dodanie, edycja, usunięcie danych) (PR #34) **[T5]**, **[T6]**
- [x] Widok „Pracownicy” – lista z filtrami, karta, import dla kadr **[T6]**

## 5. Dalsze wdrożenie (po hackathonie)
- [ ] Wysyłka do e-Akt i EZD przez API – adaptery HTTP czekają na specyfikację dostawców (`app/infrastructure/eakt.py`, `ezd.py`)
- [ ] Bezpośrednia integracja z systemem kadrowym (dziś import plików i formularz)
- [ ] Podpis elektroniczny (dziś wydruk PDF i rejestracja daty podpisu)
- [ ] Potwierdzić z KPRM regułę nieobecności: ustawa – ciągła, dłuższa niż miesiąc (tak liczy kod); specyfikacja – łącznie > 30 dni
- [ ] Dostosowanie do nowelizacji ustawy o służbie cywilnej (nowa wersja przepisów w Ustawieniach)
