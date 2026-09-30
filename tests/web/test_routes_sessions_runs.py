"""Sessions, runs and the SSE stream over HTTP, with the fake graph (spec 02 §4, §5, §11)."""

from __future__ import annotations

import asyncio
import uuid

from tests.web.conftest import parse_sse, wait_for_status

CAESAR_Q = 'Build a Caesar cipher tool. Encrypt "TALOS AGENT" with a shift of 7.'
PYTHON_Q = "Run this Python code and give me the output: print(sum(range(1, 101)))"


async def new_session(client) -> str:
    response = await client.post("/api/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def send(client, session_id: str, text: str) -> dict:
    response = await client.post(f"/api/sessions/{session_id}/messages", json={"text": text})
    assert response.status_code == 202, response.text
    return response.json()


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["db"] is True and body["fake_graph"] is True
    assert isinstance(body["version"], str)


async def test_create_reuses_the_empty_session_and_lists_only_used_ones(client):
    first = await new_session(client)
    assert await new_session(client) == first  # an empty session is reused
    assert (await client.get("/api/sessions")).json() == []

    run = (await send(client, first, CAESAR_Q))["run"]
    await wait_for_status(client, run["id"], "done")
    listed = (await client.get("/api/sessions")).json()
    assert [s["id"] for s in listed] == [first]
    assert listed[0]["name"] == "Caesar cipher"
    assert listed[0]["run_count"] == 1
    assert listed[0]["forged"] == ["caesar_cipher"]
    assert listed[0]["runs"] == [{"n": 1, "query": CAESAR_Q, "mark": "forged"}]
    assert await new_session(client) != first


async def test_session_detail_rename_and_errors(client):
    sid = await new_session(client)
    run = (await send(client, sid, CAESAR_Q))["run"]
    await wait_for_status(client, run["id"], "done")

    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["session"]["name"] == "Caesar cipher"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["chips"] == [{"kind": "forged", "text": "Forged caesar_cipher"}]
    assert detail["runs"][0]["summary"] == "1 tool forged, 2 attempts"
    assert detail["runs"][0]["summary_gold"] is True

    renamed = await client.patch(f"/api/sessions/{sid}", json={"name": "  Ciphers  "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ciphers"
    for bad in ("", "   ", "x" * 81):
        response = await client.patch(f"/api/sessions/{sid}", json={"name": bad})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    missing = str(uuid.uuid4())
    for response in (
        await client.get(f"/api/sessions/{missing}"),
        await client.patch(f"/api/sessions/{missing}", json={"name": "x"}),
        await client.post(f"/api/sessions/{missing}/messages", json={"text": "hi"}),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert (await client.get("/api/sessions/not-a-uuid")).status_code == 422


async def test_message_text_is_trimmed_and_bounded(client):
    sid = await new_session(client)
    for bad in ("", "    ", "x" * 4001):
        response = await client.post(f"/api/sessions/{sid}/messages", json={"text": bad})
        assert response.status_code == 422
    body = await send(client, sid, "   What can you do?  ")
    assert body["message"]["html"] == "What can you do?"
    assert body["run"]["query"] == "What can you do?"
    assert body["run"]["status"] == "running"


async def test_one_run_at_a_time_anywhere(client):
    a = await new_session(client)
    run = (await send(client, a, PYTHON_Q))["run"]
    await wait_for_status(client, run["id"], "waiting")
    b_session = await client.post("/api/sessions")
    b = b_session.json()["id"]
    response = await client.post(f"/api/sessions/{b}/messages", json={"text": "hi"})
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "run_active",
            "message": "A run is already going. Stop it or wait for it to finish.",
            "run_id": run["id"],
            "session_id": a,
        }
    }


async def test_pending_approval_is_browser_safe_and_resume_approve_finishes(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    paused = await wait_for_status(client, run_id, "waiting")
    assert paused["pending"] == {
        "kind": "confirm_exec",
        "payload": {"tool": "python_exec", "preview": "print(sum(range(1, 101)))"},
    }
    response = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
    assert response.status_code == 202
    done = await wait_for_status(client, run_id, "done")
    assert done["pending"] is None
    assert done["summary"] == "Built-in, approved"


async def test_resume_errors(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")

    wrong = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "save", "value": "k"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "bad_decision"
    unknown = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "maybe"})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "invalid_request"

    await client.post(f"/api/runs/{run_id}/resume", json={"decision": "decline"})
    declined = await wait_for_status(client, run_id, "declined")
    assert declined["summary"] == "Declined, nothing ran"
    again = await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_waiting"

    missing = str(uuid.uuid4())
    for response in (
        await client.get(f"/api/runs/{missing}"),
        await client.get(f"/api/runs/{missing}/events"),
        await client.post(f"/api/runs/{missing}/resume", json={"decision": "approve"}),
        await client.post(f"/api/runs/{missing}/stop"),
    ):
        assert response.status_code == 404


async def test_stop_during_a_pause_then_stop_again_is_a_noop(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")
    assert (await client.post(f"/api/runs/{run_id}/stop")).status_code == 202
    stopped = await wait_for_status(client, run_id, "stopped")
    assert stopped["summary"] == "Stopped"
    assert (await client.post(f"/api/runs/{run_id}/stop")).status_code == 202
    events = parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
    assert events[-1]["event"] == "run.finished"
    assert events[-1]["data"]["data"]["status"] == "stopped"
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["messages"][-1]["note"] == "Stopped. Ask again whenever you're ready."


async def test_sse_sends_the_whole_run_then_closes(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, CAESAR_Q))["run"]["id"]
    await wait_for_status(client, run_id, "done")
    response = await client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))
    assert [e["event"] for e in events[:2]] == ["run.started", "log.cmd"]
    assert events[-1]["event"] == "run.finished"
    envelope = events[0]["data"]
    assert set(envelope) == {"run_id", "seq", "ts", "type", "data"}
    assert envelope["run_id"] == run_id and envelope["type"] == "run.started"
    assert envelope["data"] == {"session_id": sid, "query": CAESAR_Q, "n": 1}
    assert all(e["event"] == e["data"]["type"] for e in events)


