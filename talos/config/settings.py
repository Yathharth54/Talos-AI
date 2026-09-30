"""Centralized config: loads .env once, exposes typed constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

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


def auto_approve_exec() -> bool:
    """Whether python_exec/shell_exec run without asking the user first.

    Off by default: both run model-written code on the host. Read at call
    time (not import time) so unattended runners and tests can flip it.
    """
    return os.environ.get("TALOS_AUTO_APPROVE_EXEC", "false").lower() in {"1", "true", "yes"}

VAULT_DIR = PROJECT_ROOT / "talos" / "vault"
VAULT_TOOLS_DIR = VAULT_DIR / "tools"
VAULT_MANIFEST_PATH = VAULT_DIR / "manifest.json"

# Where Talos writes files when the user doesn't specify an absolute path.
# All relative paths in file_read/file_write get anchored here. Gitignored.
WORKSPACE_DIR = PROJECT_ROOT / "workspace"


def key_status() -> dict[str, bool]:
    """Return which keys are present (True) vs missing (False). For smoke tests."""
    return {
        "OPENROUTER_API_KEY": bool(OPENROUTER_API_KEY),
        "TAVILY_API_KEY": bool(TAVILY_API_KEY),
        "JINA_API_KEY": bool(JINA_API_KEY),
        "LANGSMITH_API_KEY": bool(LANGSMITH_API_KEY),
    }
