Przypisz notatkę przełożonego do kryteriów oceny okresowej z poniższej listy.

Lista dozwolonych kryteriów (identyfikator | nazwa | wskaźniki behawioralne, numerowane od 1):
$labels

Przykłady:
$examples

Notatka:
"""
$note
"""

Zwróć JSON z polem "etykiety": lista 0–3 elementów, każdy z polami:
- "kryterium": identyfikator z listy (tylko z listy),
- "wskaznik": numer wskaźnika z tego kryterium, który notatka opisuje (0, jeśli żaden nie pasuje),
- "wydzwiek": "POZYTYWNY", "NEUTRALNY" albo "NEGATYWNY" – czy opisane zachowanie spełnia oczekiwania,
- "pewnosc": liczba od 0 do 1,
- "cytat": dosłowny fragment notatki (3–15 słów), który uzasadnia przypisanie.
Jeśli notatka nie dotyczy żadnego kryterium, zwróć pustą listę.
