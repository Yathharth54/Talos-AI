"""Centralized config: loads .env once, exposes typed constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Where HITL writes API keys, and the .env we load at startup. Read before
# load_dotenv so the file itself can't redirect where it is read from.
DOTENV_PATH = Path(os.environ.get("TALOS_DOTENV_PATH") or PROJECT_ROOT / ".env")
load_dotenv(DOTENV_PATH)

# All LLM calls go through OpenRouter's OpenAI-compatible endpoint.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
TALOS_MODEL = os.environ.get("TALOS_MODEL", "deepseek/deepseek-v4.1-flash")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY", "")
LANGSMITH_TRACING = os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "talos-ai")

SUBPROCESS_TIMEOUT = int(os.environ.get("TALOS_SUBPROCESS_TIMEOUT", "10"))
FORGE_MAX_RETRIES = int(os.environ.get("TALOS_FORGE_MAX_RETRIES", "3"))
# Per-request LLM timeout (seconds). The OpenAI SDK default is 600s, so a
# stalled provider response would otherwise hang a query for minutes.
LLM_TIMEOUT = float(os.environ.get("TALOS_LLM_TIMEOUT", "120"))
# Wall-clock limit (seconds) for one sandboxed forged-tool call.
TOOL_TIMEOUT = float(os.environ.get("TALOS_TOOL_TIMEOUT", "30"))


# Set by the web app from its "Ask before running code" setting. None means
# "no override": fall back to TALOS_AUTO_APPROVE_EXEC. The CLI never sets it.
_auto_approve_override: bool | None = None


def set_auto_approve_override(value: bool | None) -> None:
    """Override TALOS_AUTO_APPROVE_EXEC for this process (web app only).

    Args:
        value: True to run code without asking, False to always ask,
            None to go back to the environment variable.
    """
    global _auto_approve_override
    _auto_approve_override = value


def auto_approve_exec() -> bool:
    """Whether python_exec/shell_exec run without asking the user first.

    Off by default: both run model-written code on the host. Read at call
    time (not import time) so unattended runners and tests can flip it.
    The web app's setting (`set_auto_approve_override`) wins over the env var.
    """
    if _auto_approve_override is not None:
        return _auto_approve_override
    return os.environ.get("TALOS_AUTO_APPROVE_EXEC", "false").lower() in {"1", "true", "yes"}


# Vault location. TALOS_VAULT_DIR lets Docker mount the vault elsewhere.
VAULT_DIR = Path(os.environ.get("TALOS_VAULT_DIR") or PROJECT_ROOT / "talos" / "vault")
VAULT_TOOLS_DIR = VAULT_DIR / "tools"
VAULT_MANIFEST_PATH = VAULT_DIR / "manifest.json"

# Where Talos writes files when the user doesn't specify an absolute path.
# All relative paths in file_read/file_write get anchored here. Gitignored.
WORKSPACE_DIR = Path(os.environ.get("TALOS_WORKSPACE_DIR") or PROJECT_ROOT / "workspace")

# Persistence. Empty DATABASE_URL means no database (the CLI default).
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
CHECKPOINTER_KINDS = frozenset({"memory", "postgres"})
CHECKPOINTER = os.environ.get("TALOS_CHECKPOINTER", "memory").strip().lower() or "memory"
if CHECKPOINTER not in CHECKPOINTER_KINDS:
    raise ValueError(
        f"TALOS_CHECKPOINTER must be one of {sorted(CHECKPOINTER_KINDS)}, got {CHECKPOINTER!r}"
    )


# Web app (talos-web). One uvicorn worker only: runs and the vault are
# single-process state, and startup recovery fails every `running` run.
WEB_HOST = os.environ.get("TALOS_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEB_PORT = int(os.environ.get("TALOS_WEB_PORT", "").strip() or "8000")
FAKE_GRAPH = os.environ.get("TALOS_FAKE_GRAPH", "").strip().lower() in {"1", "true", "yes"}
WEB_DEV = os.environ.get("TALOS_WEB_DEV", "").strip().lower() in {"1", "true", "yes"}
# Host headers the web app answers besides 127.0.0.1, localhost and [::1]
# (DNS-rebinding guard). Comma-separated, e.g. "talos.lan,box.local".
WEB_ALLOWED_HOSTS = tuple(
    host.strip()
    for host in os.environ.get("TALOS_WEB_ALLOWED_HOSTS", "").split(",")
    if host.strip()
)


def key_status() -> dict[str, bool]:
    """Return which keys are present (True) vs missing (False). For smoke tests."""
    return {
        "OPENROUTER_API_KEY": bool(OPENROUTER_API_KEY),
        "TAVILY_API_KEY": bool(TAVILY_API_KEY),
        "JINA_API_KEY": bool(JINA_API_KEY),
        "LANGSMITH_API_KEY": bool(LANGSMITH_API_KEY),
    }
