"""Unit tests for the live e2e backend harness (no database, no server)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "frontend" / "e2e" / "serve_backend.py"


def _load():
    spec = importlib.util.spec_from_file_location("serve_backend", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_child_env_strips_keys_and_points_at_tmp(tmp_path: Path) -> None:
    mod = _load()
    base = {
        "PATH": "/bin",
        "OPENROUTER_API_KEY": "sk-real",
        "OPENWEATHERMAP_API_KEY": "real",
        "LANGSMITH_TRACING": "true",
        "TALOS_AUTO_APPROVE_EXEC": "true",
        "DATABASE_URL": "postgresql+psycopg://me:me@localhost:5432/mine",
    }
    env = mod.child_env(
        base, tmp_path, "postgresql+psycopg://talos:talos@localhost:55432/talos_e2e"
    )
    assert "OPENROUTER_API_KEY" not in env
    assert "OPENWEATHERMAP_API_KEY" not in env
    assert "LANGSMITH_TRACING" not in env
    assert "TALOS_AUTO_APPROVE_EXEC" not in env
    assert env["DATABASE_URL"].endswith("/talos_e2e")
    assert env["TALOS_FAKE_GRAPH"] == "1"
    assert env["TALOS_VAULT_DIR"] == str(tmp_path / "vault")
    assert env["TALOS_WORKSPACE_DIR"] == str(tmp_path / "workspace")
    assert env["TALOS_DOTENV_PATH"] == str(tmp_path / ".env")
    assert env["TALOS_WEB_HOST"] == "127.0.0.1"
    assert env["TALOS_WEB_PORT"] == "8765"
    assert env["PATH"] == "/bin"


def test_admin_url_targets_the_maintenance_database() -> None:
    mod = _load()
    name, admin = mod.split_db_url("postgresql+psycopg://talos:talos@localhost:55432/talos_e2e")
    assert name == "talos_e2e"
    assert admin == "postgresql://talos:talos@localhost:55432/postgres"


def test_refuses_a_database_that_is_not_an_e2e_one() -> None:
    mod = _load()
    with pytest.raises(SystemExit):
        mod.split_db_url("postgresql+psycopg://talos:talos@localhost:55432/talos")


def test_prepare_tmp_wipes_and_recreates(tmp_path: Path) -> None:
    mod = _load()
    root = tmp_path / ".e2e-tmp"
    (root / "vault" / "tools").mkdir(parents=True)
    (root / "vault" / "tools" / "old.py").write_text("x = 1\n")
    mod.prepare_tmp(root)
    assert (root / "vault" / "tools").is_dir()
    assert not (root / "vault" / "tools" / "old.py").exists()
    assert (root / "workspace").is_dir()
    assert (root / ".env").read_text() == ""
