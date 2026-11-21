"""Syntetyczne dane w stylu urzędowym (bez prawdziwych danych osobowych).

Uruchom: python scripts/gen_fake_data.py --n 500
Wynik: data/fake_wnioski.csv  (przerób kolumny pod konkretne zadanie)

Plik do importu kadrowego (POST /api/admin/employees/import, app/infrastructure/hr_import.py):
    python scripts/gen_fake_data.py --kadry --n 40      ->  data/fake_kadry.csv
"""
import argparse
import random
from pathlib import Path

import pandas as pd
from faker import Faker

fake = Faker("pl_PL")
Faker.seed(42)
random.seed(42)

TYPY = ["dofinansowanie", "zasiłek", "pozwolenie", "skarga", "wniosek o informację publiczną"]
STATUSY = ["nowy", "w weryfikacji", "uzupełnienie braków", "zatwierdzony", "odrzucony"]
URZEDY = ["UW Warszawa", "UM Bydgoszcz", "UM Kraków", "PUP Gdańsk", "MOPS Łódź"]


def row(i):
    return {
        "id_wniosku": f"WN/{2026}/{i:05d}",
        "data_zlozenia": fake.date_between("-1y", "today").isoformat(),
        "typ": random.choice(TYPY),
        "status": random.choices(STATUSY, weights=[2, 3, 1, 4, 1])[0],
        "urzad": random.choice(URZEDY),
        "wnioskodawca": fake.name(),
        "miasto": fake.city(),
        "kwota_pln": round(random.lognormvariate(8, 1), 2),
        "opis": fake.sentence(nb_words=14),
    }


KOMORKI = ["Departament Prawny", "Biuro Dyrektora Generalnego", "Departament Budżetu", "Biuro Informatyki"]


def hr_rows(n: int) -> list[dict]:
    """A fictional office: the director general, heads of units, their teams (no real personal data)."""
    def person(i, komorka, stanowisko, boss, head=False, manages=False):
        civil = random.random() < 0.3
        last = fake.date_between("-30M", "-3M") if random.random() < 0.8 else None
        return {
            "id": f"prac.{i:04d}", "imie": fake.first_name(), "nazwisko": fake.last_name(),
            "urzad": "Urząd Przykładowy", "komorka": komorka, "stanowisko": stanowisko,
            "opis_stanowiska": fake.sentence(nb_words=8), "id_przelozonego": boss or "",
            "arkusz": "", "urzednik_mianowany": "TAK" if civil else "NIE",
            "stopien_sluzbowy": random.randint(1, 8) if civil else "",
            "kieruje_zespolem": "TAK" if manages else "NIE", "kierownik_urzedu": "TAK" if head else "NIE",
            "email": f"prac.{i:04d}@urzad.example",
            "data_zatrudnienia": fake.date_between("-15y", "-1y").isoformat(),
            "data_zakonczenia_zatrudnienia": "",
            "data_ostatniej_oceny": last.isoformat() if last else "",
        }

    rows = [person(1, "Biuro Dyrektora Generalnego", "Dyrektor generalny", None, head=True, manages=True)]
    heads = []
    for k in KOMORKI:
        rows.append(person(len(rows) + 1, k, "Dyrektor departamentu", "prac.0001", manages=True))
        heads.append(rows[-1]["id"])
    while len(rows) < n:
        rows.append(person(len(rows) + 1, KOMORKI[len(rows) % len(KOMORKI)],
                           random.choice(["Specjalista", "Starszy specjalista", "Główny specjalista"]),
                           heads[len(rows) % len(heads)]))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default=None)
    ap.add_argument("--kadry", action="store_true", help="plik do importu kadrowego zamiast wniosków")
    a = ap.parse_args()
    if a.kadry:
        a.out = a.out or "data/fake_kadry.csv"
        df = pd.DataFrame(hr_rows(max(a.n, len(KOMORKI) + 1)))
    else:
        a.out = a.out or "data/fake_wnioski.csv"
        df = pd.DataFrame([row(i) for i in range(1, a.n + 1)])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False, sep=";", encoding="utf-8-sig")
    print(f"Zapisano {len(df)} wierszy -> {a.out}")
