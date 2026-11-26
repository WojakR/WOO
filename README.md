# Cyfrowy Asystent Ocen Okresowych

**System, który prowadzi urząd przez cały 24-miesięczny cykl oceny okresowej w służbie cywilnej – pilnuje przepisów,
terminów i skutków kadrowych, a asystent AI pomaga przełożonemu przygotować rozmowę i napisać ocenę.**

Projekt zespołu **bEEd** na hackathon **HackNation 2026**, zadanie Kancelarii Prezesa Rady Ministrów
(Departament Służby Cywilnej). [Prezentacja konkursowa na YouTube](https://youtu.be/3NeZ1WR35dY).

![Demo: Cyfrowy Asystent Ocen Okresowych](docs/asystent-ocen-demo.gif)

<sub>Demo na danych fikcyjnych, nagrane w trybie bez modelu AI – szkice pochodzą z szablonów.</sub>

## Problem

Ocena okresowa obejmuje ok. **123 tys. członków korpusu służby cywilnej w ok. 1740 urzędach** i powtarza się co
24 miesiące. Dziś odbywa się na papierze i bywa traktowana jak formalność:

- przełożeni nie mają wsparcia przy doborze kryteriów, rozmowie, uzasadnieniu i planie rozwoju pracownika;
- terminy wynikają z ustawy i rozporządzenia, przesuwają się przy nieobecnościach i zmianach stanowisk – łatwo je przeoczyć;
- skutki ocen (ponowna ocena, stopień służbowy, sprzeciw) giną w dokumentach, a kadry nie mają obrazu całego urzędu;
- małe urzędy nie mają działu IT, a dane o ocenach są wrażliwe.

## Co robi system

Formularz oceny to najmniejsza część. Wartość polega na tym, że system prowadzi **cały cykl** – dla oceniającego,
ocenianego i działu kadr.

| Problem urzędu | Co robi system |
|---|---|
| Terminy łatwo przeoczyć | Liczy je według ustawy (dni wolne, nieobecności, zmiana stanowiska), przypomina w aplikacji i e-mailem, eksportuje do kalendarza (.ics) |
| Ocena bywa formalnością | Zbiera notatki przełożonego z całego okresu, przygotowuje rozmowę oceniającą, podpowiada oceny z dowodami i pisze szkic uzasadnienia oraz planu rozwoju (IPRZ) |
| Przeciążenie widać za późno | Wirtualny HR partner łączy notatki, historię ocen, dane o czasie pracy i listę kontrolną wypalenia; wskazuje też osoby, które warto docenić |
| Skutki oceny giną w papierach | Po ocenie sam tworzy zadania: ponowna ocena po negatywnej, obowiązkowy stopień służbowy, wniosek o kolejny stopień, nowy cykl |
| Spory wymagają dowodów | Obsługuje sprzeciw i jego rozstrzygnięcie, odmowę podpisu, dziennik zmian i archiwum z sumą kontrolną SHA-256 |
| Ludzie zmieniają stanowiska | Zastępstwa, zmiana przełożonego z przekazaniem notatek, zmiana stanowiska bez utraty historii |
| Nowelizacja psuje procesy | Przepisy są wersjonowane z datą wejścia w życie, a trwające oceny zostają przy swojej wersji |
| Kadry nie mają obrazu całości | Postęp ocen w urzędzie, rozkład wyników, porównanie komórek, mapa potrzeb szkoleniowych, zestawienia do sprawozdań |
| Brak IT i wrażliwe dane | Działa na jednym komputerze, lokalnie; AI na modelu lokalnym, a przy modelu zewnętrznym dane są pseudonimizowane |

Do tego: arkusz A/B/C dobierany automatycznie, wynik liczony na żywo według § 11 rozporządzenia, PDF zgodny ze
wzorem, import danych kadrowych, czasu pracy i starych ocen z PDF/skanów (OCR), paczki do e-Akt i EZD.
Wszystkie 9 przypadków użycia z zadania KPRM jest zrealizowanych, a także większość rozszerzeń
([zakres](docs/task.md)).

## Decyzje projektowe

- **AI tylko proponuje.** Każdą podpowiedź przełożony przegląda i zatwierdza – szkicu nie da się wstawić bez
  przeczytania, a zatwierdzenie etapu blokuje pola.
- **Wszystko działa bez AI.** Bez modelu szkice i podpowiedzi powstają z szablonów i reguł. Przy awarii modelu system
  przechodzi na kolejny z listy, a w ostateczności na szablony.
- **Dane osobowe nie opuszczają urzędu.** Domyślnie model lokalny ([Bielik](https://huggingface.co/speakleash) przez
  Ollamę). Wszystkie wywołania modelu idą przez jedną funkcję (`backend/llm.py`), która pseudonimizuje tekst – także
  odmienione polskie imiona i nazwiska, numery telefonów i zapis bez polskich znaków.
- **Przepisy jako dane, nie kod.** Kryteria, arkusze, skala, progi i 15 terminów są w plikach JSON
  ([`data/kprm/`](data/kprm/README.md)); decyzje urzędu (widoczność, rytm przypomnień, kto rozpatruje sprzeciw,
  minimalna wielkość grupy w raportach) w [`config/ustawienia_urzedu.json`](config/ustawienia_urzedu.json).
  Administrator zmienia je w panelu, z walidacją i zapisem, kto i dlaczego zmienił.
- **Architektura warstwowa.** Reguły oceny i terminów to czysty Python (`app/domain/`), oddzielony od przypadków użycia
  (`app/application/`), adapterów – baza, e-mail, e-Akt, EZD, modele AI (`app/infrastructure/`) – i API.
- **Trzy warianty wdrożenia.** Mały urząd: dwuklik w `Uruchom.bat`. Serwer urzędu: `docker compose up`. Większa
  instytucja: PostgreSQL zamiast SQLite. Logowanie z hasłem (scrypt) i rolami, tryb produkcyjny, dostępność (WCAG).
- **Testy prawa, nie tylko kodu.** Ok. 500 testów automatycznych, w tym wszystkie przykłady liczenia terminów z
  materiałów KPRM. CI (GitHub Actions) uruchamia testy oraz buduje i sprawdza obraz Dockera.

## Jak pracowaliśmy

Ok. 26 tys. linii Pythona i ponad 50 pull requestów w niecałą dobę hackathonu. Zespół pracował z agentami AI
(Claude Code) uruchomionymi równolegle na kilku komputerach: własny koordynator rozdzielał zadania i blokował pliki,
żeby agenci sobie nie przeszkadzali, a komputery łączyły się przez sieć ZeroTier. Ludzie projektowali, dzielili
pracę na zadania, przeglądali i scalali zmiany oraz weryfikowali logikę z przepisami.

## Zespół

| Osoba | Obszar |
|---|---|
| **Franek** ([Franio2018](https://github.com/Franio2018)) | Rdzeń domeny i kontrakt API, asystent AI (podpowiedzi, personalizacja z historii pracownika), cykl oceny i terminy, ustawienia administratora i wersjonowanie przepisów, funkcje wdrożeniowe (tryb produkcyjny, dziennik zmian, import kadr, skutki ocen), sprzeciw i integracja z EZD; infrastruktura pracy agentów na wielu komputerach |
| **Wojtek** ([WojakR](https://github.com/WojakR)) | Zgodność terminów z przepisami (przykłady KPRM jako testy), pseudonimizacja danych dla AI, API przygotowania rozmowy i szkiców, uprawnienia według struktury podległości i zastępstwa, przypomnienia, sprzeciw (art. 83), logowanie, uruchamianie jednym poleceniem, Docker i CI |
| **Nikola** ([Neonaaq](https://github.com/Neonaaq)) | Interfejs użytkownika (Streamlit): ekrany oceny, zespołu i pracownika, dashboard, archiwum, pomoc, panel administratora, wygląd i dane demo |
| **Amelia i Mateusz** | Konsulting i analiza biznesowa: analiza potrzeb klienta (rozmowy z pracownikami i kierownictwem), projekt działania systemu i jego funkcjonalności, dostosowanie konfiguracji do wymagań, testy zgodności z wymaganiami formalnymi i prawnymi, przekazywanie wymagań programistom |

## Szybki start

Wymagany [Python 3.10+](https://www.python.org/downloads/). Pobierz repozytorium i uruchom:

- **Windows:** dwuklik w `Uruchom.bat`
- **macOS / Linux:** `sh uruchom.sh`

Aplikacja otworzy się w przeglądarce z danymi przykładowymi. Scenariusz demo: jako **Henryk Pryncypał** otwórz ocenę
Grzegorza, przejrzyj sugestie, wstaw szkic uzasadnienia i zatwierdź ocenę; przełącz się na **Grzegorza Wzora**,
potwierdź zapoznanie i pobierz PDF arkusza. Panel demo pozwala też przesuwać zegar, żeby zobaczyć terminy i przypomnienia.

## Dokumentacja

- [Instalacja, uruchomienie i wdrożenie w urzędzie](docs/instalacja.md)
- [Podręcznik użytkownika](docs/podrecznik.md) (ten sam tekst jest w aplikacji w zakładce „Pomoc”)
- [Zadanie i zakres](docs/task.md)
- Techniczna: [API](docs/api.md) · [model danych](docs/model-danych.md) · [terminy](docs/terminy.md) ·
  [asystent AI](docs/asystent.md)

## Technologie

Python · FastAPI · Streamlit · SQLite / PostgreSQL · SQLModel · Ollama (Bielik) / LiteLLM · Tesseract OCR · Docker ·
pytest · GitHub Actions

## Licencja

[MIT](LICENSE)
