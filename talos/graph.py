"""Talos's main StateGraph — Phase 7 production wiring.

Topology:

    START
      │
      ▼
    orchestrator_in   (reset per-query state)
      │
      ▼
    planner           (decompose → sub_tasks)
      │
      ├── (empty plan) ─────────────────────────────────┐
      ▼                                                 │
    dispatch_router                                     │
      │                                                 │
      ├──> primitive ────────────────┐                  │
      │                              │                  │
      ├──> vault ────────────────────┤                  │
      │                              │                  │
      └──> forge_subgraph            │                  │
              │                      │                  │
              ▼                      │                  │
            forge_decision           │                  │
              │ (passed)             │                  │
              ▼                      │                  │
            learn ───────────────────┤                  │
              │                                          │
              ▼                                          │
            executor ──────────────────                  │
              │                                          │
              ▼                                          │
            advance_router                               │
              │                                          │
              ├── (more sub-tasks) ─→ advance_node ─→ dispatch_router
              │                                          │
              └── (done) ─────────────────────────────────┤
                                                          ▼
                                                  orchestrator_out
                                                          │
                                                          ▼
                                                         END

LangGraph note: the `forge_app` from agents/forge_subgraph.py is a compiled
StateGraph. We add it directly with `add_node("forge_subgraph", forge_app)`
— LangGraph treats compiled graphs as first-class node citizens.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from talos.agents.executor import executor_node
from talos.agents.forge_subgraph import forge_app
from talos.agents.hitl import hitl_check_node
from talos.agents.learner import learn_node
from talos.agents.orchestrator import (
    advance_node,
    orchestrator_in_node,
    orchestrator_out_node,
    route_advance,
    route_after_forge_test,
    route_after_planner,
    route_dispatch,
)
from talos.agents.planner import planner_node
from talos.state import TalosState


def build_graph() -> StateGraph:
    g: StateGraph = StateGraph(TalosState)

    # Nodes
    g.add_node("orchestrator_in", orchestrator_in_node)
    g.add_node("planner", planner_node)
    g.add_node("forge_subgraph", forge_app)  # compiled sub-graph plugged in as a node
    g.add_node("hitl_check", hitl_check_node)
    g.add_node("learn", learn_node)
    g.add_node("executor", executor_node)
    g.add_node("advance", advance_node)
    g.add_node("orchestrator_out", orchestrator_out_node)

    # Static edges
    g.add_edge(START, "orchestrator_in")
    g.add_edge("orchestrator_in", "planner")
    g.add_edge("hitl_check", "learn")
    g.add_edge("learn", "executor")
    g.add_edge("orchestrator_out", END)

    # Conditional edges
    # After planner: empty plan → respond; otherwise → dispatch.
    g.add_conditional_edges(
        "planner",
        route_after_planner,
        {"respond": "orchestrator_out", "dispatch": "_dispatch"},
    )

    # We need a synthetic "dispatch" node to host the dispatch router.
    # Cleanest way is a no-op node whose only job is to be the source of the
    # conditional edge. (LangGraph requires routers to be attached to nodes.)
    g.add_node("_dispatch", lambda state: {})
    g.add_conditional_edges(
        "_dispatch",
        route_dispatch,
        {"primitive": "executor", "vault": "executor", "forge": "forge_subgraph"},
    )

    # Forge sub-graph terminates →
    #   success → hitl_check (asks for missing env vars, may pause) → learn → executor
    #   failure → executor (records clean failure since vault has no entry)
    g.add_conditional_edges(
        "forge_subgraph",
        route_after_forge_test,
        {"learn": "hitl_check", "advance": "executor"},
    )

    # After executor, decide: more sub-tasks or respond.
    g.add_conditional_edges(
        "executor",
        route_advance,
        {"continue": "advance", "respond": "orchestrator_out"},
    )

    # advance loops back to dispatch.
    g.add_conditional_edges(
        "advance",
        lambda s: "dispatch",  # always re-dispatch with the new current_sub_task
        {"dispatch": "_dispatch"},
    )

    return g


# Compiled app with an in-memory checkpointer.
#
# LangGraph concept: a checkpointer persists state per `thread_id`. With
# this in place, callers `invoke({...new input...}, config={"configurable":
# {"thread_id": "X"}})` and LangGraph automatically restores the prior
# state for thread X before applying the new input. Conversation history
# accumulates across turns via the `add_messages` reducer — no manual
# history-passing needed in main.py anymore.
#
# (PydanticAI analogue: passing `message_history=[...]` into Agent.run.
#  Same idea — here it's automatic per thread.)
#
# MemorySaver is in-process only. Swap to SqliteSaver / PostgresSaver later
# for cross-process persistence (Phase 9 may want this for HITL resume).
checkpointer = MemorySaver()
app = build_graph().compile(checkpointer=checkpointer)
