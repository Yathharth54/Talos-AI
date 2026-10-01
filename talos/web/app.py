"""create_app(): the FastAPI instance, its lifespan, routers and static files.

Startup (spec 02 §3), in `open_services()` and the lifespan:

1. Refuse to start without DATABASE_URL.
2. `alembic upgrade head` (in a thread: Alembic runs its own event loop).
3. The Postgres checkpointer and `build_app(saver)`, or the fake graph
   with a temporary vault copy when TALOS_FAKE_GRAPH=1.
4. Recovery: runs left `running` by a dead process become `failed`.
5. The stored "Ask before running code" setting is applied.
6. Shutdown stops active runs, then closes the pool and the engine.

Run with one uvicorn worker only: run state and the vault are per process.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from talos.config import settings
from talos.web.deps import (
    ASK_BEFORE_EXEC,
    ApiError,
    Services,
    error_response,
    install_error_handlers,
)
from talos.web.routes import health, runs, sessions, vault
from talos.web.routes import settings as settings_routes
from talos.web.runner import RunManager
from talos.web.security import install_log_redaction

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024
DEV_ORIGIN = "http://127.0.0.1:5173"
STATIC_DIR = settings.PROJECT_ROOT / "frontend" / "dist"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
WRITE_METHODS = frozenset({"POST", "PATCH", "DELETE"})
_ORIGIN = re.compile(r"^https?://(?P<host>\[[0-9a-fA-F:.]+\]|[^/:\[\]]+)(?::\d+)?$")

ServicesFactory = Callable[[], Awaitable[Services]]


class BodySizeLimit:
    """Reject request bodies over `max_bytes` (by Content-Length) with 413."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length is not None and length.isdigit() and int(length) > self.max_bytes:
                response = error_response(413, "too_large", "Request body is over 64 KB.")
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class LocalOriginOnly:
    """Refuse writes (POST, PATCH, DELETE) whose `Origin` isn't a local page, with 403.

    A browser sends `Origin` on cross-site writes; a page on another site
    must not be able to start runs or save keys through the local API.
    Requests without `Origin` (curl, same-origin GETs) pass.

    Args:
        app: The wrapped ASGI app.
        hosts: Hosts an origin may name (any port, http or https).
        extra_origins: Exact origins also allowed (the Vite dev server).
    """

    def __init__(
        self, app: ASGIApp, hosts: tuple[str, ...], extra_origins: tuple[str, ...] = ()
    ) -> None:
        self.app = app
        self.hosts = frozenset(h.lower() for h in hosts)
        self.extra_origins = frozenset(extra_origins)

    def allowed(self, origin: str) -> bool:
        """Whether `origin` is an http(s) origin on one of the allowed hosts."""
        if origin in self.extra_origins:
            return True
        match = _ORIGIN.match(origin)
        return match is not None and match.group("host").lower() in self.hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in WRITE_METHODS:
            origin = Headers(scope=scope).get("origin")
            if origin is not None and not self.allowed(origin):
                response = error_response(
                    403, "bad_origin", "Requests from other sites can't change Talos."
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def open_services() -> Services:
    """Production services from the environment (see the module doc)."""
    from talos.graph import build_app
    from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
    from talos.persistence.db import dispose_db, init_db
    from talos.persistence.migrations import upgrade_head
    from talos.vault.manager import SkillManager
    from talos.web.fake_graph import FakeDriver, make_fake_vault
    from talos.web.runner import GraphDriver
    from talos.web.store import PgStore

    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. The web app needs Postgres, for example "
            "DATABASE_URL=postgresql+psycopg://talos:talos@localhost:5432/talos "
            "(see README, Web app)."
        )
    await asyncio.to_thread(upgrade_head)
    store = PgStore(init_db())
    if settings.FAKE_GRAPH:
        fake_vault, fake_root = make_fake_vault()
        log.warning("TALOS_FAKE_GRAPH=1: scripted runs, vault copy at %s", fake_root)

        async def close_fake() -> None:
            await dispose_db()
            shutil.rmtree(fake_root, ignore_errors=True)

        return Services(
            store=store,
            driver=FakeDriver(fake_vault, event_delay_ms=settings.FAKE_EVENT_DELAY_MS),
            vault=fake_vault,
            fake_graph=True,
            aclose=close_fake,
        )
    try:
        saver = await open_postgres_saver()
    except BaseException:
        await dispose_db()
        raise

    async def close_real() -> None:
        await close_postgres_saver(saver)
        await dispose_db()

    return Services(
        store=store,
        driver=GraphDriver(build_app(saver)),
        vault=SkillManager(),
        aclose=close_real,
    )


def create_app(
    services: ServicesFactory | None = None,
    *,
    static_dir: Path | None = STATIC_DIR,
    dev: bool | None = None,
) -> FastAPI:
    """Build the app.

    Args:
        services: Builds the services at startup; default `open_services`
            (Postgres). Tests pass a factory with MemoryStore and FakeDriver.
        static_dir: The built frontend; served at / when it exists.
        dev: Allow CORS from Vite's dev server (default TALOS_WEB_DEV).

    Only local Host headers are answered (127.0.0.1, localhost, [::1] and
    TALOS_WEB_ALLOWED_HOSTS), and writes from non-local origins get 403.
    """
    factory = services or open_services

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        install_log_redaction()
        built = await factory()
        manager: RunManager | None = None
        try:
            manager = RunManager(built.store, built.driver)
            recovered = await built.store.recover()
            if recovered:
                log.warning("marked %d interrupted run(s) as failed", len(recovered))
            ask = await built.store.get_setting(ASK_BEFORE_EXEC)
            if ask is not None:
                settings.set_auto_approve_override(not bool(ask))
            app.state.services = built
            app.state.manager = manager
            yield
        finally:
            try:
                if manager is not None:
                    await manager.shutdown()
            finally:
                settings.set_auto_approve_override(None)
                if built.aclose is not None:
                    await built.aclose()

    app = FastAPI(
        title="Talos", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    install_error_handlers(app)
    for router in (
        health.router,
        sessions.router,
        runs.router,
        vault.router,
        settings_routes.router,
    ):
        app.include_router(router, prefix="/api")
    dev_mode = settings.WEB_DEV if dev is None else dev
    hosts = (*LOCAL_HOSTS, *settings.WEB_ALLOWED_HOSTS)
    # add_middleware wraps: the last one added is the outermost.
    app.add_middleware(
        LocalOriginOnly, hosts=hosts, extra_origins=(DEV_ORIGIN,) if dev_mode else ()
    )
    app.add_middleware(BodySizeLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))
    if dev_mode:  # outermost, so 413 and 403 responses carry CORS headers too
        app.add_middleware(
            CORSMiddleware, allow_origins=[DEV_ORIGIN], allow_methods=["*"], allow_headers=["*"]
        )
    if static_dir is not None:
        _serve_frontend(app, static_dir)
    return app


def _serve_frontend(app: FastAPI, root: Path) -> None:
    """Files from the built frontend; index.html for any other non-/api path."""
    root = root.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", "No such API endpoint.")
        index = root / "index.html"
        if not index.is_file():
            raise ApiError(404, "not_found", "The frontend isn't built (frontend/dist).")
        if path:
            try:
                target = (root / path).resolve()
                if target.is_relative_to(root) and target.is_file():
                    return FileResponse(target)
            except (ValueError, OSError):  # e.g. a NUL byte from %00
                pass
        return FileResponse(index)
