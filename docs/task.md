# Zadanie: Cyfrowy Asystent Ocen Okresowych (KPRM, zadanie 14)

Pełna treść, regulamin i materiały: `hakaton/dane/KPRM - Cyfrowy Asystent Ocen Okresowych/` (poza repo).
Dane domenowe w repo: `../server/data/kprm/` (opis: `server/data/README.md`).

## Instytucja i problem
- KPRM, Departament Służby Cywilnej. Ocena okresowa (co 24 miesiące, ok. 123 tys. osób w ok. 1740 urzędach)
  jest robiona na papierze i traktowana jak formalność. Przełożonym brakuje wsparcia w wyborze kryteriów,
  rozmowach, informacji zwrotnej i planowaniu rozwoju.

## Użytkownik (kto klika?)
- Oceniający (bezpośredni przełożony) – główny użytkownik.
- Oceniany – potwierdza kryteria i zapoznanie z oceną.
- Kadry / administrator – terminy, korekty, statystyki.

## Scenariusz demo (jedno zdanie)
- Przełożony prowadzi ocenę Grzegorza od wyznaczenia kryteriów do PDF-a, a asystent pilnuje terminów
  i przepisów, podpowiada kryteria, przygotowuje rozmowę, pisze szkic uzasadnienia i sygnalizuje przeciążenie.

## MVP: co MUSI działać na demo
- [ ] UC1 Wyznaczenie kryteriów (arkusz A/B/C z konfiguracji, maks. 3 dodatkowe bez powtórzeń, termin +24 mies.) + AI podpowiada kryteria
- [ ] UC2 Potwierdzenie przez ocenianego, blokowanie pól
- [ ] UC3 Przypomnienia o terminach (przycisk „przewiń czas”)
- [ ] UC4 Przygotowanie do rozmowy oceniającej z notatek (AI)
- [ ] UC5 Ocena: macierz 1/3/5/7/9, średnia, poziom, pozytywna/negatywna (§ 11), walidacje + AI szkic uzasadnienia i IPRZ
- [ ] UC6 Zapoznanie się z oceną + PDF zgodny ze wzorem
- [ ] UC7 Wirtualny HR partner: sygnały przeciążenia, rekomendacje, momenty do docenienia
- [ ] (jeśli czas) UC8 Przesunięcie terminu przez nieobecność > 1 mies.
- [ ] (jeśli czas) UC9 Wniosek o kolejny stopień służbowy (część III)

Zadania dla agentów: `server/tasks/kprm-demo.json`.

## Poza zakresem (świadomie nie robimy)
- Sprzeciw i ponowne sporządzenie oceny, zastępstwa, zmiana oceniającego, import historii,
  sprawozdawczość, integracja z EZD i systemem kadrowym, prawdziwe logowanie i podpis elektroniczny.

## Dane (skąd, format, czy syntetyczne)
- `server/data/kprm/*.json` – kryteria, arkusze, reguły, terminy (z rozporządzenia i ustawy).
- `server/data/kprm/pracownicy.json` – fikcyjne osoby z przykładowych arkuszy KPRM.
- `server/data/kprm/wiedza/` – teksty przepisów i poradnika KPRM do RAG; `przyklady/` – 11 wypełnionych arkuszy.
