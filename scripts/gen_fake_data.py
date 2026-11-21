"""Syntetyczne dane w stylu urzędowym (bez prawdziwych danych osobowych).

Uruchom: python scripts/gen_fake_data.py --n 500
Wynik: data/fake_wnioski.csv  (przerób kolumny pod konkretne zadanie)
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default="data/fake_wnioski.csv")
    a = ap.parse_args()
    df = pd.DataFrame([row(i) for i in range(1, a.n + 1)])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False, sep=";", encoding="utf-8-sig")
    print(f"Zapisano {len(df)} wierszy -> {a.out}")
