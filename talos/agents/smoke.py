"""Smoke-test gate — runs a forged tool against REAL upstream inputs once,
before it gets registered in the vault.

Why this exists: the unit tests the Tester runs are mocked. They confirm the
function works against the Forger's invented inputs. Reality has different
shapes — APIs return fields the Forger didn't expect, types don't match,
upstream sub-task outputs need different access patterns. Without this gate,
those failures only surface when the Executor tries the real call — by which
point the broken tool is already in the vault.

The smoke gate skips when there's no typed contract to execute against (the
legacy planner path). When it runs, a failure is fed back to the Forger as a
retry, with the runtime error in the same channel as unit-test failures.
"""

from __future__ import annotations

from typing import Any

from talos.agents.executor import (
    _build_kwargs_from_bindings,
    _validate_kwargs,
)
from talos.state import TalosState


def _load_forged_function(forged: dict) -> Any:
    """exec the forged source in an isolated namespace and return the function.

    We rely on the Forger's contract (one top-level function whose name equals
    `forged['name']`). The Tester has already run this code once in subprocess
    so we know it imports cleanly. In-process exec here is the cheapest way
    to get a callable; the alternative would be writing it to a temp file
    and importlib-loading.
    """
    name = forged.get("name")
    code = forged.get("code", "")
    if not name or not code:
        raise ValueError("forged_tool missing name or code")
    ns: dict[str, Any] = {}
    exec(compile(code, f"<forged:{name}>", "exec"), ns)
    fn = ns.get(name)
    if fn is None or not callable(fn):
        raise ValueError(f"function {name!r} not defined in forged code")
    return fn


def smoke_node(state: TalosState) -> dict:
    """Real-call validation between unit tests and registration.

    Reads:  forged_tool, current_sub_task (input_schema, param_bindings),
            sub_task_results (for upstream output substitution)
    Writes: smoke_result {passed, error, output, skipped}
    """
    forged = state.get("forged_tool") or {}
    sub_task = state.get("current_sub_task") or {}

    if not sub_task.get("input_schema"):
        # No typed contract → no deterministic way to invoke. Pass through.
        return {"smoke_result": {"passed": True, "skipped": True,
                                  "reason": "no typed contract on sub-task"}}

    # If the tool needs env vars we may not have set, smoke would always
    # fail with KeyError. Skip and let the HITL flow handle missing keys.
    if forged.get("needs_env_vars"):
        return {"smoke_result": {"passed": True, "skipped": True,
                                  "reason": f"env vars required: {forged['needs_env_vars']}"}}

    try:
        fn = _load_forged_function(forged)
    except (SyntaxError, ValueError) as e:
        return {"smoke_result": {"passed": False, "skipped": False,
                                  "error": f"load error: {type(e).__name__}: {e}"}}

    prior = state.get("sub_task_results") or []
    results_by_id = {r.get("sub_task_id"): r for r in prior}

    try:
        kwargs = _build_kwargs_from_bindings(
            sub_task.get("param_bindings") or {}, results_by_id,
        )
        _validate_kwargs(fn, kwargs)
    except (ValueError, TypeError) as e:
        return {"smoke_result": {"passed": False, "skipped": False,
                                  "error": f"contract violation: {e}"}}

    try:
        out = fn(**kwargs)
    except Exception as e:  # noqa: BLE001 — smoke is meant to surface anything
        return {"smoke_result": {"passed": False, "skipped": False,
                                  "error": f"runtime: {type(e).__name__}: {e}"}}

    return {"smoke_result": {"passed": True, "skipped": False, "output": out}}
