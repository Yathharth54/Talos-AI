"""Phase 9 — HITL tests.

Verifies:
- _persist_env_var creates and updates the .env file
- hitl_check_node is a no-op when no env vars are needed
- hitl_check_node is a no-op when all env vars are already set
- hitl_check_node interrupts when an env var is missing, then resumes
  cleanly with the user-supplied value
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from talos.agents import hitl as hitl_mod
from talos.agents.hitl import hitl_check_node
from talos.state import TalosState


# ---- _persist_env_var -----------------------------------------------------

def test_persist_creates_env_file(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", target)
    monkeypatch.delenv("X_TEST_KEY", raising=False)

    hitl_mod._persist_env_var("X_TEST_KEY", "abc123")

    assert target.read_text() == "X_TEST_KEY=abc123\n"
    import os
    assert os.environ["X_TEST_KEY"] == "abc123"


def test_persist_updates_existing_key(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("OTHER=keep\nX=old\nLAST=keep2\n")
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", target)

    hitl_mod._persist_env_var("X", "new")
    text = target.read_text()
    assert "OTHER=keep" in text
    assert "X=new" in text
    assert "X=old" not in text
    assert "LAST=keep2" in text


def test_persist_appends_new_key(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("OTHER=keep\n")
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", target)

    hitl_mod._persist_env_var("FRESH", "v")
    text = target.read_text()
    assert "OTHER=keep" in text
    assert "FRESH=v" in text


# ---- hitl_check_node (no-graph) -------------------------------------------

def test_hitl_noop_when_no_vars_needed():
    state = {"forged_tool": {"name": "x", "needs_env_vars": []}}
    assert hitl_check_node(state) == {}  # type: ignore[arg-type]


def test_hitl_noop_when_vars_already_set(monkeypatch):
    monkeypatch.setenv("ALREADY_SET", "yes")
    state = {"forged_tool": {"name": "x", "needs_env_vars": ["ALREADY_SET"]}}
    assert hitl_check_node(state) == {}  # type: ignore[arg-type]


# ---- hitl_check_node inside a checkpointed graph (interrupt + resume) ----

def test_hitl_interrupts_and_resumes(monkeypatch, tmp_path):
    """Build a tiny graph with one node — hitl_check — and verify it
    pauses and resumes correctly when an env var is missing."""
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("FAKE_API_KEY", raising=False)

    g: StateGraph = StateGraph(TalosState)
    g.add_node("hitl", hitl_check_node)
    g.add_edge(START, "hitl")
    g.add_edge("hitl", END)
    app = g.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "tA"}}
    initial = {
        "messages": [HumanMessage(content="forge a weather tool")],
        "forged_tool": {"name": "weather", "needs_env_vars": ["FAKE_API_KEY"]},
    }

    # First invoke: should pause at the interrupt.
    state = app.invoke(initial, config=config)
    assert "__interrupt__" in state
    payload = state["__interrupt__"][0].value
    assert payload["env_var"] == "FAKE_API_KEY"
    assert payload["tool_name"] == "weather"

    # Resume with a value → graph completes; .env updated; integrations recorded.
    final = app.invoke(Command(resume="user-supplied-key"), config=config)
    assert "__interrupt__" not in final
    import os
    assert os.environ["FAKE_API_KEY"] == "user-supplied-key"
    assert "FAKE_API_KEY" in (final.get("available_integrations") or {})


def test_hitl_skip_does_not_persist(monkeypatch, tmp_path):
    monkeypatch.setattr(hitl_mod, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("OPTIONAL_KEY", raising=False)

    g: StateGraph = StateGraph(TalosState)
    g.add_node("hitl", hitl_check_node)
    g.add_edge(START, "hitl")
    g.add_edge("hitl", END)
    app = g.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "tB"}}
    initial = {"forged_tool": {"name": "thing", "needs_env_vars": ["OPTIONAL_KEY"]}}

    app.invoke(initial, config=config)
    app.invoke(Command(resume="skip"), config=config)

    import os
    assert "OPTIONAL_KEY" not in os.environ
    # .env file should still not contain the skipped key
    env_path = tmp_path / ".env"
    if env_path.exists():
        assert "OPTIONAL_KEY" not in env_path.read_text()
