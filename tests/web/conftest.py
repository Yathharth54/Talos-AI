"""App fixtures: the real FastAPI app on MemoryStore + FakeDriver, no database.

httpx's ASGITransport doesn't run the lifespan, so `client` enters it
explicitly. It also buffers each response until the app finishes it, so an
SSE request returns once its stream closes (after `run.finished`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from talos.agents import hitl
from talos.vault.manager import SkillManager
from talos.web.app import create_app
from talos.web.deps import Services
from talos.web.fake_graph import FakeDriver
from talos.web.store import MemoryStore


@pytest.fixture
def dotenv(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / ".env"
    monkeypatch.setattr(hitl, "DOTENV_PATH", path)
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    return path


@pytest.fixture
def services(tmp_path: Path, dotenv: Path) -> Services:
    vault = SkillManager(vault_dir=tmp_path / "vault")
    return Services(store=MemoryStore(), driver=FakeDriver(vault), vault=vault, fake_graph=True)


def make_app(services: Services, **kwargs: Any) -> FastAPI:
    async def factory() -> Services:
        return services

    return create_app(factory, **{"static_dir": None, "dev": False, **kwargs})


@pytest.fixture
def app(services: Services) -> FastAPI:
    return make_app(services)


async def open_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async for c in open_client(app):
        yield c


def parse_sse(text: str) -> list[dict[str, Any]]:
    """`[{id, event, data}]` from an SSE body; comment lines are skipped."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, Any] = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if fields:
            fields["data"] = json.loads(fields["data"])
            events.append(fields)
    return events


async def wait_for_status(client: httpx.AsyncClient, run_id: str, *statuses: str) -> dict:
    """Poll GET /api/runs/{id} until its status is one of `statuses` (fake runs are instant)."""
    import asyncio

    for _ in range(200):
        body = (await client.get(f"/api/runs/{run_id}")).json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} never reached {statuses}: {body['status']}")
