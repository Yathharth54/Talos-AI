"""Start talos-web for the live Playwright suite, isolated from real data.

Run from the repo root: ``uv run python frontend/e2e/serve_backend.py``.
Playwright's webServer starts it; see frontend/playwright.live.config.ts.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger("talos.e2e")

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / "frontend" / ".e2e-tmp"
DEFAULT_DB = "postgresql+psycopg://talos:talos@localhost:55432/talos_e2e"
PORT = "8765"
# The fake graph waits this long before each event (TALOS_FAKE_EVENT_DELAY_MS), so
# 05-stop and 06-reload act on a run that is still going on the server. A Caesar
# forge (70 events) then takes about 1.8 s on the server.
EVENT_DELAY_MS = "25"
# Every TALOS_* knob is the harness's own: none passes through from the shell.
_DROP_PREFIXES = ("LANGSMITH_", "TALOS_")
_DROP_NAMES = {"DATABASE_URL"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def split_db_url(url: str) -> tuple[str, str]:
    """Split a database URL into the database name and an admin URL.

    Refuses any database whose name doesn't end in ``_e2e``, or that isn't on
    this machine, because the harness drops it.

    Args:
        url: SQLAlchemy-style Postgres URL of the e2e database.

    Returns:
        The database name and the libpq URL of the server's ``postgres`` database.
    """
    parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    name = parts.path.lstrip("/")
    if not name.endswith("_e2e"):
        raise SystemExit(f"E2E_DATABASE_URL must name a *_e2e database, got {name!r}")
    if parts.hostname not in _LOCAL_HOSTS:
        raise SystemExit(f"E2E_DATABASE_URL must be on localhost, got {parts.hostname!r}")
    return name, parts._replace(path="/postgres").geturl()


def recreate_database(url: str) -> None:
    """Drop and create the e2e database.

    Args:
        url: SQLAlchemy-style Postgres URL of the e2e database.
    """
    import psycopg
    from psycopg import sql

    name, admin = split_db_url(url)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    logger.info("recreated database %s", name)


def prepare_tmp(root: Path) -> None:
    """Wipe and recreate the vault, workspace and .env under ``root``.

    Args:
        root: The temporary folder holding the e2e run's state.
    """
    shutil.rmtree(root, ignore_errors=True)
    (root / "vault" / "tools").mkdir(parents=True)
    (root / "workspace").mkdir()
    (root / ".env").write_text("", encoding="utf-8")


def child_env(base: dict[str, str], root: Path, db_url: str) -> dict[str, str]:
    """Build the server's environment: no real keys, tmp paths, fake graph.

    Args:
        base: The parent environment to start from.
        root: The temporary folder from ``prepare_tmp``.
        db_url: The e2e database URL.

    Returns:
        The environment to exec the server with.
    """
    env = {
        k: v
        for k, v in base.items()
        if not k.endswith("_API_KEY") and not k.startswith(_DROP_PREFIXES) and k not in _DROP_NAMES
    }
    env.update(
        DATABASE_URL=db_url,
        TALOS_FAKE_GRAPH="1",
        TALOS_FAKE_EVENT_DELAY_MS=EVENT_DELAY_MS,
        TALOS_VAULT_DIR=str(root / "vault"),
        TALOS_WORKSPACE_DIR=str(root / "workspace"),
        TALOS_DOTENV_PATH=str(root / ".env"),
        TALOS_WEB_HOST="127.0.0.1",
        TALOS_WEB_PORT=PORT,
    )
    return env


def main() -> None:
    """Prepare the isolated world, then replace this process with the server."""
    logging.basicConfig(level=logging.INFO)
    db_url = os.environ.get("E2E_DATABASE_URL") or DEFAULT_DB
    recreate_database(db_url)
    prepare_tmp(TMP)
    env = child_env(dict(os.environ), TMP, db_url)
    os.execve(sys.executable, [sys.executable, "-m", "talos.web"], env)


if __name__ == "__main__":
    main()
