"""App-level behaviour: lifespan, errors, limits, CORS, static files, entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.config import settings
from talos.web.app import open_services
from tests.web.conftest import make_app, open_client


async def test_startup_applies_the_stored_setting_and_recovers(services):
    await services.store.set_setting("ask_before_exec", False)
    session = await services.store.create_session()
    orphan, _ = await services.store.begin_run(session.id, "q", "q", None)
    app = make_app(services)
    async for _client in open_client(app):
        assert settings.auto_approve_exec() is True
        assert (await services.store.get_run(orphan.id)).status == "failed"
    assert settings._auto_approve_override is None  # shutdown resets the override


async def test_open_services_refuses_without_a_database(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        await open_services()


async def test_oversized_bodies_get_413(client):
    response = await client.post("/api/anything", json={"text": "x" * (65 * 1024)})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"


async def test_unknown_api_paths_use_the_error_shape(client):
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_cors_only_in_dev_mode(services):
    origin = {"Origin": "http://127.0.0.1:5173"}
    async for client in open_client(make_app(services, dev=False)):
        response = await client.get("/api/health", headers=origin)
        assert "access-control-allow-origin" not in response.headers
    async for client in open_client(make_app(services, dev=True)):
        response = await client.get("/api/health", headers=origin)
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        other = await client.get("/api/health", headers={"Origin": "http://evil.test"})
        assert "access-control-allow-origin" not in other.headers


async def test_frontend_is_served_with_an_index_fallback(services, tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Talos</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    async for client in open_client(make_app(services, static_dir=dist)):
        assert "Talos" in (await client.get("/")).text
        assert (await client.get("/assets/app.js")).text == "console.log(1)"
        assert "Talos" in (await client.get("/sessions/whatever")).text
        assert "no" != (await client.get("/../secret.txt")).text
        api = await client.get("/api/nope")
        assert api.status_code == 404 and api.json()["error"]["code"] == "not_found"


async def test_foreign_host_headers_are_rejected(client):
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 sends Host: evil.example."""
    response = await client.get("/api/health", headers={"Host": "evil.example"})
    assert response.status_code == 400
    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"):
        assert (await client.get("/api/health", headers={"Host": host})).status_code == 200


async def test_extra_allowed_hosts_come_from_settings(services, monkeypatch):
    monkeypatch.setattr(settings, "WEB_ALLOWED_HOSTS", ("talos.lan",))
    async for client in open_client(make_app(services)):
        response = await client.get("/api/health", headers={"Host": "talos.lan:8000"})
        assert response.status_code == 200
        assert (await client.get("/api/health", headers={"Host": "x.lan"})).status_code == 400


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_foreign_origins_cannot_write(client, method):
    response = await client.request(
        method, "/api/sessions", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "bad_origin"


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8000", "https://localhost", "http://localhost:3000", "http://[::1]:8000"],
)
async def test_local_origins_can_write(client, origin):
    response = await client.post("/api/sessions", headers={"Origin": origin})
    assert response.status_code == 201


@pytest.mark.parametrize("origin", ["null", "http://127.0.0.1.evil.example", "file://"])
async def test_odd_origins_cannot_write(client, origin):
    response = await client.post("/api/sessions", headers={"Origin": origin})
    assert response.status_code == 403


async def test_reads_and_originless_writes_are_unaffected(client):
    assert (await client.get("/api/health", headers={"Origin": "https://evil.example"})).is_success
    assert (await client.post("/api/sessions")).status_code == 201


async def test_the_dev_origin_can_write_in_dev(services):
    async for client in open_client(make_app(services, dev=True)):
        response = await client.post("/api/sessions", headers={"Origin": "http://127.0.0.1:5173"})
        assert response.status_code == 201


async def test_413_carries_cors_headers_in_dev(services):
    """CORS is the outermost middleware, so the dev frontend can read a 413."""
    async for client in open_client(make_app(services, dev=True)):
        response = await client.post(
            "/api/anything",
            json={"text": "x" * (65 * 1024)},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert response.status_code == 413
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
