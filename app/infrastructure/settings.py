"""Office settings (decisions of the office, editable by its administrator) – kept apart from the rules of law
in server/data/kprm/reguly.json. Read from config/ustawienia_urzedu.json (or the file in USTAWIENIA_URZEDU)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.domain.access import VisibilityScope
from app.domain.errors import ValidationError

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "ustawienia_urzedu.json"


@dataclass(frozen=True)
class OfficeSettings:
    visibility_scope: VisibilityScope = VisibilityScope.SUBTREE

    @classmethod
    def from_dict(cls, raw: dict) -> OfficeSettings:
        scope = raw.get("zakres_widocznosci", VisibilityScope.SUBTREE.value)
        try:
            return cls(visibility_scope=VisibilityScope(scope))
        except ValueError:
            allowed = ", ".join(v.value for v in VisibilityScope)
            raise ValidationError([f"Ustawienia urzędu: nieznany zakres_widocznosci „{scope}” (dozwolone: {allowed})."]) from None


def load_office_settings(path: str | Path | None = None) -> OfficeSettings:
    p = Path(path or os.getenv("USTAWIENIA_URZEDU") or DEFAULT_PATH)
    if not p.exists():
        return OfficeSettings()
    return OfficeSettings.from_dict(json.loads(p.read_text(encoding="utf-8")))
