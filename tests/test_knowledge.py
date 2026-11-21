"""T21: knowledge base in the app – list, document, full-text search, 404."""
from fastapi.testclient import TestClient

from app.api.knowledge import slugify
from backend.main import app

client = TestClient(app)


def test_list_starts_with_the_manual_and_has_the_regulations():
    docs = client.get("/api/knowledge").json()
    assert docs[0]["slug"] == "podrecznik" and docs[0]["rodzaj"] == "PODRECZNIK"
    slugs = {d["slug"]: d for d in docs}
    assert slugs["rozporzadzenie-oceny-okresowe-2016"]["rodzaj"] == "PRZEPISY"
    assert "ustawa-sc-wyciag-oceny" in slugs and all(d["tytul"] for d in docs)


def test_document_markdown_and_headings():
    d = client.get("/api/knowledge/podrecznik").json()
    assert d["tytul"].startswith("Podręcznik użytkownika") and d["tresc"].startswith("# Podręcznik")
    anchors = {h["kotwica"] for h in d["naglowki"]}
    assert "5-zapoznanie-na-papierze" in anchors and "administrator" in anchors
    law = client.get("/api/knowledge/ustawa-sc-wyciag-oceny").json()
    assert "Art. 83" in law["tresc"]


def test_manual_covers_every_role():
    text = client.get("/api/knowledge/podrecznik").json()["tresc"]
    for heading in ("## Oceniający", "## Oceniany", "## Dział kadr", "## Administrator"):
        assert heading in text


def test_search():
    r = client.get("/api/knowledge/search", params={"q": "sprzeciw"}).json()
    assert r["wyniki"] and r["wyniki"][0]["rodzaj"] == "PODRECZNIK"
    assert any(w["slug"] == "ustawa-sc-wyciag-oceny" for w in r["wyniki"])
    hit = next(w for w in r["wyniki"] if w["slug"] == "ustawa-sc-wyciag-oceny")
    assert "sprzeciw" in hit["fragment"].casefold() and hit["trafienia"] >= 1
    assert client.get("/api/knowledge/search", params={"q": "ab"}).json()["wyniki"] == []
    assert client.get("/api/knowledge/search", params={"q": "zzzqqqxxx"}).json()["wyniki"] == []


def test_search_is_case_and_whitespace_insensitive():
    a = client.get("/api/knowledge/search", params={"q": "FIKCJA  zapoznania"}).json()["wyniki"]
    assert a and a[0]["slug"] == "podrecznik"


def test_unknown_document_is_404():
    r = client.get("/api/knowledge/nie-ma-takiego")
    assert r.status_code == 404 and "nie-ma-takiego" in r.json()["komunikat"]


def test_slugify_matches_the_ui_rule():
    assert slugify("5. Zapoznanie na papierze") == "5-zapoznanie-na-papierze"
    assert slugify("Dział kadr – raporty") == "dzial-kadr-raporty"
