# HackNation 2026 – Cyfrowy Asystent Ocen Okresowych (projekt)

> Ten katalog to `projekt/` w monorepo: aplikacja konkursowa. Koordynator agentów jest w `../server/`,
> a dane domenowe KPRM w `../server/data/kprm/`. Zadanie i scenariusz demo: [`docs/task.md`](docs/task.md).

Python + FastAPI (API i aplikacja webowa) + SQLite + asystent AI (model lokalny przez Ollamę, z wersją bez AI).

**Najprościej (mały urząd, jeden komputer, bez Dockera i bez IT):** zainstaluj
[Pythona 3.10+](https://www.python.org/downloads/) (Windows: zaznacz „Add python.exe to PATH”), pobierz repozytorium
(`git clone` albo „Code → Download ZIP” i rozpakuj) i uruchom:

- **Windows:** dwuklik w `projekt\Uruchom.bat`
- **macOS / Linux:** `sh projekt/uruchom.sh`

Za pierwszym razem skrypt tworzy środowisko `.venv`, instaluje biblioteki (kilka minut, potrzebny internet) i plik
ustawień `.env`; potem start trwa kilka sekund. Aplikacja otwiera się w przeglądarce (http://localhost:8000; gdy port
jest zajęty – następny wolny). Zatrzymanie: zamknij okno albo Ctrl+C. Dane zostają w `projekt/data/app.db`.
Opcje: `--port 9000`, `--siec` (dostęp z innych komputerów w sieci urzędu), `--bez-przegladarki`.
Asystent AI nie jest potrzebny – bez modelu działają szablony i reguły.

**Dla programistów** (po instalacji z punktu 1, w katalogu `projekt/`):
```bash
uvicorn backend.main:app --reload
```
i otwórz **http://localhost:8000**. Szczegóły w punkcie 2.

```
backend/
  config.py     # wczytuje .env / st.secrets
  llm.py        # ask_llm(), ask_llm_json() – fallback po liście modeli
  parsers.py    # PDF, XML, CSV/XLSX, TXT, OCR -> tekst/dict/DataFrame
  db.py         # SQLite
  main.py       # FastAPI: /api/... + serwuje interfejs z frontend/web
  kprm.py       # jedyny czytelnik danych KPRM z ../server/data/kprm
app/
  domain/       # reguły oceny (§ 11), terminy, cykl oceny – czysty Python
  application/  # przypadki użycia UC1–UC5, asystent AI
  infrastructure/ # adaptery: dane KPRM, pamięć, modele AI
  api/          # endpointy /api (routes.py), dane demo (demo_state.py), schematy kontraktu
frontend/web/   # interfejs webowy (HTML/CSS/JS, bez budowania i bez CDN)
frontend/app.py # stare demo Streamlit (wgrywanie plików, pytania do LLM)
Uruchom.bat / uruchom.sh # start jednym poleceniem (wywołują scripts/uruchom.py)
scripts/
  uruchom.py       # .venv + biblioteki + .env + wolny port + przeglądarka
  check_setup.py   # sprawdza instalację i klucze
  gen_fake_data.py # dane syntetyczne
data/              # dane testowe (bazy .db nie są commitowane)
```

## 1. Instalacja (każdy, dziś wieczorem)

Wymagany Python 3.10+ (`python --version`) i git.

**Windows (PowerShell):**
```powershell
git clone https://github.com/Franio2018/Hacknation.git
cd Hacknation/projekt
python -m venv .venv
.venv\Scripts\Activate.ps1      # błąd o skryptach? -> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env
```

**macOS / Linux:**
```bash
git clone https://github.com/Franio2018/Hacknation.git
cd Hacknation/projekt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Aplikacja ocen działa bez żadnych kluczy. Klucze w `.env` są potrzebne tylko do `ask_llm()` (punkt 3) –
bez nich ustaw `LLM_MOCK=1`. Sprawdzenie instalacji:

```bash
python scripts/check_setup.py
```

Wszystko ma być ✅.

## 2. Uruchamianie

Wszystkie polecenia z katalogu `projekt/`, z aktywnym `.venv`.

```bash
uvicorn backend.main:app --reload        # aplikacja -> http://localhost:8000, API -> http://localhost:8000/docs
python -m pytest -q                      # testy (bez kluczy i bez modelu AI)
```

Port zajęty? `uvicorn backend.main:app --reload --port 8765` i otwórz http://localhost:8765.
Dostęp z innych komputerów w sieci urzędu: dodaj `--host 0.0.0.0` (i otwórz port w zaporze).

### Serwer urzędu w Dockerze

Na serwerze z Dockerem, w katalogu `projekt/`:

```bash
docker compose up -d          # buduje obraz i startuje -> http://<serwer>:8000
docker compose logs -f        # dziennik
docker compose down           # zatrzymanie; dane zostają w wolumenie "oceny-dane"
```

- Baza SQLite jest w wolumenie (`/data/app.db`), więc przetrwa restart i aktualizację obrazu
  (`git pull` + `docker compose up -d --build`). `docker compose down -v` usuwa też dane.
- Ustawienia: opcjonalny plik `.env` obok (wzór w `.env.example`). Inny port: `PORT=9000 docker compose up -d`.
- AI domyślnie wyłączone (szablony i reguły). Model lokalny: Ollama na tym samym serwerze i `AI_MODE=local`
  (kontener łączy się z `host.docker.internal:11434`).
- Obraz jest sprawdzany w CI (zadanie `docker`: budowa, start, odpowiedź API, dane po restarcie).

### Co zobaczysz

Aplikacja startuje z danymi przykładowymi (osoby z `server/data/kprm/pracownicy.json`, notatki z
`notatki_testowe.json`) i zegarem demo ustawionym na **25.05.2026**. Dane są zapisywane w bazie
(`data/app.db`) i przetrwają restart; przycisk ⟲ w górnym pasku przywraca stan początkowy.

- **Moje oceny** – przegląd: liczby, etapy procesu, tabela pracowników, panel „Wymaga uwagi”.
- **Otwórz** przy pracowniku – arkusz oceny: etapy, kryteria ze skalą 1–9, dowody z notatek i sugestie,
  wynik liczony na żywo (§ 11), uzasadnienie i wnioski IPRZ ze szkicem od asystenta, HR partner.
- **Terminy i przypomnienia** – terminy od najbliższego.

Górny pasek (tylko demo, zamiast logowania):
- **wybór osoby** – Henryk Pryncypał (oceniający Grzegorza), Grzegorz Wzór (oceniany), Dział kadr (wszyscy) itd.;
- **+7 dni / +30 dni** – przewija zegar serwera (terminy, przypomnienia);
- **⟲** – przywraca dane przykładowe.

Scenariusz demo: jako Henryk otwórz ocenę Grzegorza → przejrzyj sugestie → „Wstaw” szkic uzasadnienia i
wniosków IPRZ → „Zatwierdź ocenę i przekaż do zapoznania” → przełącz się na Grzegorza → „Potwierdzam
zapoznanie się z oceną”.

### Asystent AI (opcjonalnie)

Bez modelu wszystko działa – szkice i podpowiedzi powstają z szablonów i reguł (w górnym pasku:
„model lokalny niedostępny – szablony”). Tryb ustawiasz w `.env`:

| `AI_MODE` | Działanie |
|---|---|
| `local` (domyślnie) | model lokalny przez Ollamę; gdy nie działa – szablony |
| `off` | tylko szablony i reguły |
| `api` | model zewnętrzny przez LiteLLM (`LLM_MODELS`, klucz dostawcy w `.env`); dane osobowe pseudonimizowane przed wysłaniem; awaria – szablony |

Model lokalny: zainstaluj [Ollamę](https://ollama.com), potem
`ollama pull SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M` i uruchom aplikację ponownie.
Szczegóły: [`docs/asystent.md`](docs/asystent.md).

### Inne

```bash
streamlit run frontend/app.py            # stare demo Streamlit -> http://localhost:8501
python scripts/gen_fake_data.py --n 500  # dane testowe -> data/fake_wnioski.csv
```

## 3. Użycie LLM w kodzie

```python
from backend.llm import ask_llm, ask_llm_json

ask_llm("Streść ten wniosek: ...")
ask_llm_json("Wyciągnij z tekstu JSON z polami: nadawca, data, kwota. Tekst: ...")
```

Kolejność modeli ustawiasz w `LLM_MODELS` w `.env`. Gdy pierwszy padnie (limit, awaria), wchodzi następny.

## 4. Zasady pracy z gitem

- `main` zawsze działa. Na `main` merguje tylko Franek.
- Każdy pracuje na swojej gałęzi: `git checkout -b wojtek/pipeline`
- Małe commity, push co godzinę, PR do `main`.
- Przed demo: `git tag demo` na działającej wersji.

## 5. Deploy (Streamlit Community Cloud)

1. share.streamlit.io → zaloguj przez GitHub → **Create app**
2. Repo, gałąź `main`, plik `frontend/app.py`
3. **Advanced settings → Secrets**: wklej klucze w formacie TOML:
   ```toml
   ANTHROPIC_API_KEY = "..."
   LLM_MODELS = "anthropic/claude-sonnet-4-5,openai/gpt-4o-mini"
   ```
4. Deploy → otrzymujesz publiczny link do demo.

## 6. OCR (opcjonalnie)

Instalujesz Tesseract z polskim językiem (Windows: instalator UB-Mannheim, zaznacz Polish; macOS: `brew install tesseract tesseract-lang`), dla PDF-ów także Poppler, potem:
`pip install pytesseract pdf2image`

## 7. Polski model lokalnie (opcjonalnie)

Zainstaluj Ollamę, sprawdź dokładną nazwę modelu (`ollama search bielik` albo ollama.com), potem `ollama pull <nazwa>`.
Dopisz `ollama/<nazwa>` na koniec `LLM_MODELS`. Na laptopie bez GPU model działa wolno: to opcja zapasowa i argument w pitchu („może działać on-premise”), nie silnik demo.
