"""Executor — runs the right thing for the current sub-task.

Three dispatch paths (chosen by the Planner-assigned `needs` label):
- primitive  → call one of talos.primitives.* directly by name
- vault      → SkillManager.load(name)(...)
- forge      → after Learn registers it, vault.load(forged_tool['name'])(...)

Inside this node we do TWO things:
1. Resolve concrete args via a small LLM call (ArgResolver). The Planner
   only describes what the sub-task wants in natural language; we need
   real Python args.
2. Dispatch to the right callable.

LangChain note: a node is allowed to make multiple LLM calls. There's no
"one LLM call per node" rule. Each call shows up as its own span in
LangSmith — useful here to see arg-resolver vs the actual tool execution
side by side.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from talos.agents._history import format_recent_history
from talos.config import settings
from talos.primitives.file_ops import file_read, file_write
from talos.primitives.python_exec import python_exec
from talos.primitives.shell_exec import shell_exec
from talos.primitives.web_read import web_read
from talos.primitives.web_search import web_search
from talos.prompts.arg_resolver import ARG_RESOLVER_SYSTEM_PROMPT
from talos.state import TalosState
from talos.vault.manager import SkillManager


# Primitives keyed by the names the Planner uses in `tool_hint`.
# `human_input` is excluded — it's only invoked via the Orchestrator's
# HITL flow in Phase 9, never as a regular sub-task.
PRIMITIVES: dict[str, Callable[..., Any]] = {
    "web_search": web_search,
    "web_read": web_read,
    "file_read": file_read,
    "file_write": file_write,
    "python_exec": python_exec,
    "shell_exec": shell_exec,
}


class ResolvedArgs(BaseModel):
    """ArgResolver structured output."""

    args: list[Any] = Field(
        default_factory=list,
        description="positional arguments in order",
    )
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="keyword arguments by name",
    )


def _make_resolver_llm() -> Any:
    base = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.0,  # arg resolution should be fully deterministic
    )
    # `method="function_calling"` because our ResolvedArgs has open-ended
    # types (`list[Any]`, `dict[str, Any]`) — OpenAI's strict structured-
    # outputs mode rejects those, but the function_calling path accepts them.
    return base.with_structured_output(ResolvedArgs, method="function_calling")


def _get_skill_manager() -> SkillManager:
    return SkillManager()


def _resolve_args(
    signature: str,
    sub_task: dict,
    user_query: str,
    prior_results: list[dict],
    history: str = "",
) -> ResolvedArgs:
    """Ask the LLM to fill concrete args for the tool call."""
    history_block = history if history else "(no prior turns)"
    user_msg = (
        f"Function signature: {signature}\n\n"
        f"Sub-task description: {sub_task.get('action', '')}\n"
        f"Sub-task input description: {sub_task.get('input_description', '')}\n\n"
        f"Recent conversation (most recent last):\n{history_block}\n\n"
        f"Current user query: {user_query}\n\n"
        f"Prior sub-task results (this run):\n{_format_prior_results(prior_results)}\n"
    )
    return _make_resolver_llm().invoke([
        SystemMessage(content=ARG_RESOLVER_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])


def _format_prior_results(results: list[dict]) -> str:
    """Compact summary for the arg-resolver prompt. The full values are kept
    in `results` and substituted in via `_substitute_placeholders` after
    the LLM emits `__SUBTASK_OUTPUT_N__` markers."""
    if not results:
        return "(none)"
    lines = []
    for r in results:
        sid = r.get("sub_task_id", "?")
        out = r.get("output")
        snippet = repr(out)
        if len(snippet) > 500:
            snippet = (
                snippet[:500]
                + f"...(truncated — to use the FULL value, emit __SUBTASK_OUTPUT_{sid}__)"
            )
        lines.append(f"- sub-task {sid}: {snippet}")
    return "\n".join(lines)


# Matches `__SUBTASK_OUTPUT_<N>__` optionally followed by a chain of
# accessors like [0], ["key"], or ['key']. Examples:
#   __SUBTASK_OUTPUT_1__                  → whole output
#   __SUBTASK_OUTPUT_1__[0]               → first element
#   __SUBTASK_OUTPUT_1__["results"][2]    → nested
#   __SUBTASK_OUTPUT_1__[0]["url"]        → list-of-dicts
_PLACEHOLDER_RE = re.compile(
    r"""__SUBTASK_OUTPUT_(\d+)__((?:\[(?:\d+|"[^"]*"|'[^']*')\])*)"""
)
_ACCESSOR_RE = re.compile(r"""\[(\d+|"[^"]*"|'[^']*')\]""")


def _walk_accessors(obj: Any, accessor_chain: str) -> Any:
    """Apply a chain of `[idx]` / `["key"]` accessors. Any failure returns the
    last successful intermediate (better than raising; the tool will then
    explain the type mismatch in its own error)."""
    if not accessor_chain:
        return obj
    cur = obj
    for m in _ACCESSOR_RE.finditer(accessor_chain):
        token = m.group(1)
        try:
            if token.startswith(("'", '"')):
                cur = cur[token[1:-1]]
            else:
                cur = cur[int(token)]
        except (KeyError, IndexError, TypeError):
            return cur
    return cur


def _substitute_placeholders(value: Any, results_by_id: dict) -> Any:
    """Walk the resolved-args structure and replace SUBTASK_OUTPUT placeholders
    (with optional accessor chains) with actual prior outputs.

    For a STRING that is exactly a placeholder → swap in the raw object
    (preserves type — list/dict returned as such, not str-ified).
    For a STRING that contains a placeholder → string-substitute (str()).
    """
    if isinstance(value, str):
        m = _PLACEHOLDER_RE.fullmatch(value.strip())
        if m:
            sid = int(m.group(1))
            rec = results_by_id.get(sid)
            if rec is None:
                return value
            return _walk_accessors(rec.get("output"), m.group(2))
        # Partial: in-string substitution, stringified.
        def _sub(mm):
            sid = int(mm.group(1))
            rec = results_by_id.get(sid) or {}
            return str(_walk_accessors(rec.get("output"), mm.group(2)))
        return _PLACEHOLDER_RE.sub(_sub, value)
    if isinstance(value, list):
        return [_substitute_placeholders(v, results_by_id) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_placeholders(v, results_by_id) for k, v in value.items()}
    return value


def _build_kwargs_from_bindings(
    param_bindings: dict[str, Any],
    results_by_id: dict,
) -> dict[str, Any]:
    """Resolve each binding to a concrete value.

    A binding value is either a literal (kept as-is) OR a string of the form
    `__SUBTASK_OUTPUT_<N>__[...]` which is resolved against prior results
    using the same accessor walker as the legacy placeholder substitution.
    Missing upstream sub-tasks raise ValueError so the failure is loud and
    targeted, not silently degraded into a wrong call.
    """
    kwargs: dict[str, Any] = {}
    for name, raw in param_bindings.items():
        if isinstance(raw, str):
            m = _PLACEHOLDER_RE.fullmatch(raw.strip())
            if m:
                sid = int(m.group(1))
                rec = results_by_id.get(sid)
                if rec is None:
                    raise ValueError(
                        f"param '{name}' references sub-task {sid}, which has not run"
                    )
                kwargs[name] = _walk_accessors(rec.get("output"), m.group(2))
                continue
            # Strings without the marker are literal strings.
            kwargs[name] = raw
        else:
            kwargs[name] = raw
    return kwargs


def _validate_kwargs(fn: Callable[..., Any], kwargs: dict[str, Any]) -> None:
    """Cheap pre-flight check: every kwarg must be a real param of fn, and
    every required param must be present. Raises TypeError with a clear
    message on mismatch, before the function runs.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return  # built-ins / partials we can't introspect — skip cleanly
    params = sig.parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if not accepts_kwargs:
        unexpected = [k for k in kwargs if k not in params]
        if unexpected:
            raise TypeError(
                f"unexpected kwargs {unexpected} for {fn.__name__}{sig}"
            )
    required = [
        n for n, p in params.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    missing = [n for n in required if n not in kwargs]
    if missing:
        raise TypeError(f"missing required args {missing} for {fn.__name__}{sig}")


def _signature_of(fn: Callable[..., Any]) -> str:
    try:
        return f"{fn.__name__}{inspect.signature(fn)}"
    except (TypeError, ValueError):
        return f"{getattr(fn, '__name__', 'tool')}(...)"


def _resolve_callable(sub_task: dict, state: TalosState, mgr: SkillManager) -> Callable[..., Any]:
    """Pick the right callable for this sub-task.

    Raises ValueError on misconfigured sub-tasks — caller wraps this so the
    graph keeps moving with a recorded failure rather than crashing.
    """
    needs = sub_task.get("needs")
    hint = sub_task.get("tool_hint")
    if needs == "primitive":
        if not hint or hint not in PRIMITIVES:
            raise ValueError(f"Unknown primitive: {hint!r}")
        return PRIMITIVES[hint]
    if needs == "vault":
        if not hint:
            raise ValueError("vault sub-task missing tool_hint")
        return mgr.load(hint)
    if needs == "forge":
        forged = state.get("forged_tool") or {}
        name = forged.get("name")
        if not name:
            raise ValueError("forge sub-task has no forged_tool in state")
        return mgr.load(name)
    raise ValueError(f"Unknown needs label: {needs!r}")


def executor_node(state: TalosState) -> dict:
    """LangGraph node: run the current sub-task and append its result.

    Reads:  current_sub_task, forged_tool, sub_task_results, messages
    Writes: execution_result (for the current call), sub_task_results (appended)
    """
    sub_task = state.get("current_sub_task") or {}
    if not sub_task:
        return {"execution_result": None}

    mgr = _get_skill_manager()

    try:
        fn = _resolve_callable(sub_task, state, mgr)
    except (ValueError, KeyError) as e:
        result = _record_failure(state, sub_task, f"dispatch error: {e}")
        return result

    user_query = _last_user_text(state)
    prior_results = state.get("sub_task_results") or []
    signature = _signature_of(fn)
    history = format_recent_history(state.get("messages") or [])
    results_by_id = {r.get("sub_task_id"): r for r in prior_results}

    # Typed-contract path: if the Planner emitted input_schema + param_bindings
    # for this sub-task, build kwargs deterministically (no LLM, no drift) and
    # validate against the function signature before invocation.
    if sub_task.get("needs") == "forge" and sub_task.get("input_schema"):
        try:
            final_args, final_kwargs = [], _build_kwargs_from_bindings(
                sub_task.get("param_bindings") or {}, results_by_id,
            )
            _validate_kwargs(fn, final_kwargs)
        except (ValueError, TypeError) as e:
            return _record_failure(state, sub_task, f"contract violation: {e}")
    else:
        # Legacy path: LLM-driven arg resolver (used for primitive + vault).
        try:
            resolved = _resolve_args(signature, sub_task, user_query, prior_results, history)
        except Exception as e:  # noqa: BLE001 — resolver failure is recoverable
            return _record_failure(state, sub_task, f"arg resolution failed: {e}")
        final_args = _substitute_placeholders(resolved.args, results_by_id)
        final_kwargs = _substitute_placeholders(resolved.kwargs, results_by_id)

    try:
        output = fn(*final_args, **final_kwargs)
        ok = True
        error: str | None = None
    except Exception as e:  # noqa: BLE001 — tool execution may legitimately fail
        output = None
        ok = False
        error = f"{type(e).__name__}: {e}"

    # Vault/forge usage tracking. Success bumps usage; failure bumps
    # consecutive_failures and may auto-prune (after N failures in a row).
    if sub_task.get("needs") in {"vault", "forge"}:
        name = sub_task.get("tool_hint") or (state.get("forged_tool") or {}).get("name")
        if name:
            if ok:
                mgr.record_usage(name)
            else:
                mgr.record_failure(name, reason=error or "unknown error")

    new_record = {
        "sub_task_id": sub_task.get("id"),
        "ok": ok,
        "output": output,
        "error": error,
    }
    return {
        "execution_result": _stringify(output) if ok else error,
        "sub_task_results": [*prior_results, new_record],
    }


# ---- internal helpers -----------------------------------------------------

def _record_failure(state: TalosState, sub_task: dict, reason: str) -> dict:
    prior = state.get("sub_task_results") or []
    new_record = {
        "sub_task_id": sub_task.get("id"),
        "ok": False,
        "output": None,
        "error": reason,
    }
    return {
        "execution_result": reason,
        "sub_task_results": [*prior, new_record],
    }


def _last_user_text(state: TalosState) -> str:
    for msg in reversed(state.get("messages", []) or []):
        if msg.__class__.__name__ == "HumanMessage":
            return str(getattr(msg, "content", "") or "")
    return ""


def _stringify(x: object) -> str:
    if isinstance(x, str):
        return x
    return repr(x)
