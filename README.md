# HackNation 2026 – Cyfrowy Asystent Ocen Okresowych (projekt)

> Ten katalog to `projekt/` w monorepo: aplikacja konkursowa. Koordynator agentów jest w `../server/`,
> a dane domenowe KPRM w `../server/data/kprm/`. Zadanie i scenariusz demo: [`docs/task.md`](docs/task.md).

Python + FastAPI (API) + Streamlit (demo) + SQLite + LLM z fallbackiem (LiteLLM).

```
backend/
  config.py     # wczytuje .env / st.secrets
  llm.py        # ask_llm(), ask_llm_json() – fallback po liście modeli
  parsers.py    # PDF, XML, CSV/XLSX, TXT, OCR -> tekst/dict/DataFrame
  db.py         # SQLite
  main.py       # FastAPI: /health /ask /upload /documents
frontend/app.py # Streamlit – demo dla jury
scripts/
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

Wpisz klucze do `.env` (albo ustaw `LLM_MOCK=1`, żeby działać bez kluczy), potem:

```bash
python scripts/check_setup.py
```

Wszystko ma być ✅.

## 2. Uruchamianie

```bash
streamlit run frontend/app.py            # demo -> http://localhost:8501
uvicorn backend.main:app --reload        # API  -> http://localhost:8000/docs
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
