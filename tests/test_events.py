"""emit() is a no-op without a stream and a custom chunk with one."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from talos.events import emit


class _S(TypedDict, total=False):
    x: int


def _graph():
    def node(state: _S) -> dict:
        emit("call.result", repr="3", type="int", small=True)
        return {"x": 1}

    g: StateGraph = StateGraph(_S)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile()


def test_emit_outside_a_graph_is_a_noop():
    assert emit("forge.smoke", call=None, result=None, passed=False) is None


def test_emit_under_invoke_is_a_noop():
    assert _graph().invoke({"x": 0}) == {"x": 1}


def test_emit_under_updates_only_stream_sends_nothing():
    chunks = list(_graph().stream({"x": 0}, stream_mode="updates"))
    assert chunks == [{"n": {"x": 1}}]


def test_emit_under_custom_stream_sends_type_and_data():
    chunks = list(_graph().stream({"x": 0}, stream_mode=["custom", "updates"]))
    assert (
        "custom",
        {"type": "call.result", "data": {"repr": "3", "type": "int", "small": True}},
    ) in chunks


async def test_emit_reaches_async_stream_from_a_sync_node():
    chunks = [c async for c in _graph().astream({"x": 0}, stream_mode="custom")]
    assert chunks == [{"type": "call.result", "data": {"repr": "3", "type": "int", "small": True}}]
