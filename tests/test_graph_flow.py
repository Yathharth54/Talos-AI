"""Phase 1 graph-shape tests. No LLM calls — pure topology checks.

We only verify here that:
  - the graph compiles
  - it runs to completion on dummy input (no infinite loops, no missing edges)
  - the stub nodes are visited in the expected order
  - state merging works (final state contains accumulated `visited` list)
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from talos.graph import app, build_graph


def test_graph_compiles():
    """`.compile()` must succeed — catches typos in node/edge names."""
    g = build_graph()
    compiled = g.compile()
    assert compiled is not None


def test_graph_runs_to_completion():
    """Invoke should terminate (no infinite loop) and return final state."""
    final = app.invoke({"messages": [HumanMessage(content="hello")]})
    assert isinstance(final, dict)
    assert "visited" in final


def test_expected_node_traversal():
    """Phase-1 stub routing should hit this exact sequence:
        orchestrate → plan → search_vault → forge → test → execute → learn → respond
    If a route or edge is mis-wired, this test breaks loudly.
    """
    final = app.invoke({"messages": [HumanMessage(content="hello")]})
    assert final["visited"] == [
        "orchestrate",
        "plan",
        "search_vault",
        "forge",
        "test",
        "execute",
        "learn",
        "respond",
    ]


def test_state_merge_for_messages():
    """The `add_messages` reducer should append, not replace."""
    final = app.invoke({"messages": [HumanMessage(content="first")]})
    # We sent one message; no node added more in Phase 1.
    assert len(final["messages"]) == 1
    assert final["messages"][0].content == "first"


def test_partial_state_returns_merge_correctly():
    """Each stub returns a partial dict; final state should contain the union."""
    final = app.invoke({"messages": [HumanMessage(content="hello")]})
    # Fields written by different nodes all need to be present in the final state.
    assert final.get("plan") is not None
    assert final.get("forged_tool") is not None
    assert final.get("test_result") == {"passed": True, "stdout": "", "stderr": ""}
    assert final.get("execution_result") == "stub-result"
