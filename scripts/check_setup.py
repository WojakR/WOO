"""Sprawdza, czy wszystko działa. Uruchom: python scripts/check_setup.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ok = True


def check(name, fn):
    global ok
    try:
        res = fn()
        print(f"✅ {name}" + (f": {res}" if res else ""))
    except Exception as e:
        ok = False
        print(f"❌ {name}: {type(e).__name__}: {str(e)[:300]}")


check("Python >= 3.10", lambda: None if sys.version_info >= (3, 10) else (_ for _ in ()).throw(RuntimeError(sys.version)))
check("Plik .env", lambda: None if (Path(__file__).parent.parent / ".env").exists() else (_ for _ in ()).throw(FileNotFoundError("skopiuj .env.example jako .env")))
for mod in ("fastapi", "streamlit", "litellm", "pandas", "pypdf", "lxml", "faker"):
    check(f"import {mod}", lambda m=mod: __import__(m) and None)

from backend import config, db  # noqa: E402

check("SQLite", lambda: str(config.DB_PATH))
check("Lista modeli", lambda: ", ".join(config.LLM_MODELS) + (" (MOCK)" if config.LLM_MOCK else ""))


def ping_each():
    if config.LLM_MOCK:
        return "pominięte (MOCK=1)"
    from litellm import completion

    results = []
    for m in config.LLM_MODELS:
        try:
            r = completion(model=m, messages=[{"role": "user", "content": "Odpowiedz jednym słowem: działa?"}],
                           max_tokens=10, timeout=30)
            results.append(f"\n   ✅ {m}: {r.choices[0].message.content.strip()}")
        except Exception as e:
            results.append(f"\n   ❌ {m}: {type(e).__name__}")
    return "".join(results)


check("Modele LLM (każdy osobno)", ping_each)
print("\nWszystko gotowe 🎉" if ok else "\nNapraw powyższe ❌ i uruchom ponownie.")
