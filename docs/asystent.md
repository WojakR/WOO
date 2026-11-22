# Asystent AI: podpowiedzi dla oceniającego

Kod: `app/application/assistant.py` (`AiSuggestionService`), prompty: `app/application/prompts/*.md`,
adaptery modeli: `app/infrastructure/ai_models.py`, składanie z konfiguracji: `app/infrastructure/assistant_factory.py`.
Dane dla trybu bez AI: `data/kprm/asystent.json` (pytania, działania rozwojowe, reguły HR partnera, szablony).

## Zasady
- **AI tylko proponuje.** Żadna funkcja niczego nie zapisuje; decyduje oceniający.
- **Każda funkcja działa bez AI.** Pole `source` mówi, skąd jest wynik: `AI`, `SZABLON` albo `REGULY`.
- **Pseudonimizacja zawsze**, także dla modelu lokalnego: imiona, nazwiska (z odmianą), PESEL i e-maile są
  zamieniane na `[OSOBA_n]`, `[PESEL]`, `[EMAIL]` przed wysłaniem i przywracane w odpowiedzi.
- **Walidacja każdej odpowiedzi:** kryteria tylko z listy, cytat musi występować w notatce, identyfikatory notatek
  muszą istnieć, żadnych pozostawionych znaczników, HR partner bez diagnoz zdrowotnych. Odrzucona odpowiedź →
  wersja bez AI.
- **Dziennik:** `service.calls` (lub callback `on_call`) zapisuje to, co faktycznie wyszło do modelu
  (pod encję `AiInteraction`).

## Tryby (`AI_MODE` w `.env`)

| Tryb | Co robi |
|---|---|
| `local` (domyślny) | Ollama na tej maszynie, structured outputs (schemat JSON); nic nie wychodzi z komputera |
| `off` | tylko szablony i reguły |
| `api` | model zewnętrzny przez `backend.llm.ask_llm` (LiteLLM, lista `LLM_MODELS` z przejściem na następny); schemat JSON w prompcie systemowym; błąd dostawcy → wersja bez AI |

Uruchomienie modelu lokalnego:
```bash
ollama pull SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M
# opcjonalnie mniejszy model do klasyfikacji: AI_LOCAL_MODEL_FAST=<tag> w .env
```

## Funkcje i ich odpowiedniki w API (`docs/api.md`, `app/api/schemas.py`)

| Funkcja usługi | UC | Endpoint | Schemat | Bez AI |
|---|---|---|---|---|
| `classify_note(note, sheet, additional, people)` | UC4–5 | w tle po `POST /evaluations/{id}/notes` | `NoteOut.sugestie_ai` | podobieństwo tekstu do wskaźników (top 3, bez wydźwięku) |
| `draft(kind, cycle, employee, notes)` | UC5 | `POST /evaluations/{id}/ai/draft` | `DraftOut` | szablon z kryteriami, punktami i cytatami z notatek |
| `draft_stream(...)` | UC5 | ten sam, `Accept: text/event-stream` | strumień tekstu | szablon jednym kawałkiem |
| `conversation_prep(cycle, employee, evaluator, notes, today, kind, absences)` | UC4 | `POST /evaluations/{id}/ai/conversation-prep` | `ConversationPrepOut` | szkielet z danych + pytania z katalogu |
| `suggest_criteria(employee, sheet, description)` | UC1 | `POST /evaluations/{id}/ai/suggest-criteria` | `SuggestCriteriaOut` | słowa kluczowe stanowiska |
| `hr_partner(cycle, employee, notes, absences, today)` | UC7 | `GET /evaluations/{id}/hr-partner` | `HrPartnerOut` | sygnały z reguł + katalog działań |

`draft` zapamiętuje wynik po kluczu z danych wejściowych (`Draft.key`); zmiana ocen lub notatek daje nowy klucz,
więc UI może oznaczyć stary szkic jako nieaktualny.

**Dla routerów API:** `app/api/assistant_mapping.py` zamienia wyniki usługi na schematy z `app/api/schemas.py`
(`to_classification`, `to_draft_out`, `to_conversation_prep_out`, `to_suggest_criteria_out`, `to_hr_partner_out`).
Kody kryteriów wychodzą wielkimi literami (`RZETELNOSC`), `criterion_id()` zamienia je z powrotem.
Router = pobranie danych z repozytoriów → wywołanie usługi → `to_*()`.

