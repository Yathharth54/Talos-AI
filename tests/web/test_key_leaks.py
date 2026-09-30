"""A key sent to /resume never shows up in logs, run_events or responses (spec 02 §10, §11)."""

from __future__ import annotations

import json
import logging

import pytest

from tests.web.conftest import make_app, open_client, parse_sse, wait_for_status
from tests.web.stubs import ScriptDriver

KEY = "owm-" + "7f3c9a1b2d4e6f80"


class LeakyDriver(ScriptDriver):
    """A driver that logs its resume value, as careless graph code might."""

    async def run(self, state, *, query, thread_id, resume):
        if resume is not None:
            logging.getLogger("talos.agents.hitl").warning("resumed with %s", resume.value)
        async for item in super().run(state, query=query, thread_id=thread_id, resume=resume):
            yield item


@pytest.fixture
def leaky_services(services):
    services.driver = LeakyDriver()
    return services


async def test_a_saved_key_never_leaks(leaky_services, caplog):
    caplog.set_level(logging.DEBUG)
    app = make_app(leaky_services)
    async for client in open_client(app):
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": "key"})
        run_id = sent.json()["run"]["id"]
        await wait_for_status(client, run_id, "waiting")

        wrong = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "approve", "value": KEY}
        )
        too_long = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "save", "value": KEY * 400}
        )
        ok = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "save", "value": KEY}
        )
        assert (wrong.status_code, too_long.status_code, ok.status_code) == (422, 422, 202)
        await wait_for_status(client, run_id, "done")

        bodies = [wrong.text, too_long.text, ok.text]
        bodies.append((await client.get(f"/api/runs/{run_id}")).text)
        bodies.append((await client.get(f"/api/sessions/{sid}")).text)
        stream = (await client.get(f"/api/runs/{run_id}/events")).text
        bodies.append(stream)
        for body in bodies:
            assert KEY not in body

        resolved = next(e for e in parse_sse(stream) if e["event"] == "interrupt.resolved")
        assert resolved["data"]["data"] == {"kind": "missing_api_key", "decision": "save"}

    stored = leaky_services.store.events[next(iter(leaky_services.store.runs))]
    assert KEY not in json.dumps([e.data for e in stored])
    assert KEY not in caplog.text
    assert "resumed with [redacted]" in caplog.text


INJECTION = "abc\nTALOS_AUTO_APPROVE_EXEC=true"


async def test_a_key_with_a_newline_is_refused_without_echoing_it(leaky_services, dotenv, caplog):
    """A newline in a key would add a line to .env (spec 02 §10)."""
    caplog.set_level(logging.DEBUG)
    async for client in open_client(make_app(leaky_services)):
        sid = (await client.post("/api/sessions")).json()["id"]
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": "key"})
        run_id = sent.json()["run"]["id"]
        await wait_for_status(client, run_id, "waiting")
        refused = await client.post(
            f"/api/runs/{run_id}/resume", json={"decision": "save", "value": INJECTION}
        )
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "bad_decision"
        assert "abc" not in refused.text and "TALOS_AUTO_APPROVE_EXEC" not in refused.text
        assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "waiting"
    assert not dotenv.exists()
    assert leaky_services.driver.resumes == []
    assert "TALOS_AUTO_APPROVE_EXEC=true" not in caplog.text


@pytest.mark.parametrize(
    "value", ["abc def", "abc\tdef", "abc\rdef", "abc\x00def", "abc\x1bdef", "abc def"]
)
def test_keys_with_whitespace_or_control_characters_are_bad_decisions(value):
    from talos.web.runner import BadDecision, _resume_for

    with pytest.raises(BadDecision) as caught:
        _resume_for({"type": "missing_api_key"}, "save", value)
    assert "abc" not in str(caught.value) and "def" not in str(caught.value)


def test_a_padded_key_is_stripped_and_accepted():
    from talos.web.runner import _resume_for

    assert _resume_for({"type": "missing_api_key"}, "save", "  sk-123\n").value == "sk-123"
