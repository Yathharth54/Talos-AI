"""Smoke-test gate (Change 1) — verify the gate catches runtime contract
breaks before a tool reaches the vault, and lets pure-python contracts pass."""

from __future__ import annotations

from talos.agents.smoke import smoke_node


def _state(forged_code: str, name: str, sub_task: dict, prior=None, env_vars=None) -> dict:
    return {
        "forged_tool": {
            "name": name,
            "code": forged_code,
            "test_code": "",
            "needs_env_vars": env_vars or [],
        },
        "current_sub_task": sub_task,
        "sub_task_results": prior or [],
    }


def test_smoke_passes_for_clean_pure_python():
    code = "def add(a, b):\n    return a + b\n"
    sub_task = {
        "id": 1,
        "needs": "forge",
        "input_schema": {"a": "int", "b": "int"},
        "output_schema": "int",
        "param_bindings": {"a": 2, "b": 3},
    }
    out = smoke_node(_state(code, "add", sub_task))
    s = out["smoke_result"]
    assert s["passed"] is True
    assert s["output"] == 5
    assert s["skipped"] is False


def test_smoke_skips_when_no_contract_and_args_required():
    """No input_schema and the function needs args → no way to call it; pass."""
    code = "def foo(x):\n    return x\n"
    sub_task = {"id": 1, "needs": "forge", "input_schema": {}, "param_bindings": {}}
    out = smoke_node(_state(code, "foo", sub_task))
    assert out["smoke_result"]["passed"] is True
    assert out["smoke_result"]["skipped"] is True


def test_smoke_runs_zero_arg_tool_without_contract():
    """A zero-arg tool is always callable, so it is smoke-tested even with
    no input_schema."""
    code = "def foo():\n    return 42\n"
    sub_task = {"id": 1, "needs": "forge", "input_schema": {}, "param_bindings": {}}
    out = smoke_node(_state(code, "foo", sub_task))
    assert out["smoke_result"]["passed"] is True
    assert out["smoke_result"]["skipped"] is False
    assert out["smoke_result"]["output"] == 42


def test_smoke_catches_zero_arg_tool_failure_without_contract():
    """e.g. a fetcher whose mocked unit tests pass but the real API response
    has a different shape — must fail smoke so the Forger retries."""
    code = "def fetch():\n    raise ValueError('Unexpected response format')\n"
    sub_task = {"id": 1, "needs": "forge", "input_schema": {}, "param_bindings": {}}
    out = smoke_node(_state(code, "fetch", sub_task))
    assert out["smoke_result"]["passed"] is False
    assert "Unexpected response format" in out["smoke_result"]["error"]


def test_smoke_skips_when_env_vars_required():
    """Tools that need API keys can't be smoke-tested without those keys.
    Skip cleanly so the HITL flow can ask for them."""
    code = "import os\ndef f():\n    return os.environ['X']\n"
    sub_task = {
        "id": 1,
        "needs": "forge",
        "input_schema": {},
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
        "id": 2,
        "needs": "forge",
        "input_schema": {"payload": "dict"},
        "output_schema": "str",
        "param_bindings": {"payload": "__SUBTASK_OUTPUT_1__"},
        "depends_on": [1],
    }
    state = _state(
        code, "parse", sub_task, prior=[{"sub_task_id": 1, "ok": True, "output": {"value": 100}}]
    )
    out = smoke_node(state)
    s = out["smoke_result"]
    assert s["passed"] is False
    assert "KeyError" in s["error"]


def test_smoke_catches_signature_mismatch():
    """Bindings supply a kwarg the function doesn't accept → caught before
    invocation by _validate_kwargs."""
    code = "def square(x: int) -> int:\n    return x * x\n"
    sub_task = {
        "id": 1,
        "needs": "forge",
        "input_schema": {"x": "int", "y": "int"},  # planner mistakenly gave 2 params
        "output_schema": "int",
        "param_bindings": {"x": 4, "y": 5},
    }
    out = smoke_node(_state(code, "square", sub_task))
    s = out["smoke_result"]
    assert s["passed"] is False
    assert "contract violation" in s["error"]
    assert "unexpected" in s["error"] or "missing" in s["error"]


def test_smoke_parses_upstream_json_string_for_dict_param():
    code = (
        "def count_keys(data):\n"
        "    if not isinstance(data, dict):\n"
        "        raise TypeError('need dict')\n"
        "    return len(data)\n"
    )
    sub_task = {
        "id": 2,
        "needs": "forge",
        "input_schema": {"data": "dict"},
        "output_schema": "int",
        "param_bindings": {"data": "__SUBTASK_OUTPUT_1__"},
    }
    prior = [{"sub_task_id": 1, "ok": True, "output": '{"a": 1}', "error": None}]
    out = smoke_node(_state(code, "count_keys", sub_task, prior=prior))
    assert out["smoke_result"]["passed"] is True, out["smoke_result"]
    assert out["smoke_result"]["output"] == 1


# ---- forge.smoke events (overview §4.4) --------------------------------------


def _smoke_events(state: dict) -> list[dict]:
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("smoke", smoke_node)
    g.add_edge(START, "smoke")
    g.add_edge("smoke", END)
    return list(g.compile().stream(state, stream_mode="custom"))


_ADD_TASK = {
    "id": 1,
    "needs": "forge",
    "input_schema": {"a": "int", "b": "int"},
    "output_schema": "int",
    "param_bindings": {"a": 2, "b": 3},
}


def test_smoke_emits_call_and_result_on_success():
    events = _smoke_events(_state("def add(a, b):\n    return a + b\n", "add", _ADD_TASK))
    assert events == [
        {"type": "forge.smoke", "data": {"call": "add(a=2, b=3)", "result": "5", "passed": True}}
    ]


def test_smoke_emits_failure_with_the_call():
    code = "def add(a, b):\n    raise ValueError('nope')\n"
    [event] = _smoke_events(_state(code, "add", _ADD_TASK))
    assert event["data"] == {"call": "add(a=2, b=3)", "result": None, "passed": False}


def test_smoke_emits_nothing_when_skipped():
    state = _state("def f():\n    return 1\n", "f", {}, env_vars=["SOME_KEY"])
    assert _smoke_events(state) == []


def test_smoke_emits_no_call_when_the_tool_cannot_load():
    [event] = _smoke_events(_state("def add(:\n", "add", _ADD_TASK))
    assert event["data"] == {"call": None, "result": None, "passed": False}


def test_smoke_result_repr_is_capped():
    from talos.agents.smoke import short_repr

    text = short_repr("x" * 1000)
    assert len(text) == 200
    assert text.endswith("…")
