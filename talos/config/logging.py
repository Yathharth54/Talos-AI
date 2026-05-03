"""Logging setup. Imported once at REPL startup; no-op everywhere else.

Why a module: the CLAUDE.md convention says "no print statements; use
logging." Centralising format + level here keeps the rest of the code
clean of `logging.basicConfig(...)` calls.
"""

from __future__ import annotations

import logging
import os


def setup_logging() -> None:
    """Initialise root logger formatting. Idempotent."""
    level = os.environ.get("TALOS_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # The HTTP libs are noisy at INFO. Quiet them unless DEBUG is on.
    if level not in {"DEBUG"}:
        for noisy in ("httpx", "httpcore", "openai", "urllib3", "langsmith"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


# Convenience for callers
get_logger = logging.getLogger
