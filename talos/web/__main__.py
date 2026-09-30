"""`talos-web` / `python -m talos.web`: serve the API with uvicorn.

One worker, always: run state and the vault are per process, and startup
recovery fails every `running` run, which would break a second worker's
live runs. Binds to 127.0.0.1 by default; there is no auth.
"""

from __future__ import annotations

import uvicorn

from talos.config import settings
from talos.config.logging import setup_logging


def main() -> None:
    """Run the app on TALOS_WEB_HOST:TALOS_WEB_PORT (default 127.0.0.1:8000)."""
    setup_logging()
    uvicorn.run(
        "talos.web.app:create_app",
        factory=True,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        workers=1,
    )


if __name__ == "__main__":
    main()
