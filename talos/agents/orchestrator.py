"""Orchestrator — the conversation/coordination layer.

Three responsibilities, split across two nodes + two routers:
- `orchestrator_in_node`:   pure Python; resets per-query forge state.
- `orchestrator_out_node`:  one LLM call; synthesises final response.
- `route_dispatch`:         router; reads current sub-task's `needs` label.
- `route_advance`:          router; pops next sub-task or finishes.

Note on iteration: the graph is static. We DON'T add new edges per plan.
The advance router updates `current_sub_task` in place and returns either
"continue" (loop back to dispatch) or "respond" (jump to out).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from talos.agents._history import format_recent_history
from talos.config import settings
from talos.prompts.orchestrator import ORCHESTRATOR_RESPONSE_PROMPT
from talos.state import TalosState


def _make_llm() -> Any:
    """Plain ChatOpenAI client (no structured output) for response synthesis."""
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.3,
    )


# ---- nodes -----------------------------------------------------------------

def orchestrator_in_node(state: TalosState) -> dict:
    """Reset per-query state. Runs once at the start of each invocation.

    Wipes any leftover forge bookkeeping from a previous run. Conversation
    history (`messages`) is preserved by the `add_messages` reducer.
    """
    return {
        "plan": None,
        "current_sub_task": None,
        "sub_task_results": [],
        "skill_matches": [],
        "forged_tool": None,
        "test_result": None,
        "smoke_result": None,
        "retry_count": 0,
        "execution_result": None,
        "needs_forge": False,
        "needs_human_input": False,
        "human_input_request": None,
    }


def orchestrator_out_node(state: TalosState) -> dict:
    """Synthesise final response from sub-task results.

    Adds an AIMessage to the conversation. The REPL reads this to display.
    """
    user_query = _last_user_text(state)
    results = state.get("sub_task_results") or []
    plan_full = state.get("plan") or {}
    plan = plan_full.get("sub_tasks", [])
    history = format_recent_history(state.get("messages") or [])
    history_block = history if history else "(this is the first turn)"

    if plan_full.get("verdict") == "infeasible":
        # Refusal path — the Planner determined the query can't be answered.
        # Surface the reason verbatim plus a short framing line; no fabrication.
        category = plan_full.get("verdict_category") or "infeasible"
        reason = plan_full.get("verdict_reason") or "no further detail provided"
        body = (
            f"Recent conversation:\n{history_block}\n\n"
            f"User asked: {user_query}\n\n"
            f"VERDICT: This query is {category}. Reason: {reason}\n\n"
            "Reply to the user explaining why this can't be done, plainly and "
            "without trying to substitute a different problem. If the category "
            "is 'underspecified', ask the user the specific clarifying question "
            "needed to proceed."
        )
    elif not plan and not results:
        # Conversational — no work was done; let the LLM respond directly.
        body = (
            f"Recent conversation:\n{history_block}\n\n"
            f"User said: {user_query}\n\n"
            "No sub-tasks ran (this looked conversational). Reply directly."
        )
    else:
        body = (
            f"Recent conversation:\n{history_block}\n\n"
            f"User asked: {user_query}\n\n"
            f"Sub-tasks executed ({len(results)} results):\n"
            f"{_format_results(plan, results)}\n\n"
            "Synthesise a final response. If the sub-task results don't actually "
            "contain the answer, say so plainly — do not fabricate values."
        )

    messages = [
        SystemMessage(content=ORCHESTRATOR_RESPONSE_PROMPT),
        HumanMessage(content=body),
    ]
    response = _make_llm().invoke(messages)
    text = getattr(response, "content", str(response))
    return {"messages": [AIMessage(content=text)]}


# ---- routers ---------------------------------------------------------------

def route_after_planner(state: TalosState) -> str:
    """Three terminals after planning:
      - 'respond' for conversational queries (empty plan, feasible verdict).
      - 'respond' for infeasible queries — orchestrator_out formats a refusal.
      - 'dispatch' otherwise.
    Both terminals route through orchestrator_out; it inspects the plan to
    decide whether to synthesise from sub-task results or emit a refusal."""
    plan = state.get("plan") or {}
    if plan.get("verdict") == "infeasible":
        return "respond"
    sub_tasks = plan.get("sub_tasks") or []
    if not sub_tasks:
        return "respond"
    return "dispatch"


def route_dispatch(state: TalosState) -> str:
    """Pick the right execution path for the current sub-task.

    Reads: current_sub_task["needs"] in {"primitive", "vault", "forge"}.
    """
    sub_task = state.get("current_sub_task") or {}
    needs = sub_task.get("needs")
    if needs == "primitive":
        return "primitive"
    if needs == "vault":
        return "vault"
    if needs == "forge":
        return "forge"
    # Malformed sub-task — record an error and skip via the executor.
    return "primitive"  # executor will record dispatch failure


def route_advance(state: TalosState) -> str:
    """After execute (and optionally learn): more sub-tasks, or respond?

    This router is paired with the `advance_node` state update — together
    they advance `current_sub_task` to the next pending sub-task.
    """
    plan = (state.get("plan") or {}).get("sub_tasks") or []
    results = state.get("sub_task_results") or []
    if len(results) >= len(plan):
        return "respond"
    return "continue"


def route_after_forge_test(state: TalosState) -> str:
    """Inside the forge branch: only register if BOTH unit tests AND the
    smoke gate passed. A unit-test fail or a real-call smoke fail both
    mean the tool isn't ready for the vault."""
    test = state.get("test_result") or {}
    smoke = state.get("smoke_result") or {"passed": True}  # absent = no contract = pass
    if test.get("passed") and smoke.get("passed"):
        return "learn"
    return "advance"


def advance_node(state: TalosState) -> dict:
    """Advance `current_sub_task` to the next not-yet-executed sub-task and
    clear per-sub-task forge state so the next forge starts clean.
    """
    plan = (state.get("plan") or {}).get("sub_tasks") or []
    results = state.get("sub_task_results") or []
    next_idx = len(results)
    next_task = plan[next_idx] if next_idx < len(plan) else None
    return {
        "current_sub_task": next_task,
        "forged_tool": None,
        "test_result": None,
        "smoke_result": None,
        "retry_count": 0,
        "execution_result": None,
    }


# ---- helpers ---------------------------------------------------------------

def _last_user_text(state: TalosState) -> str:
    for msg in reversed(state.get("messages", []) or []):
        if msg.__class__.__name__ == "HumanMessage":
            return str(getattr(msg, "content", "") or "")
    return ""


def _format_results(plan: list[dict], results: list[dict]) -> str:
    by_id = {r.get("sub_task_id"): r for r in results}
    lines: list[str] = []
    for st in plan:
        sid = st.get("id")
        r = by_id.get(sid)
        if r is None:
            lines.append(f"  [{sid}] {st.get('action', '')} — (not run)")
            continue
        status = "OK" if r.get("ok") else "FAIL"
        out = r.get("output") if r.get("ok") else r.get("error")
        snippet = repr(out)
        if len(snippet) > 800:
            snippet = snippet[:800] + "...(truncated)"
        lines.append(f"  [{sid}] {st.get('action', '')} — {status}: {snippet}")
    return "\n".join(lines)