async def test_sse_resumes_after_a_dropped_connection(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, CAESAR_Q))["run"]["id"]
    await wait_for_status(client, run_id, "done")
    total = len(parse_sse((await client.get(f"/api/runs/{run_id}/events")).text))
    resumed = parse_sse(
        (await client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "10"})).text
    )
    assert [int(e["id"]) for e in resumed] == list(range(11, total + 1))
    after = parse_sse((await client.get(f"/api/runs/{run_id}/events?after=20")).text)
    assert int(after[0]["id"]) == 21


async def test_sse_backlog_then_live_through_a_pause(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")

    stream = asyncio.create_task(client.get(f"/api/runs/{run_id}/events"))
    await asyncio.sleep(0.05)
    assert not stream.done()  # open while the run waits
    await client.post(f"/api/runs/{run_id}/resume", json={"decision": "approve"})
    events = parse_sse((await asyncio.wait_for(stream, 5)).text)

    kinds = [e["event"] for e in events]
    assert kinds.index("interrupt") < kinds.index("interrupt.resolved")
    assert kinds[-1] == "run.finished"
    assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))


def test_heartbeat_is_a_keep_alive_comment():
    from sse_starlette.sse import ServerSentEvent

    from talos.web.routes.runs import HEARTBEAT_S

    assert HEARTBEAT_S == 15
    assert ServerSentEvent(comment="keep-alive", sep="\n").encode() == b": keep-alive\n\n"


async def test_get_run_pending_is_built_from_the_interrupt_not_the_row(client, services):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")
    row = services.store.runs[uuid.UUID(run_id)]
    row.pending_interrupt = {
        "type": "confirm_exec",
        "tool": "python_exec",
        "preview": "p",
        "args": ["SECRET_ARG"],
        "kwargs": {"code": "SECRET_KWARG"},
    }
    response = await client.get(f"/api/runs/{run_id}")
    assert response.json()["pending"] == {
        "kind": "confirm_exec",
        "payload": {"tool": "python_exec", "preview": "p"},
    }
    assert "SECRET" not in response.text


async def test_invalid_resume_bodies_are_422_and_never_echo_the_value(client):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")
    secret = "sk-" + "z9y8x7w6v5" * 5
    for body in (
        {"decision": "save", "value": secret},  # wrong decision for an approval
        {"decision": "maybe", "value": secret},
        {"decision": "save", "value": secret * 200},
    ):
        response = await client.post(f"/api/runs/{run_id}/resume", json=body)
        assert response.status_code == 422
        assert secret not in response.text


async def test_sse_closes_the_subscribe_generator_on_disconnect(client, app):
    sid = await new_session(client)
    run_id = (await send(client, sid, PYTHON_Q))["run"]["id"]
    await wait_for_status(client, run_id, "waiting")
    manager = app.state.manager
    closed = asyncio.Event()
    real = manager.subscribe

    async def spy(rid, after=0):
        try:
            async for envelope in real(rid, after):
                yield envelope
        finally:
            closed.set()

    held = []  # keep each generator alive so only an explicit aclose() can finish it

    def holding(rid, after=0):
        held.append(spy(rid, after))
        return held[-1]

    manager.subscribe = holding
    stream = asyncio.create_task(client.get(f"/api/runs/{run_id}/events"))
    await asyncio.sleep(0.1)
    assert not stream.done()
    stream.cancel()  # the client goes away
    await asyncio.gather(stream, return_exceptions=True)
    await asyncio.wait_for(closed.wait(), 2)
