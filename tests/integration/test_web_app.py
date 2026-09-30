"""The web app on Postgres (spec 02 §11 Integration): a full fake-graph Caesar run,
and a restart mid-pause followed by a successful resume, with the fake graph
and with the real graph on the Postgres checkpointer."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.graph import build_app
from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
from talos.vault.manager import SkillManager
from talos.web.deps import Services
from talos.web.fake_graph import FakeDriver
from talos.web.runner import GraphDriver
from talos.web.store import PgStore
from tests.web import chunks
from tests.web.conftest import make_app, open_client, parse_sse, wait_for_status

pytestmark = pytest.mark.integration

CAESAR_Q = 'Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.'
PYTHON_Q = "Run this Python code and give me the output: print(sum(range(1, 101)))"


@pytest.fixture
def fake_services(factory, tmp_path: Path, monkeypatch):
    from talos.agents import hitl

    monkeypatch.setattr(hitl, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)

    def build() -> Services:
        vault = SkillManager(vault_dir=tmp_path / "vault")
        return Services(
            store=PgStore(factory), driver=FakeDriver(vault), vault=vault, fake_graph=True
        )

    return build


async def test_full_fake_caesar_run_on_postgres(fake_services):
    services = fake_services()
    async for client in open_client(make_app(services)):
        assert (await client.get("/api/health")).json()["db"] is True
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": CAESAR_Q})
        run_id = sent.json()["run"]["id"]
        done = await wait_for_status(client, run_id, "done")
        assert done["summary"] == "1 tool forged, 2 attempts"
        events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
        assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))
        assert events[-1]["event"] == "run.finished"
        detail = (await client.get(f"/api/sessions/{sid}")).json()
        assert detail["session"]["name"] == "Caesar cipher"
        assert detail["messages"][1]["chips"] == [
            {"kind": "forged", "text": "Forged caesar_cipher"}
        ]
        listed = (await client.get("/api/sessions")).json()
        assert listed[0]["runs"][0]["mark"] == "forged"


async def test_fake_restart_mid_pause_then_resume(fake_services):
    first = fake_services()
    async for client in open_client(make_app(first)):
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": PYTHON_Q})
        run_id = sent.json()["run"]["id"]
        await wait_for_status(client, run_id, "waiting")

    second = fake_services()  # a new process: new store object, new driver, same database
    async for client in open_client(make_app(second)):
        paused = await wait_for_status(client, run_id, "waiting")
        assert paused["pending"]["kind"] == "confirm_exec"
        resumed = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
        assert resumed.status_code == 202
        done = await wait_for_status(client, run_id, "done")
        assert done["summary"] == "Built-in, approved"
        events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
        assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))


async def test_real_graph_restart_mid_pause_then_resume(factory, migrated_url, tmp_path: Path):
    """The real graph on AsyncPostgresSaver: pause, new app instance, approve."""
    with chunks.scenario_env("exec_pause") as env:

        async def services_with_new_saver() -> Services:
            saver = await open_postgres_saver(migrated_url)
            return Services(
                store=PgStore(factory),
                driver=GraphDriver(build_app(saver)),
                vault=env["vault"],
                aclose=lambda: close_postgres_saver(saver),
            )

        first = await services_with_new_saver()
        async for client in open_client(make_app(first)):
            sid = (await client.post("/api/sessions")).json()["id"]
            sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": PYTHON_Q})
            run_id = sent.json()["run"]["id"]
            await wait_for_status(client, run_id, "waiting")

        second = await services_with_new_saver()
        async for client in open_client(make_app(second)):
            await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
            done = await wait_for_status(client, run_id, "done", "failed")
            assert done["status"] == "done", done
            assert done["summary"] == "Built-in, approved"
            events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
            result = next(e for e in events if e["event"] == "call.result")
            assert "5050" in result["data"]["data"]["repr"]
