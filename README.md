# Cyfrowy Asystent Ocen Okresowych

**Aplikacja, która prowadzi przełożonego w służbie cywilnej przez całą ocenę okresową pracownika – od wyznaczenia
kryteriów do podpisanego arkusza PDF – a asystent AI pilnuje terminów i przepisów, podpowiada i pisze szkice.**

Projekt powstał na hackathonie **HackNation 2026** jako odpowiedź na zadanie Kancelarii Prezesa Rady Ministrów
(Departament Służby Cywilnej).

![Demo: Cyfrowy Asystent Ocen Okresowych](docs/asystent-ocen-demo.gif)

## Problem

Ocena okresowa w służbie cywilnej obejmuje ok. **123 tys. osób w ok. 1740 urzędach** i odbywa się co 24 miesiące.
Dziś to głównie papier i formalność: przełożeni nie mają wsparcia przy wyborze kryteriów, przygotowaniu rozmowy,
uzasadnieniu oceny i planowaniu rozwoju pracownika, a terminy i wymogi rozporządzenia łatwo przeoczyć.

## Rozwiązanie

Aplikacja odwzorowuje cały proces z rozporządzenia, dla trzech ról: **oceniającego**, **ocenianego** i **działu kadr**.

- **Arkusz oceny krok po kroku** – arkusze A/B/C, kryteria obowiązkowe i dodatkowe, skala 1–9, wynik liczony na żywo
  według § 11 rozporządzenia, walidacje i blokowanie pól na kolejnych etapach.
- **Asystent AI** – podpowiada kryteria, przygotowuje rozmowę oceniającą na podstawie notatek, pisze szkic
  uzasadnienia i indywidualnego programu rozwoju zawodowego (IPRZ).
- **Wirtualny HR partner** – wychwytuje sygnały przeciążenia i wypalenia, podpowiada momenty do docenienia pracownika.
- **Terminy i przypomnienia** – liczenie terminów zgodnie z przykładami KPRM (z nieobecnościami, zmianą stanowiska
  i oceniającego), przypomnienia w aplikacji i e-mailem, zaproszenia na rozmowę do kalendarza (.ics).
- **Pełny obieg** – zapoznanie z oceną, sprzeciw i jego rozpatrzenie, wniosek o kolejny stopień służbowy,
  PDF arkusza zgodny ze wzorem z rozporządzenia, archiwum z okresami przechowywania.
- **Dla kadr** – postęp ocen w urzędzie, dashboard, analiza potrzeb szkoleniowych, import danych kadrowych
  (CSV/XLSX), import starych ocen z PDF i skanów (OCR), eksport do e-Akt i EZD, zmiana przepisów bez zmian w kodzie.

## Ciekawe decyzje techniczne

- **Dane osobowe nie opuszczają urzędu.** Domyślnie AI działa na modelu lokalnym
  ([Bielik](https://huggingface.co/speakleash) przez Ollamę). Przy modelu zewnętrznym dane są pseudonimizowane
  przed wysłaniem – wszystkie wywołania modelu przechodzą przez jedno miejsce (`backend/llm.py`).
- **AI jest dodatkiem, nie warunkiem.** Bez modelu aplikacja działa w pełni – szkice i podpowiedzi powstają
  z szablonów i reguł. Przy awarii modelu następuje automatyczne przejście na kolejny model albo na szablony.
- **Przepisy jako dane, nie kod.** Kryteria, arkusze, reguły oceny i terminy są w plikach JSON
  ([`data/kprm/`](data/kprm/README.md)), wersjonowanych z datą wejścia w życie.
- **Czysta architektura.** Reguły oceny i terminów to czysty Python (`app/domain/`), oddzielony od przypadków użycia,
  adapterów (baza, e-mail, e-Akt, EZD, modele AI) i API.
- **Uruchomienie bez działu IT.** Mały urząd uruchamia aplikację dwuklikiem w `Uruchom.bat` – skrypt sam tworzy
  środowisko, instaluje zależności i otwiera przeglądarkę. Większy – jednym `docker compose up`.
- **Jakość.** Ok. 500 testów automatycznych (m.in. wszystkie przykłady liczenia terminów z materiałów KPRM),
  CI na GitHub Actions sprawdza testy oraz budowę i działanie obrazu Dockera.

## Technologie

Python · FastAPI · Streamlit · SQLite (opcjonalnie PostgreSQL) · Ollama / LiteLLM · Tesseract OCR · Docker ·
pytest · GitHub Actions

## Zespół

<!-- TODO: uzupełnić imiona i role -->
- **Imię Nazwisko** – rola, za co odpowiadał(a)
- **Imię Nazwisko** – rola, za co odpowiadał(a)

## Szybki start

Wymagany [Python 3.10+](https://www.python.org/downloads/). Pobierz repozytorium i uruchom:

- **Windows:** dwuklik w `Uruchom.bat`
- **macOS / Linux:** `sh uruchom.sh`

Aplikacja otworzy się w przeglądarce z danymi przykładowymi. Scenariusz demo: zalogowany jako **Henryk Pryncypał**
otwórz ocenę Grzegorza, przejrzyj sugestie, wstaw szkic uzasadnienia, zatwierdź ocenę, przełącz się na
**Grzegorza Wzora**, potwierdź zapoznanie i pobierz PDF arkusza.

## Dokumentacja

- [Instalacja, uruchomienie i wdrożenie w urzędzie](docs/instalacja.md)
- [Podręcznik użytkownika](docs/podrecznik.md) (ten sam tekst jest w aplikacji w zakładce „Pomoc”)
- [Zadanie i zakres](docs/task.md)
- Techniczna: [API](docs/api.md) · [model danych](docs/model-danych.md) · [terminy](docs/terminy.md) ·
  [asystent AI](docs/asystent.md)

## Licencja

[MIT](LICENSE)
