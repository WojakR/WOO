"""One-click start of the Streamlit app, from any folder.

Called by frontend/Uruchom.bat (Windows) / frontend/uruchom.sh (macOS, Linux) with the system Python, or
directly: `python <path>/frontend/start.py`. Reuses scripts/uruchom.py for the setup (.venv, requirements,
.env), then runs `streamlit run frontend/app.py` in the project folder on a free port. Standard library only.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

import uruchom as setup  # noqa: E402  (scripts/uruchom.py)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Uruchamia aplikację Streamlit Asystenta Ocen Okresowych.")
    ap.add_argument("--port", type=int, default=8501, help="port (domyślnie 8501; zajęty = następny wolny)")
    ap.add_argument("--bez-przegladarki", action="store_true", help="nie otwieraj przeglądarki")
    args = ap.parse_args(argv)

    if sys.version_info < setup.MIN_PYTHON:
        print(f"Potrzebny Python {setup.MIN_PYTHON[0]}.{setup.MIN_PYTHON[1]} lub nowszy "
              f"(jest {sys.version.split()[0]}). Pobierz z https://www.python.org/downloads/")
        return 1
    try:
        py = setup._prepare(PROJECT)
    except subprocess.CalledProcessError:
        print("✖ Instalacja bibliotek nie powiodła się. Sprawdź połączenie z internetem i uruchom ponownie.")
        return 1
    try:
        port = setup.find_free_port("127.0.0.1", args.port)
    except RuntimeError as e:
        print(f"✖ {e}")
        return 1

    print(f"\n✔ Aplikacja startuje: http://localhost:{port}/")
    print("  Zamknij to okno albo naciśnij Ctrl+C, żeby zatrzymać.\n", flush=True)
    cmd = [str(py), "-m", "streamlit", "run", str(PROJECT / "frontend" / "app.py"),
           "--server.port", str(port), "--server.headless", "true" if args.bez_przegladarki else "false",
           "--browser.gatherUsageStats", "false"]
    try:
        return subprocess.call(cmd, cwd=PROJECT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
