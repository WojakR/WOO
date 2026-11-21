import inspect
import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

os.environ["LLM_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import schemas as s  # noqa: E402


def test_every_schema_produces_json_schema():
    models = [m for _, m in inspect.getmembers(s, inspect.isclass)
              if issubclass(m, BaseModel) and m.__module__ == s.__name__]
    assert len(models) > 30
    for m in models:
        assert m.model_json_schema()["title"] == m.__name__


def test_scores_accept_only_legal_points():
    assert s.ScoresIn(punkty={"RZETELNOSC": 3, "KOMUNIKACJA": None}).punkty["RZETELNOSC"] == 3
    with pytest.raises(ValidationError):
        s.ScoresIn(punkty={"RZETELNOSC": 4})


def test_at_most_three_additional_criteria():
    with pytest.raises(ValidationError):
        s.AdditionalCriteriaIn(kody=["A", "B", "C", "D"])


def test_api_error_shape():
    err = s.ApiError(kod="PRZEJSCIE_NIEDOZWOLONE", komunikat="Ocena nie jest w etapie rozmowy oceniającej.",
                     walidacje=[s.Walidacja(kod="UZASADNIENIE_WYMAGANE", pole="czesc_ii.uzasadnienie",
                                            waga=s.Waga.BLAD, komunikat="Uzasadnienie jest obowiązkowe.")])
    assert err.model_dump()["walidacje"][0]["waga"] == "BLAD"
