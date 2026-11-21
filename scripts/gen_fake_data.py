"""Syntetyczne dane w stylu urzędowym (bez prawdziwych danych osobowych).

Uruchom: python scripts/gen_fake_data.py --n 500
Wynik: data/fake_wnioski.csv  (przerób kolumny pod konkretne zadanie)

Czas pracy (RCP) dla przykładowych pracowników z pracownicy.json – do importu w POST /api/admin/rcp/import:
python scripts/gen_fake_data.py --rcp --do 2026-05-25 --tygodnie 10   ->  data/fake_rcp.csv
Jedna osoba (--przeciazony, domyślnie grzegorz.wzor) ma regularne nadgodziny, krótkie przerwy i pracę po godzinach.
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


def rcp_rows(employee_ids, until, weeks, overloaded):
    """Working days (Mon–Fri) of the last `weeks` weeks; columns as app/infrastructure/rcp_import.py expects."""
    from datetime import date, timedelta

    end = date.fromisoformat(until)
    day = end - timedelta(weeks=weeks)
    out = []
    while day <= end:
        if day.weekday() < 5:
            for eid in employee_ids:
                heavy = eid == overloaded and random.random() < 0.8
                start_h = random.choice([7, 7, 8, 8, 8])
                minutes = random.randint(470, 500) + (random.randint(60, 150) if heavy else 0)
                start = start_h * 60 + random.randint(0, 40)
                stop = start + minutes
                out.append({
                    "id_pracownika": eid, "data": day.isoformat(),
                    "wejscie": f"{start // 60:02d}:{start % 60:02d}", "wyjscie": f"{stop // 60:02d}:{stop % 60:02d}",
                    "przerwy_min": random.randint(0, 10) if heavy else random.randint(15, 30),
                    "aktywnosc_po_godzinach": "tak" if heavy and random.random() < 0.5 else "nie",
                })
        day += timedelta(days=1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default=None)
    ap.add_argument("--rcp", action="store_true", help="dane z rejestracji czasu pracy zamiast wniosków")
    ap.add_argument("--do", default="2026-05-25", help="ostatni dzień danych RCP (RRRR-MM-DD)")
    ap.add_argument("--tygodnie", type=int, default=10)
    ap.add_argument("--przeciazony", default="grzegorz.wzor")
    a = ap.parse_args()
    if a.rcp:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from backend import kprm

        df = pd.DataFrame(rcp_rows(list(kprm.employees()), a.do, a.tygodnie, a.przeciazony))
        out = a.out or "data/fake_rcp.csv"
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False, sep=";", encoding="utf-8-sig")
        print(f"Zapisano {len(df)} dni pracy -> {out}")
        sys.exit(0)
    a.out = a.out or "data/fake_wnioski.csv"
    df = pd.DataFrame([row(i) for i in range(1, a.n + 1)])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False, sep=";", encoding="utf-8-sig")
    print(f"Zapisano {len(df)} wierszy -> {a.out}")
