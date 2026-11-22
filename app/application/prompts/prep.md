Przygotuj teksty do notatki przełożonego przed rozmową: $kind.

Oceniany: $person, stanowisko: $position, arkusz $sheet. Termin sporządzenia oceny: $deadline.
Poprzednia ocena: $previous.
Staż i historia ocen: $history.
Cele z rozmowy rozpoczynającej: $goals

Zebrane obserwacje według kryteriów (kryterium: liczba pozytywnych / negatywnych; przykłady):
$evidence

Sygnały do rozmowy wykryte przez system (także z historii pracownika – dopasuj do nich ton i tematy rozmowy):
$signals

$law

Zwróć JSON z polami:
- "cel_rozmowy": 1–2 zdania,
- "mocne_strony": do 4 krótkich punktów opartych na obserwacjach,
- "trudne_tematy": do 4 punktów: co poruszyć i jak sformułować to rzeczowo (fakty, nie ocena osoby),
- "pytania": obiekt {identyfikator kryterium: lista 1–3 $question_style}, tylko dla kryteriów z listy: $criteria_ids,
- "propozycje_rozwoju": do 4 konkretnych działań rozwojowych.
Nie podawaj punktów ani przewidywanej oceny.
