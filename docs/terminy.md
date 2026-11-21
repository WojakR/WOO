# Terminy w ocenie okresowej

Wszystkie wartości liczbowe są w `server/data/kprm/reguly.json` (`terminy`) i trafiają do kodu przez `RuleBook`;
zmiana przepisów = zmiana pliku. Kod: `app/domain/deadlines.py`, wpięcie w cykl: `app/domain/cycle.py`,
przypadki użycia: `app/application/use_cases.py`. Przykłady KPRM jako testy: `tests/test_kprm_deadline_examples.py`.

## Zasady

| Termin | Reguła | Źródło | Funkcja |
|---|---|---|---|
| Ocena okresowa | 24 mies. od poprzedniej oceny / zatrudnienia na czas nieokreślony; koniec w dniu o tym samym numerze (albo ostatnim dniu miesiąca); z dnia wolnego na następny roboczy | art. 81 ust. 4; KPRM „liczenie terminów”; poradnik s. 10 | `evaluation_deadline` |
| Przedłużenie przez nieobecność | o całą usprawiedliwioną nieobecność ciągłą **dłuższą niż miesiąc**; dni wolne między okresami nie przerywają ciągłości | art. 81 ust. 7; poradnik s. 12–13 | `merge_absences`, `is_longer_than` |
| Wyznaczenie kryteriów | 30 dni od poprzedniej oceny / zatrudnienia, 7 dni po ocenie negatywnej; dnia zdarzenia nie liczy się | § 7 rozporządzenia; poradnik s. 10 | `criteria_deadline` |
| Ponowna ocena po negatywnej | dzień po upływie 6 mies. od zapoznania się z oceną; **bez** przedłużania przez nieobecność i **bez** przesuwania z dnia wolnego | art. 81 ust. 9; poradnik s. 13–14 | `reevaluation_date` |
| Sprzeciw | 7 dni od zapoznania się z oceną; dnia zapoznania nie liczy się; z dnia wolnego na następny roboczy | art. 83 ust. 1 | `objection_deadline` |
| Zmiana stanowiska ≤ 6 mies. od odniesienia | ponowne wyznaczenie kryteriów i rozmowa w 30 dni; termin oceny **bez zmian** | § 9 ust. 1 | `position_change` → `NOWE_KRYTERIA` |
| Zmiana stanowiska > 6 mies. od odniesienia | ocena najwcześniej 7 dni przed zmianą, najpóźniej 30 dni po niej | art. 81 ust. 6; § 9 ust. 2 | `position_change` → `OCENA` |

Data odniesienia przy zmianie stanowiska: ostatnia ocena, a przy pierwszej ocenie – dzień wyznaczenia kryteriów.

## Granica „dłużej niż miesiąc” (zmiana z PR #5)

Okres trwający **dokładnie** N miesięcy kończy się w dniu `add_months(start, N)`; dłuższy jest dopiero okres,
który kończy się później. Poradnik KPRM, s. 13: dla nieobecności od 9.09.2014 „miesięczny okres […] upływał
9 października 2014”, więc nieobecność 9.09–9.10 **nie** przedłuża terminu, a 9.09–10.10 już tak.
Wcześniej kod traktował 9.09–9.10 jako dłuższą niż miesiąc. Ta sama reguła obowiązuje przy „więcej niż
6 miesięcy” dla zmiany stanowiska. Przykład z demo (L4 5.10 + urlop do 6.11) nadal przedłuża termin.

## Po ocenie negatywnej

Kolejny cykl liczy z **dwóch różnych dat** oceny negatywnej
(`start_cycle(..., start_date=<sporządzenie>, after_negative=True, negative_acknowledged_on=<zapoznanie>)`):
- kryteria w 7 dni od **sporządzenia** oceny negatywnej (§ 7 pkt 2) – `start_date`,
- termin oceny = `reevaluation_date` (6 mies. + 1 dzień) od **zapoznania** się z nią (art. 81 ust. 9) –
  `negative_acknowledged_on`, a nie 24 miesiące; nieobecności go nie wydłużają.

Domyślnie obie daty idą z `PreviousEvaluation` (`date` = sporządzenie, `acknowledged` = zapoznanie;
w `pracownicy.json`: `poprzednia_ocena.data` i `poprzednia_ocena.data_zapoznania`). Bez daty zapoznania
liczymy od sporządzenia (§ 12 ust. 1: zapoznanie „niezwłocznie”). Przykład: sporządzona 10.06.2026,
zapoznanie 22.06.2026 → kryteria do 17.06.2026, ponowna ocena 23.12.2026.

Poradnik mówi o ponownej ocenie „niezwłocznie po dniu, w którym minie 6 miesięcy” – w UI pokazywać tę datę
jako „ponowna ocena od”, a nie jako ostateczny termin.

## Dla API i UI

- `EvaluationService.objection_deadline(cycle_id)` → pole `CzescII.termin_sprzeciwu` (null przed zapoznaniem).
- `EvaluationCycle.next_evaluation_due(rules)` → data ponownej oceny po zapoznaniu się z oceną negatywną.
- `EvaluationService.register_position_change(cycle_id, data_zmiany)` → `POST /api/evaluations/{id}/position-change`
  (`PositionChangeIn` / `PositionChangeOut` w `app/api/schemas.py`).
- `reminders()` ma nowe rodzaje: `objection` (do ocenianego, do końca terminu sprzeciwu)
  i `reevaluation` (do oceniającego, ≤ 30 dni przed ponowną oceną).
