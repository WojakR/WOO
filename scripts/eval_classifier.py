"""Measure note-classification accuracy on the hand-labelled set (server/data/kprm/notatki_testowe.json).

    python scripts/eval_classifier.py                 # AI_MODE from .env (default: local / Ollama)
    python scripts/eval_classifier.py --mode off      # baseline: similarity fallback only
    python scripts/eval_classifier.py --limit 5 -v    # quick check, print every answer

Reports: criterion accuracy (top-1 and top-3), sentiment accuracy (when the criterion is right),
share sent to manual assignment, average time per note. Not part of CI: it calls the real model.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_MOCK", "0")

from app.domain.notes import Note  # noqa: E402
from app.infrastructure.assistant_factory import build_assistant  # noqa: E402
from backend import kprm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["off", "local", "api"], default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    data = kprm.test_notes()
    items = data["notatki"][: args.limit or None]
    assistant = build_assistant(args.mode)
    top1 = top3 = sentiment_ok = manual = 0
    started = time.perf_counter()
    for it in items:
        out = assistant.classify_note(Note(str(it["id"]), date.today(), it["tresc"]), data["arkusz"],
                                      data["kryteria_dodatkowe"])
        got = [s.criterion_id for s in out.suggestions]
        hit1 = bool(got) and got[0] == it["kryterium"]
        top1 += hit1
        top3 += it["kryterium"] in got
        if hit1 and out.suggestions[0].sentiment and out.suggestions[0].sentiment.value == it["wydzwiek"]:
            sentiment_ok += 1
        manual += out.status == "DO_PRZYPISANIA"
        if args.verbose:
            first = out.suggestions[0] if out.suggestions else None
            print(f"{'OK ' if hit1 else '-- '} #{it['id']:>2} oczekiwane {it['kryterium']}/{it['wydzwiek']} | "
                  f"{out.source} {out.status} | "
                  f"{first.criterion_id + '/' + (first.sentiment.value if first.sentiment else '?') + f' {first.confidence}' if first else 'brak'}")
    n = len(items)
    elapsed = time.perf_counter() - started
    print(f"\nModel: {assistant.model.name} | notatek: {n}")
    print(f"Kryterium – trafność top-1: {top1 / n:.0%}, top-3: {top3 / n:.0%}")
    print(f"Wydźwięk (przy trafionym kryterium): {sentiment_ok / max(top1, 1):.0%}")
    print(f"Do ręcznego przypisania: {manual / n:.0%}")
    print(f"Średni czas na notatkę: {elapsed / n:.1f} s")
    failed = [c for c in assistant.calls if not c.ok]
    if failed:
        print(f"Nieudane wywołania modelu: {len(failed)} (np. {failed[0].error[:120]})")


if __name__ == "__main__":
    main()
