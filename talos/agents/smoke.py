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

import inspect
import tempfile
from pathlib import Path
from typing import Any

from talos.agents.executor import (
    _build_kwargs_from_bindings,
    _validate_kwargs,
    coerce_to_schema,
)
from talos.events import emit
from talos.sandbox import SandboxedTool, error_text
from talos.state import TalosState

# Longest `call` / `result` string sent in a forge.smoke event.
_SMOKE_REPR_LIMIT = 200


def short_repr(value: Any, limit: int = _SMOKE_REPR_LIMIT) -> str:
    """repr() capped at `limit` characters, with an ellipsis when cut."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _call_text(name: str, kwargs: dict[str, Any]) -> str:
    """Render a call like `caesar_cipher(text='abc', shift=3)` for the UI."""
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    text = f"{name}({args})"
    return text if len(text) <= _SMOKE_REPR_LIMIT else text[: _SMOKE_REPR_LIMIT - 1] + "…"


def _write_forged_tool(forged: dict, directory: Path) -> SandboxedTool:
    """Write the forged source into `directory` and return a sandboxed
    callable for it. The code never runs in this process.

    Raises:
        ValueError: If the forged tool has no name or code, the code doesn't
            parse, or it doesn't define a function named `forged['name']`.
    """
    name = forged.get("name")
    code = forged.get("code", "")
    if not name or not code:
        raise ValueError("forged_tool missing name or code")
    path = directory / "forged_tool.py"
    path.write_text(code, encoding="utf-8")
    return SandboxedTool(path, name)


def _is_zero_arg(fn: Any) -> bool:
    """True if `fn` can be called with no arguments."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return all(
        p.default is not inspect.Parameter.empty
        or p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for p in params
    )


def smoke_node(state: TalosState) -> dict:
    """Real-call validation between unit tests and registration.

    Reads:  forged_tool, current_sub_task (input_schema, param_bindings),
            sub_task_results (for upstream output substitution)
    Writes: smoke_result {passed, error, output, skipped}
    Emits:  forge.smoke {call, result, passed} whenever the gate did not skip.
            `call` is None when the tool could not be loaded or its
            arguments could not be built.
    """
    forged = state.get("forged_tool") or {}
    sub_task = state.get("current_sub_task") or {}

    # If the tool needs env vars we may not have set, smoke would always
    # fail with KeyError. Skip and let the HITL flow handle missing keys.
    if forged.get("needs_env_vars"):
        return {
            "smoke_result": {
                "passed": True,
                "skipped": True,
                "reason": f"env vars required: {forged['needs_env_vars']}",
            }
        }

    # Unregistered code: write it to a temporary file for the sandbox.
    with tempfile.TemporaryDirectory(prefix="talos-smoke-") as tmp:
        try:
            fn = _write_forged_tool(forged, Path(tmp))
        except ValueError as e:
            emit("forge.smoke", call=None, result=None, passed=False)
            return {
                "smoke_result": {"passed": False, "skipped": False, "error": f"load error: {e}"}
            }
        return _smoke(fn, forged, sub_task, state)


def _smoke(fn: SandboxedTool, forged: dict, sub_task: dict, state: TalosState) -> dict:
    """Build the call from the sub-task contract and run it once in the sandbox."""
    has_contract = bool(sub_task.get("input_schema"))
    if not has_contract and not _is_zero_arg(fn):
        # No typed contract → no deterministic way to invoke. Pass through.
        # (Zero-arg tools are still callable, so they fall through and run.)
        return {
            "smoke_result": {
                "passed": True,
                "skipped": True,
                "reason": "no typed contract on sub-task",
            }
        }

    prior = state.get("sub_task_results") or []
    results_by_id = {r.get("sub_task_id"): r for r in prior}

    try:
        bindings = (sub_task.get("param_bindings") or {}) if has_contract else {}
        kwargs = coerce_to_schema(
            _build_kwargs_from_bindings(bindings, results_by_id),
            sub_task.get("input_schema") or {},
        )
        _validate_kwargs(fn, kwargs)
    except (ValueError, TypeError) as e:
        emit("forge.smoke", call=None, result=None, passed=False)
        return {
            "smoke_result": {"passed": False, "skipped": False, "error": f"contract violation: {e}"}
        }

    call = _call_text(forged.get("name") or "tool", kwargs)
    try:
        out = fn(**kwargs)
    except Exception as e:  # noqa: BLE001 — smoke is meant to surface anything
        emit("forge.smoke", call=call, result=None, passed=False)
        return {
            "smoke_result": {
                "passed": False,
                "skipped": False,
                "error": f"runtime: {error_text(e)}",
            }
        }

    emit("forge.smoke", call=call, result=short_repr(out), passed=True)
    return {"smoke_result": {"passed": True, "skipped": False, "output": out}}
