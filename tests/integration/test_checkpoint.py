"""Interrupts survive a saver/pool restart (spec 01 §4, §8)."""

from __future__ import annotations

from typing import TypedDict

import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from talos.agents import hitl as hitl_mod
from talos.agents.hitl import hitl_check_node
from talos.graph import build_app
from talos.persistence.checkpoint import close_postgres_saver, open_postgres_saver
from talos.state import TalosState

pytestmark = pytest.mark.integration


class _S(TypedDict, total=False):
    answer: str
    big: int


def _ask(state: _S) -> dict:
    value = interrupt({"type": "confirm_exec", "preview": "print(1)"})
    return {"answer": value, "big": 2**100}


def _fixture_graph(saver):
    g: StateGraph = StateGraph(_S)
    g.add_node("ask", _ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=saver)


async def test_interrupt_survives_a_restart(factory, migrated_url):
    config = {"configurable": {"thread_id": "survive-1"}}

    first = await open_postgres_saver(migrated_url)
    try:
        paused = await _fixture_graph(first).ainvoke({}, config)
        assert paused["__interrupt__"][0].value["preview"] == "print(1)"
    finally:
        await close_postgres_saver(first)

    second = await open_postgres_saver(migrated_url)
    try:
        app = _fixture_graph(second)
        final = await app.ainvoke(Command(resume="approved"), config)
        assert final == {"answer": "approved", "big": 2**100}
        # 2**100 is beyond msgpack: stored through the pickle fallback.
        assert (await app.aget_state(config)).values["big"] == 2**100
    finally:
        await close_postgres_saver(second)


async def test_hitl_interrupts_and_resumes_with_postgres(
    factory, migrated_url, monkeypatch, tmp_path
):
    """tests/test_hitl.py::test_hitl_interrupts_and_resumes, on the Postgres saver."""
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    config = {"configurable": {"thread_id": "hitl-pg"}}

    g: StateGraph = StateGraph(TalosState)
    g.add_node("hitl", hitl_check_node)
    g.add_edge(START, "hitl")
    g.add_edge("hitl", END)

    saver = await open_postgres_saver(migrated_url)
    try:
        app = g.compile(checkpointer=saver)
        initial = {
            "messages": [HumanMessage(content="forge a weather tool")],
            "forged_tool": {"name": "weather", "needs_env_vars": ["FAKE_API_KEY"]},
        }
        state = await app.ainvoke(initial, config)
        payload = state["__interrupt__"][0].value
        assert payload["env_var"] == "FAKE_API_KEY"
        assert payload["tool_name"] == "weather"

        final = await app.ainvoke(Command(resume="user-supplied-key"), config)
        assert "__interrupt__" not in final
        assert "FAKE_API_KEY" in (final.get("available_integrations") or {})
        assert (tmp_path / ".env").read_text() == "FAKE_API_KEY=user-supplied-key\n"
    finally:
        await close_postgres_saver(saver)


async def test_build_app_accepts_the_postgres_saver(factory, migrated_url):
    saver = await open_postgres_saver(migrated_url)
    try:
        assert build_app(saver).checkpointer is saver
    finally:
        await close_postgres_saver(saver)


async def test_close_postgres_saver_closes_the_pool(factory, migrated_url):
    saver = await open_postgres_saver(migrated_url)
    await close_postgres_saver(saver)
    assert saver.conn.closed
