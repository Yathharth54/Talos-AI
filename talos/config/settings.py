"""Centralized config: loads .env once, exposes typed constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY", "")
LANGSMITH_TRACING = os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "talos-ai")

SUBPROCESS_TIMEOUT = int(os.environ.get("TALOS_SUBPROCESS_TIMEOUT", "10"))
FORGE_MAX_RETRIES = int(os.environ.get("TALOS_FORGE_MAX_RETRIES", "3"))

VAULT_DIR = PROJECT_ROOT / "talos" / "vault"
VAULT_TOOLS_DIR = VAULT_DIR / "tools"
VAULT_MANIFEST_PATH = VAULT_DIR / "manifest.json"


def key_status() -> dict[str, bool]:
    """Return which keys are present (True) vs missing (False). For smoke tests."""
    return {
        "OPENAI_API_KEY": bool(OPENAI_API_KEY),
        "TAVILY_API_KEY": bool(TAVILY_API_KEY),
        "JINA_API_KEY": bool(JINA_API_KEY),
        "LANGSMITH_API_KEY": bool(LANGSMITH_API_KEY),
    }
