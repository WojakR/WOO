# Zadanie: Cyfrowy Asystent Ocen Okresowych (KPRM, zadanie 14)

Pełna treść, regulamin i materiały: `hakaton/dane/KPRM - Cyfrowy Asystent Ocen Okresowych/` (poza repo).
Dane domenowe w repo: `../server/data/kprm/` (opis: `server/data/README.md`).

## Instytucja i problem
- KPRM, Departament Służby Cywilnej. Ocena okresowa (co 24 miesiące, ok. 123 tys. osób w ok. 1740 urzędach)
  jest robiona na papierze i traktowana jak formalność. Przełożonym brakuje wsparcia w wyborze kryteriów,
  rozmowach, informacji zwrotnej i planowaniu rozwoju.

## Użytkownik (kto klika?)
- Oceniający (bezpośredni przełożony) – główny użytkownik.
- Oceniany – potwierdza kryteria i zapoznanie z oceną.
- Kadry / administrator – terminy, korekty, statystyki.

## Scenariusz demo (jedno zdanie)
- Przełożony prowadzi ocenę Grzegorza od wyznaczenia kryteriów do PDF-a, a asystent pilnuje terminów
  i przepisów, podpowiada kryteria, przygotowuje rozmowę, pisze szkic uzasadnienia i sygnalizuje przeciążenie.

## MVP: co MUSI działać na demo (zrobione)
- [x] UC1 Wyznaczenie kryteriów (arkusz A/B/C z konfiguracji, maks. 3 dodatkowe bez powtórzeń, termin +24 mies.) + AI podpowiada kryteria
- [x] UC2 Potwierdzenie przez ocenianego, blokowanie pól
- [x] UC3 Przypomnienia o terminach (przycisk „przewiń czas”)
- [x] UC4 Przygotowanie do rozmowy oceniającej z notatek (AI)
- [x] UC5 Ocena: macierz 1/3/5/7/9, średnia, poziom, pozytywna/negatywna (§ 11), walidacje + AI szkic uzasadnienia i IPRZ
- [x] UC6 Zapoznanie się z oceną + PDF zgodny ze wzorem
- [x] UC7 Wirtualny HR partner: sygnały przeciążenia, rekomendacje, momenty do docenienia
- [x] UC8 Przesunięcie terminu przez nieobecność > 1 mies.
- [x] UC9 Wniosek o kolejny stopień służbowy (część III)

Zadania dla agentów: `server/tasks/kprm-demo.json` (demo), `server/tasks/kprm-wdrozenie.json` (dalsze wdrożenie, T1–T24).

## Zrobione ponad MVP
Pierwotnie wyłączone z zakresu, ostatecznie zrealizowane (szczegóły: `../TODO.md`, `docs/api.md`, `docs/terminy.md`):
- Sprzeciw (7 dni od zapoznania), rozpatrzenie przez dyrektora generalnego / organ nadrzędny; po uwzględnieniu
  dwa tryby z przypadków użycia KPRM: zmiana oceny albo jej anulowanie i ponowne sporządzenie (bez obniżania ocen
  cząstkowych), z powiadomieniami; fikcja zapoznania przy odmowie podpisu.
- Powiadomienia o zdarzeniach (w aplikacji i e-mailem): rozstrzygnięcie sprzeciwu, zmiana / ponowne sporządzenie
  oceny, wniosek o kolejny stopień służbowy (do kadr), zaproszenie na rozmowę z plikiem .ics do kalendarza.
- Zastępstwa (zastępca oceniającego, nieobecność przełożonego), zmiana terminu z pismem PDF,
  zmiana stanowiska i zmiana oceniającego.
- Historia ocen pracownika, import starych ocen z PDF (z podglądem i zatwierdzeniem przez kadry),
  import danych kadrowych CSV/XLSX, import danych RCP; ręczne dodawanie i edycja pracownika (z podległością
  służbową) oraz usunięcie danych pracownika po ustaniu zatrudnienia (oceny zostają w archiwum).
- Sprawozdawczość: postęp ocen w urzędzie, wyniki, analiza potrzeb szkoleniowych (także CSV), dashboard;
  zestawienie wszystkich ocen dla systemu sprawozdawczego i kontroli (CSV / JSON, domyślnie z pseudonimami).
- Logowanie z hasłem i sesją (`AUTH_MODE=session`), dziennik zmian, przypomnienia e-mailem,
  archiwizacja z okresami przechowywania, wersjonowanie wymagań przez administratora, baza wiedzy w UI,
  lista kontrolna objawów wypalenia, eksport arkuszy do e-Akt i rejestracja dokumentów w EZD (paczki importu:
  PDF + metadane), asystent AI także przez zewnętrzny model (`AI_MODE=api`, z pseudonimizacją).

## Poza zakresem (świadomie nie robimy)
- Bezpośrednia (online) integracja z systemem kadrowym – dziś import plików i formularz.
- Wysyłka do e-Akt i EZD przez API usług – adaptery HTTP to szkielety, czekają na specyfikację od dostawców
  (listy pytań w `app/infrastructure/eakt.py` i `app/infrastructure/ezd.py`); działa tryb katalogowy.
- Podpis elektroniczny – obieg papierowy: wydruk PDF i rejestracja daty podpisu.

## Dane (skąd, format, czy syntetyczne)
- `server/data/kprm/*.json` – kryteria, arkusze, reguły, terminy (z rozporządzenia i ustawy).
- `server/data/kprm/pracownicy.json` – fikcyjne osoby z przykładowych arkuszy KPRM.
- `server/data/kprm/wiedza/` – teksty przepisów i poradnika KPRM do RAG; `przyklady/` – 11 wypełnionych arkuszy.
