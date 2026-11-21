"""Readable JSON for domain objects stored in the database (no pickle: nothing in the database can run code).

Dataclasses, enums, dates, Fractions, tuples and sets are tagged so they come back as the same types. Only
classes passed in `types` can be rebuilt – anything else in the stored JSON is rejected.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, time
from enum import Enum
from fractions import Fraction
from typing import Any, Iterable


class JsonCodec:
    def __init__(self, types: Iterable[type]):
        self._types = {t.__name__: t for t in types}

    # ---- encode ---------------------------------------------------------------------------------
    def _enc(self, v: Any) -> Any:
        if isinstance(v, Enum):  # before str/int: `class Status(str, Enum)` is also a str
            return {"__enum__": type(v).__name__, "v": v.value}
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, datetime):  # before date: datetime is a date
            return {"__dt__": v.isoformat()}
        if isinstance(v, date):
            return {"__date__": v.isoformat()}
        if isinstance(v, time):
            return {"__time__": v.isoformat()}
        if isinstance(v, Fraction):
            return {"__frac__": str(v)}
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            name = type(v).__name__
            if name not in self._types:
                raise TypeError(f"JsonCodec: klasa {name} nie jest zarejestrowana")
            return {"__dc__": name, **{f.name: self._enc(getattr(v, f.name)) for f in dataclasses.fields(v)}}
        if isinstance(v, tuple):
            return {"__tuple__": [self._enc(x) for x in v]}
        if isinstance(v, (set, frozenset)):
            return {"__set__": [self._enc(x) for x in v]}
        if isinstance(v, list):
            return [self._enc(x) for x in v]
        if isinstance(v, dict):
            return {"__dict__": [[self._enc(k), self._enc(x)] for k, x in v.items()]}
        raise TypeError(f"JsonCodec: nie umiem zapisać {type(v).__name__}")

    def dumps(self, v: Any) -> str:
        return json.dumps(self._enc(v), ensure_ascii=False)

    # ---- decode ---------------------------------------------------------------------------------
    def _dec(self, v: Any) -> Any:
        if isinstance(v, list):
            return [self._dec(x) for x in v]
        if not isinstance(v, dict):
            return v
        if "__date__" in v:
            return date.fromisoformat(v["__date__"])
        if "__dt__" in v:
            return datetime.fromisoformat(v["__dt__"])
        if "__time__" in v:
            return time.fromisoformat(v["__time__"])
        if "__frac__" in v:
            return Fraction(v["__frac__"])
        if "__tuple__" in v:
            return tuple(self._dec(x) for x in v["__tuple__"])
        if "__set__" in v:
            return {self._dec(x) for x in v["__set__"]}
        if "__dict__" in v:
            return {self._dec(k): self._dec(x) for k, x in v["__dict__"]}
        if "__enum__" in v:
            return self._type(v["__enum__"])(v["v"])
        if "__dc__" in v:
            cls = self._type(v["__dc__"])
            names = {f.name for f in dataclasses.fields(cls) if f.init}
            obj = cls(**{k: self._dec(x) for k, x in v.items() if k in names})
            for f in dataclasses.fields(cls):  # init=False fields, if any
                if not f.init and f.name in v:
                    object.__setattr__(obj, f.name, self._dec(v[f.name]))
            return obj
        raise ValueError("JsonCodec: nieznany format zapisu")

    def _type(self, name: str) -> type:
        if name not in self._types:
            raise ValueError(f"JsonCodec: klasa {name} nie jest dozwolona")
        return self._types[name]

    def loads(self, s: str) -> Any:
        return self._dec(json.loads(s))
