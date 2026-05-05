"""Smoke-test gate (Change 1) — verify the gate catches runtime contract
breaks before a tool reaches the vault, and lets pure-python contracts pass."""

from __future__ import annotations

from talos.agents.smoke import smoke_node


def _state(forged_code: str, name: str, sub_task: dict, prior=None, env_vars=None) -> dict:
    return {
        "forged_tool": {"name": name, "code": forged_code, "test_code": "",
                         "needs_env_vars": env_vars or []},
        "current_sub_task": sub_task,
        "sub_task_results": prior or [],
    }


def test_smoke_passes_for_clean_pure_python():
    code = "def add(a, b):\n    return a + b\n"
    sub_task = {
        "id": 1, "needs": "forge", "input_schema": {"a": "int", "b": "int"},
        "output_schema": "int", "param_bindings": {"a": 2, "b": 3},
    }
    out = smoke_node(_state(code, "add", sub_task))
    s = out["smoke_result"]
    assert s["passed"] is True
    assert s["output"] == 5
    assert s["skipped"] is False


def test_smoke_skips_when_no_contract():
    """Old-style sub-task with no input_schema → smoke is a no-op pass."""
    code = "def foo():\n    return 42\n"
    sub_task = {"id": 1, "needs": "forge", "input_schema": {}, "param_bindings": {}}
    out = smoke_node(_state(code, "foo", sub_task))
    assert out["smoke_result"]["passed"] is True
    assert out["smoke_result"]["skipped"] is True


def test_smoke_skips_when_env_vars_required():
    """Tools that need API keys can't be smoke-tested without those keys.
    Skip cleanly so the HITL flow can ask for them."""
    code = "import os\ndef f():\n    return os.environ['X']\n"
    sub_task = {
        "id": 1, "needs": "forge", "input_schema": {},
        "param_bindings": {},
    }
    out = smoke_node(_state(code, "f", sub_task, env_vars=["X"]))
    assert out["smoke_result"]["passed"] is True
    assert out["smoke_result"]["skipped"] is True


def test_smoke_catches_runtime_keyerror():
    """The classic Cluster B / E bug: code accesses a dict key that doesn't
    exist in real input. Unit tests with mocks would pass; smoke catches it."""
    code = (
        "def parse(payload: dict) -> str:\n"
        "    return payload['price']  # field doesn't exist in real input\n"
    )
    sub_task = {
        "id": 2, "needs": "forge",
        "input_schema": {"payload": "dict"}, "output_schema": "str",
        "param_bindings": {"payload": "__SUBTASK_OUTPUT_1__"},
        "depends_on": [1],
    }
    state = _state(code, "parse", sub_task,
                    prior=[{"sub_task_id": 1, "ok": True, "output": {"value": 100}}])
    out = smoke_node(state)
    s = out["smoke_result"]
    assert s["passed"] is False
    assert "KeyError" in s["error"]


def test_smoke_catches_signature_mismatch():
    """Bindings supply a kwarg the function doesn't accept → caught before
    invocation by _validate_kwargs."""
    code = "def square(x: int) -> int:\n    return x * x\n"
    sub_task = {
        "id": 1, "needs": "forge",
        "input_schema": {"x": "int", "y": "int"},  # planner mistakenly gave 2 params
        "output_schema": "int",
        "param_bindings": {"x": 4, "y": 5},
    }
    out = smoke_node(_state(code, "square", sub_task))
    s = out["smoke_result"]
    assert s["passed"] is False
    assert "contract violation" in s["error"]
    assert "unexpected" in s["error"] or "missing" in s["error"]
