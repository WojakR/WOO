"""One-command launcher (scripts/uruchom.py): install only when needed, .env from the example, free port."""
import importlib.util
import socket
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "uruchom", Path(__file__).resolve().parent.parent / "scripts" / "uruchom.py")
uruchom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uruchom)


def _fake_venv(tmp_path: Path) -> Path:
    venv_dir = tmp_path / ".venv"
    py = uruchom.venv_python(venv_dir)
    py.parent.mkdir(parents=True)
    py.write_text("")
    return venv_dir


def test_install_needed_for_new_venv_and_after_requirements_change(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi\n")
    assert uruchom.needs_install(tmp_path / ".venv", req)

    venv_dir = _fake_venv(tmp_path)
    assert uruchom.needs_install(venv_dir, req)  # no marker yet
    (venv_dir / uruchom.MARKER).write_text(uruchom.requirements_hash(req))
    assert not uruchom.needs_install(venv_dir, req)

    req.write_text("fastapi\nsqlmodel\n")
    assert uruchom.needs_install(venv_dir, req)


def test_env_created_from_example_once_and_never_overwritten(tmp_path):
    (tmp_path / ".env.example").write_text("AI_MODE=local\n")
    assert uruchom.ensure_env(tmp_path)
    assert (tmp_path / ".env").read_text() == "AI_MODE=local\n"

    (tmp_path / ".env").write_text("AI_MODE=off\n")
    assert not uruchom.ensure_env(tmp_path)
    assert (tmp_path / ".env").read_text() == "AI_MODE=off\n"


def test_busy_port_is_skipped():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert not uruchom.port_free("127.0.0.1", busy)
        assert uruchom.find_free_port("127.0.0.1", busy) != busy
