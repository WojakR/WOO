#!/bin/sh
# Aplikacja Streamlit Asystenta Ocen Okresowych - start jednym poleceniem (macOS, Linux), z dowolnego katalogu.
cd "$(dirname "$0")/.." || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" frontend/start.py "$@"