## Personalizacja z historii pracownika (przygotowanie rozmowy, część rozwojowa)

`app/domain/career_profile.py` łączy **staż w urzędzie** (`Employee.employment_start`, z danych kadrowych
`data_zatrudnienia`) z **poziomami kolejnych ocen** (oceny z systemu + `poprzednia_ocena` i `wczesniejsze_oceny`
z danych kadrowych + bieżąca, gdy wpisano wszystkie oceny cząstkowe). Wynik to sygnały dla oceniającego:

| Sygnał | Kiedy | Na co ukierunkowuje rozmowę |
|---|---|---|
| `SPADEK_PRZY_STAZU` | długi staż (≥ 5 lat) i wynik niższy niż poprzednio | pytanie otwarte na start, obciążenie, urlop, wsparcie – bez dopytywania o sprawy prywatne |
| `SPADEK_TRENDU` | kolejne oceny coraz niższe (3 z rzędu) | trend na faktach, cele poprawy, comiesięczna informacja zwrotna |
| `STAGNACJA` | ten sam średni poziom (2 razy) mimo stażu ≥ 3 lat | ambicje, oczekiwania wobec wyższego poziomu, nowe wyzwania |
| `STABILNIE_WYSOKO` | 2 razy z rzędu jeden z dwóch najwyższych poziomów | docenienie, ścieżka awansu, ryzyko znudzenia |
| `WZROST` | wynik wyższy niż poprzednio | docenienie postępu |
| `NOWY_PRACOWNIK` | staż < 12 mies. | wdrożenie, wyjaśnienie zasad oceny |

Progi i teksty (rekomendacje do rozmowy + `rozwoj`: działania rozwojowe) są decyzją urzędu:
`config/ustawienia_urzedu.json` → `profil_pracownika` (pusta sekcja = funkcja wyłączona). Gdzie trafiają:
- **HR partner** (`GET …/hr-partner`): jako dodatkowe sygnały z `dzialania_rozwojowe`; `SPADEK_OCEN` znika, gdy jest
  sygnał spadku z historii (mówi więcej).
- **Notatka na rozmowę** (`POST …/ai/conversation-prep`): sygnały, działania z historii na początku
  `propozycje_rozwoju`, trudny temat dla spadku/stagnacji; prompt dostaje staż i historię poziomów (bez nazwisk).
- **Szkic IPRZ** (`POST …/ai/draft`, `rodzaj: IPRZ`): działania z historii przed katalogiem dla słabych kryteriów.
Bez AI wszystko działa na tych samych regułach i tekstach.

## Podpowiedź punktów z notatek

`app/domain/evidence_hint.py` – **reguła, nie AI**: odsetek notatek pozytywnych przeliczony na skalę, bez skrajnych
wartości, dopiero od 3 notatek. Reguła liczy notatki, nie ich wagę, dlatego `GET …/evidence` podaje też
`sugerowane_od` / `sugerowane_do` (co dałaby jedna notatka więcej w którąś stronę), a `uzasadnienie_sugestii` mówi
wprost, że podpowiedź jest niepewna (gdy przedział > 0) i że ocenę cząstkową ustala oceniający.

## Pomiar trafności klasyfikacji
```bash
python scripts/eval_classifier.py            # model z .env (local)
python scripts/eval_classifier.py --mode off # punkt odniesienia bez AI
```
Zestaw: 30 ręcznie oznaczonych notatek (`data/kprm/notatki_testowe.json`).
Punkt odniesienia bez AI: kryterium trafione 50% (top-1) / 77% (top-3), bez wydźwięku.

## Tryb API (`AI_MODE=api`)
`ApiModel` woła `backend.llm.ask_llm` (LiteLLM, modele z `LLM_MODELS`, np. `anthropic/claude-sonnet-5-5`).
Pseudonimizacja jest podwójna: asystent maskuje osoby z oceny (`[OSOBA_n]`), a `ask_llm` – wszystkich z katalogu
pracowników, PESEL, e-maile i telefony (`[OSOBA_Kn]`), zanim cokolwiek wyjdzie z aplikacji. Brak klucza, limit albo
awaria dostawcy = `AiUnavailable` → szablon. W testach (`LLM_MOCK=1`) model jest niedostępny.
