"""Startup cost on a slow office laptop: the web app must not load pandas or Streamlit just to start."""
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def test_web_app_starts_without_pandas_and_streamlit():
    code = ("import sys, backend.main; "
            "print(','.join(m for m in ('pandas', 'streamlit') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT, capture_output=True, text=True, timeout=120,
                         env={**__import__("os").environ, "AI_MODE": "off"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""  # loaded later, only when a table is parsed / under `streamlit run`


def test_parse_table_still_reads_csv():
    from backend.parsers import parse_table
    df = parse_table("imie;nazwisko\nJan;Kowalski\n".encode(), "kadry.csv")
    assert list(df.columns) == ["imie", "nazwisko"] and df.iloc[0]["nazwisko"] == "Kowalski"
