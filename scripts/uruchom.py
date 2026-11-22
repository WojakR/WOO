"""One-command start for a small office (one laptop, no Docker, no IT).

Called by Uruchom.bat (Windows) / uruchom.sh (macOS, Linux) with the system Python:
creates .venv, installs requirements (again only when requirements.txt changes), creates .env from
.env.example, picks a free port, starts the app and opens the browser. Only the standard library here,
because it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 10)
MARKER = ".requirements.sha256"


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def requirements_hash(requirements: Path) -> str:
    return hashlib.sha256(requirements.read_bytes()).hexdigest()


def needs_install(venv_dir: Path, requirements: Path) -> bool:
    """True when the venv is new or requirements.txt changed since the last successful install."""
    marker = venv_dir / MARKER
    if not venv_python(venv_dir).exists() or not marker.exists():
        return True
    return marker.read_text(encoding="utf-8").strip() != requirements_hash(requirements)


def ensure_env(project: Path) -> bool:
    """Copy .env.example to .env when .env is missing. Returns True if it was created."""
    env, example = project / ".env", project / ".env.example"
    if env.exists() or not example.exists():
        return False
    shutil.copyfile(example, env)
    return True


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, start: int, tries: int = 20) -> int:
    for port in range(start, start + tries):
        if port_free(host, port):
            return port
    raise RuntimeError(f"Porty {start}–{start + tries - 1} są zajęte. Podaj inny: --port 9000")


def _say(msg: str) -> None:
    print(msg, flush=True)


def _prepare(project: Path) -> Path:
    venv_dir, requirements = project / ".venv", project / "requirements.txt"
    if not venv_python(venv_dir).exists():
        _say("• Tworzę środowisko Pythona (.venv) – tylko za pierwszym razem…")
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    py = venv_python(venv_dir)
    if needs_install(venv_dir, requirements):
        _say("• Instaluję biblioteki (za pierwszym razem kilka minut, potrzebny internet)…")
        subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"],
                       check=True)
        subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
                       check=True)
        (venv_dir / MARKER).write_text(requirements_hash(requirements), encoding="utf-8")
    if ensure_env(project):
        _say("• Utworzyłem plik ustawień .env (z .env.example). Aplikacja działa bez kluczy i bez modelu AI.")
    return py


# Streamlit's own health check: answers "ok" once the server is up (the /api routes run in-process, not over HTTP)
HEALTH_PATH = "_stcore/health"
# Windows without long paths allows 260 characters; the deepest file in the venv (streamlit 1.67) is ~140
# characters below the project folder, so a folder deeper than ~120 characters fails while pip installs.
WINDOWS_MAX_PATH = 260
DEEPEST_VENV_FILE = 140


def path_too_long(project: Path, is_windows: bool = os.name == "nt") -> bool:
    """True when the folder is so deep that installing the libraries may hit the Windows path limit."""
    return is_windows and len(str(project)) + DEEPEST_VENV_FILE >= WINDOWS_MAX_PATH


def _open_when_ready(url: str, timeout_s: float = 120) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + HEALTH_PATH, timeout=2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Uruchamia Asystenta Ocen Okresowych na tym komputerze.")
    ap.add_argument("--port", type=int, default=8000, help="port (domyślnie 8000; zajęty = następny wolny)")
    ap.add_argument("--siec", action="store_true",
                    help="udostępnij w sieci urzędu (inne komputery: http://<adres tego komputera>:<port>)")
    ap.add_argument("--bez-przegladarki", action="store_true", help="nie otwieraj przeglądarki")
    args = ap.parse_args(argv)

    if sys.version_info < MIN_PYTHON:
        _say(f"Potrzebny Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} lub nowszy (jest {sys.version.split()[0]}). "
             "Pobierz z https://www.python.org/downloads/")
        return 1
    try:
        py = _prepare(PROJECT)
    except subprocess.CalledProcessError:
        if path_too_long(PROJECT):
            _say("✖ Instalacja bibliotek nie powiodła się – prawdopodobnie ścieżka folderu jest za długa dla Windows "
                 f"({len(str(PROJECT))} znaków). Przenieś folder bliżej dysku (np. C:\\Asystent), usuń w nim "
                 "katalog .venv i uruchom ponownie.")
        else:
            _say("✖ Instalacja bibliotek nie powiodła się. Sprawdź połączenie z internetem i uruchom ponownie.")
        return 1

    host = "0.0.0.0" if args.siec else "127.0.0.1"
    try:
        port = find_free_port(host, args.port)
    except RuntimeError as e:
        _say(f"✖ {e}")
        return 1
    url = f"http://localhost:{port}/"
    _say(f"\n✔ Aplikacja startuje: {url}")
    if args.siec:
        _say(f"  W sieci urzędu: http://{socket.gethostname()}:{port}/ (może być potrzebne otwarcie portu w zaporze)")
    _say("  Zamknij to okno albo naciśnij Ctrl+C, żeby zatrzymać.\n")
    if not args.bez_przegladarki:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    # the Streamlit app runs the API in-process (frontend/api_client.py) – one process, one port
    cmd = [str(py), "-m", "streamlit", "run", "frontend/app.py", "--server.address", host, "--server.port", str(port),
           "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    try:
        return subprocess.call(cmd, cwd=PROJECT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
