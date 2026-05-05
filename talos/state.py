"""TalosState — the shared dict that flows through every node in the graph.

LangGraph vs PydanticAI:
- PydanticAI:  you pass `deps` into `agent.run()`; each agent has its own RunContext.
- LangGraph:   there is ONE state object (this TypedDict). Every node reads from it
               and returns a *partial* dict; LangGraph merges the partial back into
               the full state. No deps injection — everything is shared.

The `Annotated[..., reducer]` pattern below is LangGraph's way to say
"this field has a custom merge strategy." Without a reducer, the default merge
is "replace": whatever the node returns overwrites the old value.
With `add_messages`, returning a new message *appends* it to the existing list
instead of replacing — closest analogue in PydanticAI is the message history
that `Agent.run()` accumulates internally, except here it's exposed as state.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class TalosState(TypedDict, total=False):
    # --- Conversation ---
    # `add_messages` is a "reducer" — when a node returns {"messages": [new_msg]},
    # LangGraph appends rather than overwrites. Equivalent to PydanticAI's internal
    # message history, but here it's a first-class state field.
    messages: Annotated[list[BaseMessage], add_messages]

    # --- Planning ---
    plan: dict | None                    # full structured plan from Planner
    current_sub_task: dict | None        # sub-task currently being processed
    sub_task_results: list[dict]         # results of completed sub-tasks

    # --- Skill search ---
    skill_matches: list[dict]            # vault hits for current sub-task

    # --- Forging ---
    forged_tool: dict | None             # {name, code, test_code, description}
    test_result: dict | None             # {passed, stdout, stderr} — unit tests (mocked)
    smoke_result: dict | None            # {passed, error, output, skipped} — real-call gate
    retry_count: int                     # forge→test retry counter (cap at FORGE_MAX_RETRIES)

    # --- Execution ---
    execution_result: str | None         # output from running a tool

    # --- Routing flags ---
    # Conditional edges read these to decide where to go next.
    # In PydanticAI you'd write `if needs_forge: ...` inside an agent.
    # Here, `needs_forge` is data; a router function reads it externally.
    needs_forge: bool
    needs_human_input: bool
    human_input_request: dict | None

    # --- Discovered API integrations ---
    available_integrations: dict         # name → env var
