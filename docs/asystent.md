# Asystent AI: podpowiedzi dla oceniającego

Kod: `app/application/assistant.py` (`AiSuggestionService`), prompty: `app/application/prompts/*.md`,
adaptery modeli: `app/infrastructure/ai_models.py`, składanie z konfiguracji: `app/infrastructure/assistant_factory.py`.
Dane dla trybu bez AI: `server/data/kprm/asystent.json` (pytania, działania rozwojowe, reguły HR partnera, szablony).

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

## Pomiar trafności klasyfikacji
```bash
python scripts/eval_classifier.py            # model z .env (local)
python scripts/eval_classifier.py --mode off # punkt odniesienia bez AI
```
Zestaw: 30 ręcznie oznaczonych notatek (`server/data/kprm/notatki_testowe.json`).
Punkt odniesienia bez AI: kryterium trafione 50% (top-1) / 77% (top-3), bez wydźwięku.

## Tryb API (`AI_MODE=api`)
`ApiModel` woła `backend.llm.ask_llm` (LiteLLM, modele z `LLM_MODELS`, np. `anthropic/claude-sonnet-5-5`).
Pseudonimizacja jest podwójna: asystent maskuje osoby z oceny (`[OSOBA_n]`), a `ask_llm` – wszystkich z katalogu
pracowników, PESEL, e-maile i telefony (`[OSOBA_Kn]`), zanim cokolwiek wyjdzie z aplikacji. Brak klucza, limit albo
awaria dostawcy = `AiUnavailable` → szablon. W testach (`LLM_MOCK=1`) model jest niedostępny.
