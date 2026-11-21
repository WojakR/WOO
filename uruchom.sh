#!/usr/bin/env sh
# Asystent Ocen Okresowych – start jednym poleceniem (macOS / Linux, bez Dockera).
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" scripts/uruchom.py "$@"
  fi
done
echo "Nie znaleziono Pythona. Zainstaluj Python 3.10 lub nowszy (https://www.python.org/downloads/)."
exit 1
