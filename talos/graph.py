"""LangGraph StateGraph wiring for Talos.

Phase 1: every node is a stub. No LLM calls. The point is to lock in the
*topology* — nodes, edges, and routing — before any real logic lands.

LangGraph concepts in 60 seconds (PydanticAI comparison):

1. NODE = a Python function `(state) -> partial_state_dict`.
   PydanticAI analogue: a single `Agent` or a tool function. The difference:
   nodes don't "return" results to a caller; they mutate shared state.

2. EDGE = "after node A finishes, run node B." Static topology, no logic.
   PydanticAI analogue: chaining `await agent_a.run(...); await agent_b.run(...)`.

3. CONDITIONAL EDGE = a router function `(state) -> str` whose return value
   keys into a dict mapping keys → next nodes.
   PydanticAI analogue: an `if/elif` inside an agent. Here it's externalised
   so the routing decision shows up in traces (LangSmith) as data, not code.

4. add_node / add_edge / add_conditional_edges build a `StateGraph`.
   `.compile()` produces an `app` you can `.invoke(state)` or `.stream(state)`.
   PydanticAI analogue: `Agent(...)` is already runnable; LangGraph splits
   "define" from "compile" so the same graph can be invoked many ways.

5. START / END are sentinel node names. START → first node, last node → END.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from talos.state import TalosState


# -----------------------------------------------------------------------------
# Stub nodes. Each one only records that it ran (in `visited`) and writes the
# minimum state needed for routing to behave deterministically.
# -----------------------------------------------------------------------------
# A "stub" returns a *partial* dict — only the keys it touches.
# LangGraph merges that partial into the full state.

def _mark_visited(state: TalosState, name: str) -> list[str]:
    """Append `name` to state['visited'] without using a reducer.

    Why no reducer: `visited` is a Phase-1-only debug aid. Using a custom
    reducer (like `add_messages`) would be overkill. Instead each node reads
    the current list and returns a new one — LangGraph's default "replace"
    merge then overwrites the old list with the new one.
    """
    return [*state.get("visited", []), name]


def orchestrate_node(state: TalosState) -> dict:
    return {"visited": _mark_visited(state, "orchestrate")}


def plan_node(state: TalosState) -> dict:
    # Stub: emit a single fake sub-task so downstream routers have something to chew on.
    return {
        "visited": _mark_visited(state, "plan"),
        "plan": {"sub_tasks": [{"id": 1, "needs": "vault_or_forge"}]},
        "current_sub_task": {"id": 1, "needs": "vault_or_forge"},
    }


def search_vault_node(state: TalosState) -> dict:
    # Stub: pretend the vault is empty so we route into the forge path.
    return {"visited": _mark_visited(state, "search_vault"), "skill_matches": []}


def forge_node(state: TalosState) -> dict:
    return {
        "visited": _mark_visited(state, "forge"),
        "forged_tool": {"name": "stub_tool", "code": "# stub", "test_code": "# stub"},
        "retry_count": state.get("retry_count", 0),
    }


def test_node(state: TalosState) -> dict:
    # Stub: always pass.
    return {
        "visited": _mark_visited(state, "test"),
        "test_result": {"passed": True, "stdout": "", "stderr": ""},
    }


def execute_node(state: TalosState) -> dict:
    return {
        "visited": _mark_visited(state, "execute"),
        "execution_result": "stub-result",
    }


def learn_node(state: TalosState) -> dict:
    # In Phase 6 this will register the forged tool in the vault.
    return {"visited": _mark_visited(state, "learn")}


def respond_node(state: TalosState) -> dict:
    return {"visited": _mark_visited(state, "respond")}


# -----------------------------------------------------------------------------
# Routers. Pure functions: read state, return a string key.
# Each key maps (in `add_conditional_edges`) to the next node name.
# -----------------------------------------------------------------------------

def route_sub_task(state: TalosState) -> str:
    """After plan: pick what kind of work the current sub-task needs.

    Phase 1 stub: always go to search_vault, then mark "done" on the second pass
    once a sub_task_result has been recorded by execute.
    """
    if state.get("sub_task_results"):
        return "done"
    needs = (state.get("current_sub_task") or {}).get("needs", "")
    if needs == "primitive":
        return "primitive"
    return "search_vault"


def route_after_search(state: TalosState) -> str:
    """If vault matched, run it; else forge a new tool."""
    return "execute" if state.get("skill_matches") else "forge"


def route_after_test(state: TalosState) -> str:
    """If tests passed, execute; if failed and retries left, retry; else give up."""
    test = state.get("test_result") or {}
    if test.get("passed"):
        return "execute"
    if state.get("retry_count", 0) < 3:
        return "retry_forge"
    return "fail"


def route_after_execute(state: TalosState) -> str:
    """After execute: learn (if a tool was forged), or move to next sub-task / respond.

    Phase 1 stub: always go to learn. Real impl (Phase 6) will inspect
    `state["forged_tool"]` and `state["plan"]["sub_tasks"]` to choose.
    """
    _ = state  # signature must match LangGraph router contract; unused in stub
    return "learn"


# -----------------------------------------------------------------------------
# Build the graph.
# -----------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Construct the StateGraph. Returns the *uncompiled* graph for inspection;
    callers (main, tests) call `.compile()` themselves.
    """
    g: StateGraph = StateGraph(TalosState)

    g.add_node("orchestrate", orchestrate_node)
    g.add_node("plan", plan_node)
    g.add_node("search_vault", search_vault_node)
    g.add_node("forge", forge_node)
    g.add_node("test", test_node)
    g.add_node("execute", execute_node)
    g.add_node("learn", learn_node)
    g.add_node("respond", respond_node)

    # Static edges: unconditional next-node.
    g.add_edge(START, "orchestrate")
    g.add_edge("orchestrate", "plan")
    g.add_edge("forge", "test")
    # Phase 1: after learn, hand control back to execute's post-router.
    # Real flow: learn → plan (so the planner pops the next sub-task).
    # We route learn → respond directly here to avoid an infinite stub loop;
    # the proper learn → plan loop arrives in Phase 6.
    g.add_edge("learn", "respond")
    g.add_edge("respond", END)

    # Conditional edges: router fn + label→node map.
    g.add_conditional_edges(
        "plan",
        route_sub_task,
        {"primitive": "execute", "search_vault": "search_vault", "done": "respond"},
    )
    g.add_conditional_edges(
        "search_vault",
        route_after_search,
        {"execute": "execute", "forge": "forge"},
    )
    g.add_conditional_edges(
        "test",
        route_after_test,
        {"execute": "execute", "retry_forge": "forge", "fail": "respond"},
    )
    g.add_conditional_edges(
        "execute",
        route_after_execute,
        {"learn": "learn", "next_sub_task": "plan", "respond": "respond"},
    )

    return g


# Module-level compiled app, ready to invoke.
# `.compile()` is roughly "freeze the graph, return something you can run."
# In PydanticAI, `Agent(...)` is the equivalent — already callable.
app = build_graph().compile()
