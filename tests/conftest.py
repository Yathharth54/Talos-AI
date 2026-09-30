"""Test-wide setup. Runs before any test imports.

Disables LangSmith tracing during tests so we don't spam the LangSmith
quota with mock-LLM traces (which are noisy and useless). Live tests
that need tracing can re-enable it explicitly.

Integration tests (`@pytest.mark.integration`) wipe and migrate a real
Postgres. They run only when BOTH hold:
- DATABASE_URL is exported in the shell (a value from .env is ignored:
  it is read here, before talos.config.settings loads .env), and
- the run selects them with `-m integration`.
So a plain `uv run pytest` can never touch a database.
"""

from __future__ import annotations

import os

import pytest

os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_TRACING_V2", None)

# Snapshot before any talos import can load .env into os.environ.
_EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def integration_skip_reason(explicit_url: str, markexpr: str) -> str | None:
    """Why integration tests must be skipped in this run, or None to run them.

    Args:
        explicit_url: DATABASE_URL as exported in the shell (not from .env).
        markexpr: The `-m` expression pytest was given ("" if none).
    """
    if not explicit_url:
        return "needs DATABASE_URL exported (a disposable Postgres); see README Tests"
    expr = markexpr.replace(" ", "")
    if "integration" not in expr or "notintegration" in expr:
        return "integration test: run with -m integration"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration tests unless explicitly selected with a database."""
    reason = integration_skip_reason(_EXPLICIT_DATABASE_URL, config.option.markexpr or "")
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database_url() -> str:
    """The explicitly exported DATABASE_URL (integration tests only)."""
    return _EXPLICIT_DATABASE_URL
