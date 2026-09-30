"""FastAPI dependencies, the services bundle, and the one error shape.

Every error response is `{"error": {"code": ..., "message": ...}}`
(spec 02 §4). Validation errors never echo the request body back, so a
pasted key can't come back in a 422.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from talos.vault.manager import SkillManager
from talos.web.runner import Driver, RunError, RunManager
from talos.web.store import Store

# The app_settings key for "Ask before running code".
ASK_BEFORE_EXEC = "ask_before_exec"


@dataclass
class Services:
    """Everything the app needs, built once at startup."""

    store: Store
    driver: Driver
    vault: SkillManager
    fake_graph: bool = False
    aclose: Callable[[], Awaitable[None]] | None = None


class ApiError(Exception):
    """An error a route raises on purpose: HTTP status, code and message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def not_found(what: str) -> ApiError:
    """A 404 `not_found` error.

    Args:
        what: The missing thing, e.g. "Session".

    Returns:
        An ApiError with the message "{what} not found."
    """
    return ApiError(404, "not_found", f"{what} not found.")


def error_response(status: int, code: str, message: str, **extra: str) -> JSONResponse:
    """`{"error": {"code", "message", ...extra}}` with the given status."""
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 413: "too_large"}


def install_error_handlers(app: FastAPI) -> None:
    """Map every error to the one JSON shape."""

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RunError)
    async def _run(_: Request, exc: RunError) -> JSONResponse:
        return error_response(exc.status, exc.code, str(exc), **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = str(first.get("msg") or "Invalid request.").removeprefix("Value error, ")
        return error_response(422, "invalid_request", f"{where}: {message}" if where else message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))


def get_services(request: Request) -> Services:
    """The services bundle built at startup (FastAPI dependency)."""
    return request.app.state.services


def get_store(request: Request) -> Store:
    """The app's Store (FastAPI dependency)."""
    return request.app.state.services.store


def get_vault(request: Request) -> SkillManager:
    """The vault the app runs against (FastAPI dependency)."""
    return request.app.state.services.vault


def get_manager(request: Request) -> RunManager:
    """The app's RunManager (FastAPI dependency)."""
    return request.app.state.manager
