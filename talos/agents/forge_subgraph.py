"""Forge sub-graph — encapsulates the forge → test → retry loop.

LangGraph concept introduced: sub-graphs.
- A `StateGraph` can be compiled and used as a single node inside another
  `StateGraph`. The inner graph has its own state schema; the outer graph
  invokes it like any other callable node.
- This is LangGraph's modularity primitive. PydanticAI analogue: an Agent
  delegating to another Agent, except here the "delegation" is wired
  declaratively as graph topology rather than via a function call.

Why a sub-graph here:
- The forge → test → retry interaction is dense; a self-contained inner
  graph keeps it testable in isolation (we can drive it with a fake LLM
  and not touch the outer Talos graph at all).
- LangSmith traces will show this as one collapsible block — readable.

State sharing:
- The sub-graph reuses TalosState fields directly (forged_tool,
  test_result, retry_count, current_sub_task). No separate inner state.
  We could split it into its own TypedDict later if the sub-graph
  evolves to need private fields.

Routing:
- forge → test (always)
- test → END if passed
- test → forge if failed and retries left
- test → END if failed and retries exhausted
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from talos.agents.forger import forger_node
from talos.agents.tester import tester_node
from talos.config import settings
from talos.state import TalosState


def _route_after_test(state: TalosState) -> str:
    test = state.get("test_result") or {}
    if test.get("passed"):
        return "done"
    if state.get("retry_count", 0) < settings.FORGE_MAX_RETRIES:
        return "retry"
    return "done"  # exhausted retries — exit loop with passed=False


def build_forge_subgraph() -> StateGraph:
    g: StateGraph = StateGraph(TalosState)
    g.add_node("forge", forger_node)
    g.add_node("test", tester_node)
    g.add_edge(START, "forge")
    g.add_edge("forge", "test")
    g.add_conditional_edges(
        "test",
        _route_after_test,
        {"retry": "forge", "done": END},
    )
    return g


# Compile once at import; expose as `forge_app`.
forge_app = build_forge_subgraph().compile()
