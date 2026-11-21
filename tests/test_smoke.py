import os
import sys
from pathlib import Path

os.environ["LLM_MOCK"] = "1"
os.environ["DB_PATH"] = "data/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from backend.llm import ask_llm  # noqa: E402
from backend.main import app  # noqa: E402
from backend.parsers import parse_file  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["ok"] is True


def test_ask_mock():
    assert ask_llm("hej").startswith("[MOCK]")


def test_parse_xml_strips_namespaces():
    kind, data = parse_file(b'<n:A xmlns:n="u"><n:B>1</n:B><n:B>2</n:B></n:A>', "x.xml")
    assert kind == "xml" and data == {"A": {"B": ["1", "2"]}}


def test_parse_csv_semicolon():
    kind, df = parse_file("a;b\n1;2\n".encode(), "x.csv")
    assert kind == "table" and list(df.columns) == ["a", "b"]


def test_upload_endpoint():
    r = client.post("/upload", files={"file": ("t.txt", b"tekst testowy")})
    assert r.status_code == 200 and r.json()["kind"] == "text"
