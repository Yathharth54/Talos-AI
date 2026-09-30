"""Path and persistence settings are read from the environment (spec 01 §3)."""

from __future__ import annotations

import importlib
from pathlib import Path

import dotenv
import pytest

from talos.config import settings

_VARS = (
    "TALOS_VAULT_DIR",
    "TALOS_WORKSPACE_DIR",
    "TALOS_DOTENV_PATH",
    "DATABASE_URL",
    "TALOS_CHECKPOINTER",
    "TALOS_WEB_HOST",
    "TALOS_WEB_PORT",
    "TALOS_FAKE_GRAPH",
    "TALOS_WEB_DEV",
)


@pytest.fixture
def reload_settings(monkeypatch):
    """Reload settings under a patched environment, then restore it."""

    # Keep a developer's real .env out of these tests.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def _reload(**env: str):
        for name in _VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(settings)

    yield _reload
    monkeypatch.undo()
    importlib.reload(settings)


def test_path_defaults_live_under_the_repo(reload_settings):
    s = reload_settings()
    assert s.VAULT_DIR == s.PROJECT_ROOT / "talos" / "vault"
    assert s.VAULT_TOOLS_DIR == s.VAULT_DIR / "tools"
    assert s.VAULT_MANIFEST_PATH == s.VAULT_DIR / "manifest.json"
    assert s.WORKSPACE_DIR == s.PROJECT_ROOT / "workspace"
    assert s.DOTENV_PATH == s.PROJECT_ROOT / ".env"


def test_path_overrides_come_from_env(reload_settings, tmp_path: Path):
    s = reload_settings(
        TALOS_VAULT_DIR=str(tmp_path / "v"),
        TALOS_WORKSPACE_DIR=str(tmp_path / "w"),
        TALOS_DOTENV_PATH=str(tmp_path / "keys.env"),
    )
    assert s.VAULT_DIR == tmp_path / "v"
    assert s.VAULT_TOOLS_DIR == tmp_path / "v" / "tools"
    assert s.VAULT_MANIFEST_PATH == tmp_path / "v" / "manifest.json"
    assert s.WORKSPACE_DIR == tmp_path / "w"
    assert s.DOTENV_PATH == tmp_path / "keys.env"


def test_empty_path_override_falls_back_to_default(reload_settings):
    s = reload_settings(TALOS_VAULT_DIR="")
    assert s.VAULT_DIR == s.PROJECT_ROOT / "talos" / "vault"


def test_database_defaults(reload_settings):
    s = reload_settings()
    assert s.CHECKPOINTER == "memory"
    assert s.DATABASE_URL == ""


def test_checkpointer_is_normalised(reload_settings):
    s = reload_settings(TALOS_CHECKPOINTER=" Postgres ", DATABASE_URL="postgresql+psycopg://x")
    assert s.CHECKPOINTER == "postgres"
    assert s.DATABASE_URL == "postgresql+psycopg://x"


def test_unknown_checkpointer_is_rejected(reload_settings):
    with pytest.raises(ValueError, match="TALOS_CHECKPOINTER"):
        reload_settings(TALOS_CHECKPOINTER="sqlite")


def test_hitl_writes_to_the_configured_dotenv():
    from talos.agents import hitl

    assert hitl.DOTENV_PATH == settings.DOTENV_PATH


def test_cli_warns_but_stays_in_memory_when_postgres_is_asked(monkeypatch, caplog):
    from talos import main as main_mod
    from talos.graph import app, checkpointer

    monkeypatch.setattr(main_mod.settings, "CHECKPOINTER", "postgres")
    with caplog.at_level("WARNING", logger="talos.main"):
        assert main_mod.warn_if_postgres_checkpointer() is True
    assert "in-memory" in caplog.text
    assert app.checkpointer is checkpointer

    monkeypatch.setattr(main_mod.settings, "CHECKPOINTER", "memory")
    assert main_mod.warn_if_postgres_checkpointer() is False


def test_web_settings_default_to_a_local_real_server(reload_settings):
    s = reload_settings()
    assert (s.WEB_HOST, s.WEB_PORT, s.FAKE_GRAPH, s.WEB_DEV) == ("127.0.0.1", 8000, False, False)


def test_web_settings_come_from_env(reload_settings):
    s = reload_settings(
        TALOS_WEB_HOST="0.0.0.0", TALOS_WEB_PORT="9001", TALOS_FAKE_GRAPH="1", TALOS_WEB_DEV="true"
    )
    assert (s.WEB_HOST, s.WEB_PORT, s.FAKE_GRAPH, s.WEB_DEV) == ("0.0.0.0", 9001, True, True)


def test_auto_approve_override_wins_over_the_env(monkeypatch):
    monkeypatch.setenv("TALOS_AUTO_APPROVE_EXEC", "true")
    assert settings.auto_approve_exec() is True
    try:
        settings.set_auto_approve_override(False)
        assert settings.auto_approve_exec() is False
        monkeypatch.setenv("TALOS_AUTO_APPROVE_EXEC", "false")
        settings.set_auto_approve_override(True)
        assert settings.auto_approve_exec() is True
    finally:
        settings.set_auto_approve_override(None)
    assert settings.auto_approve_exec() is False  # back to the env var


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_web_port_falls_back_to_8000(reload_settings, value):
    assert reload_settings(TALOS_WEB_PORT=value).WEB_PORT == 8000
