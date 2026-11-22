# data/kprm – dane domenowe

Dane, z których korzysta aplikacja (moduł `backend/kprm.py`;
ścieżkę można zmienić zmienną `KPRM_DATA_DIR`).

## Zadanie 14: Cyfrowy Asystent Ocen Okresowych (KPRM)

Wszystko pochodzi z materiałów KPRM do HackNation 2026 (folder organizatora na Google Drive).
Osoby w przykładach są fikcyjne.

| Plik | Co zawiera | Źródło |
|---|---|---|
| `kryteria.json` | 14 kryteriów oceny ze wskaźnikami behawioralnymi | zał. nr 1 do rozporządzenia PRM z 4.04.2016 |
| `arkusze.json` | arkusze A/B/C: komu przysługują, kryteria obowiązkowe, maks. 3 kryteria dodatkowe | § 3–4 rozporządzenia |
| `reguly.json` | skala 1/3/5/7/9, progi średniej, warunek oceny pozytywnej/negatywnej, terminy (24 mies., 30/7 dni, sprzeciw 7/14 dni…), zasady liczenia terminów z przykładem testowym, stopnie służbowe, statusy procesu | ustawa art. 81–83, 89; rozporządzenie § 5–12; „liczenie terminów” KPRM |
| `pracownicy.json` | 8 ocenianych i ich oceniający z przykładowych arkuszy (urząd, komórka, stanowisko, arkusz, poprzednia ocena, scenariusz demo) | przykładowe arkusze KPRM |
| `wiedza/*.md` | teksty do RAG: rozporządzenie, ustawa (cała i wyciąg), poradnik KPRM, skrócony opis procesu, liczenie terminów, przypadki użycia, schematy pól arkuszy A/B/C | materiały KPRM |
| `przyklady/*.md` | 11 wypełnionych arkuszy (w tym 3 negatywne) – wzorce stylu uzasadnień i wniosków rozwojowych dla LLM | przykładowe arkusze KPRM |

Uwagi:
- Warunek oceny pozytywnej z § 11 rozporządzenia: poziom ogólny „na poziomie oczekiwań” lub wyżej
  **i żadna ocena cząstkowa = 1 pkt**. Excel KPRM („Arkusz B – wersja zautomatyzowana”) liczy to samo.
- „Standardy zarządzania ZZL w służbie cywilnej” (PDF) mają zepsute kodowanie fontów, tekstu nie da się
  wyciągnąć – nie ma go w `wiedza/`. Oryginał: `hakaton/dane/KPRM - Cyfrowy Asystent Ocen Okresowych/1. Akty prawne/`.
- Oryginalne pliki (PDF, DOCX, XLSX, BPMN) nie są w repo – leżą w `hakaton/dane/` na dysku.
- W przykładach KPRM są błędy formalne (np. data „14.046.2024”, brak średniej w arkuszu 4) –
  przydatne do pokazania walidacji.

## Zadania dla agentów

`../tasks/kprm-demo.json` – przypadki użycia do demo rozpisane jako zadania koordynatora:

```bash
cd server
python -m coordinator.cli import tasks/kprm-demo.json
```
