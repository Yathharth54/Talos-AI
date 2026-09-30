"""Wait until Postgres accepts connections (Docker entrypoint).

`python -m talos.persistence.wait` blocks until DATABASE_URL answers or
TALOS_DB_WAIT_TIMEOUT seconds (default 60) pass, then exits 0 or 1.
Compose already waits for the db healthcheck; this also covers a database
that is up but still restarting, and a DATABASE_URL pointing elsewhere.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any

import psycopg

from talos.config import settings
from talos.persistence.db import libpq_url

logger = logging.getLogger(__name__)


def wait_for_db(
    url: str,
    timeout: float = 60.0,
    interval: float = 1.0,
    *,
    connect: Callable[..., Any] = psycopg.connect,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Block until a connection to `url` succeeds.

    Args:
        url: Postgres URL in any form `libpq_url` accepts.
        timeout: Seconds to keep trying.
        interval: Seconds between attempts.
        connect: psycopg.connect, replaceable in tests.
        sleep: time.sleep, replaceable in tests.
        clock: time.monotonic, replaceable in tests.

    Raises:
        ValueError: If `url` is not a Postgres URL.
        TimeoutError: If no attempt succeeded within `timeout`.
    """
    conninfo = libpq_url(url)
    deadline = clock() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            connect(conninfo, connect_timeout=3).close()
            logger.info("database is ready after %d attempt(s)", attempt)
            return
        except psycopg.OperationalError as e:
            if clock() >= deadline:
                raise TimeoutError(f"database not reachable after {timeout:g}s: {e}") from e
            logger.info("waiting for the database (attempt %d): %s", attempt, e)
            sleep(interval)


def main() -> int:
    """CLI entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL is not set; the web app needs Postgres.")
        return 1
    timeout = float(os.environ.get("TALOS_DB_WAIT_TIMEOUT", "60"))
    try:
        wait_for_db(settings.DATABASE_URL, timeout=timeout)
    except (TimeoutError, ValueError) as e:
        logger.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
