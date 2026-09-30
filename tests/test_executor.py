"""Phase 6 — Executor tests.

Patterns:
- Monkeypatch `_make_resolver_llm` with a fake that returns a canned
  ResolvedArgs — same seam pattern as Forger / Planner.
- Monkeypatch `_get_skill_manager` to point at a tmp_path vault, so vault
  tests don't touch the real folder.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from talos.agents import executor as exec_mod
from talos.agents.executor import ResolvedArgs, executor_node
from talos.vault.manager import SkillManager

# ---- helpers --------------------------------------------------------------


class _FakeResolver:
    def __init__(self, resolved: ResolvedArgs) -> None:
        self._resolved = resolved
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self._resolved


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> SkillManager:
    mgr = SkillManager(vault_dir=tmp_path)
    monkeypatch.setattr(exec_mod, "_get_skill_manager", lambda: mgr)
    return mgr


def _patch_resolver(monkeypatch, resolved: ResolvedArgs) -> _FakeResolver:
    fake = _FakeResolver(resolved)
    monkeypatch.setattr(exec_mod, "_make_resolver_llm", lambda: fake)
    return fake


def _state(query: str = "do thing", **extra) -> dict:
    base = {"messages": [HumanMessage(content=query)]}
    base.update(extra)
    return base


# ---- primitive dispatch ---------------------------------------------------


def test_executor_runs_primitive_with_resolved_args(vault, monkeypatch, tmp_path: Path):
    target = tmp_path / "out.txt"
    _patch_resolver(monkeypatch, ResolvedArgs(args=[str(target), "hello"], kwargs={}))

    sub_task = {"id": 1, "needs": "primitive", "tool_hint": "file_write", "action": "write"}
    out = executor_node(_state("write hello to a file", current_sub_task=sub_task))

    assert out["sub_task_results"][0]["ok"] is True
    assert target.read_text() == "hello"


def test_executor_unknown_primitive_records_failure(vault, monkeypatch):
    sub_task = {"id": 1, "needs": "primitive", "tool_hint": "does_not_exist", "action": "x"}
    out = executor_node(_state(current_sub_task=sub_task))
    assert out["sub_task_results"][0]["ok"] is False
    assert "Unknown primitive" in out["sub_task_results"][0]["error"]


# ---- vault dispatch -------------------------------------------------------


def test_executor_runs_vault_tool(vault, monkeypatch):
    vault.register(
        {
            "name": "doubler",
            "description": "doubles a number",
            "keywords": ["double"],
            "function": "doubler",
            "signature": "doubler(n: int) -> int",
        },
        "def doubler(n):\n    return n * 2\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[21], kwargs={}))

    sub_task = {"id": 1, "needs": "vault", "tool_hint": "doubler", "action": "double 21"}
    out = executor_node(_state(current_sub_task=sub_task))
    assert out["sub_task_results"][0]["ok"] is True
    assert out["sub_task_results"][0]["output"] == 42


def test_executor_vault_records_usage(vault, monkeypatch):
    vault.register(
        {
            "name": "noop",
            "description": "does nothing",
            "keywords": ["noop"],
            "function": "noop",
            "signature": "noop() -> None",
        },
        "def noop():\n    return None\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "noop", "action": "no-op"}

    executor_node(_state(current_sub_task=sub_task))
    executor_node(_state(current_sub_task=sub_task))
    entry = next(e for e in vault.all() if e["name"] == "noop")
    assert entry["usage_count"] == 2
    assert entry["last_used"] is not None


# ---- forge dispatch (post-learn) -----------------------------------------


def test_executor_runs_freshly_forged_tool(vault, monkeypatch):
    # Simulate the path where Learn has just registered a forged tool and
    # the Executor immediately runs it for the current sub-task.
    vault.register(
        {
            "name": "shouter",
            "description": "uppercases input",
            "keywords": ["upper"],
            "function": "shouter",
            "signature": "shouter(s: str) -> str",
        },
        "def shouter(s):\n    return s.upper()\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=["hi"], kwargs={}))

    sub_task = {"id": 1, "needs": "forge", "action": "uppercase"}
    state = _state(
        current_sub_task=sub_task,
        forged_tool={"name": "shouter"},
    )
    out = executor_node(state)
    assert out["sub_task_results"][0]["output"] == "HI"


def test_executor_forge_without_forged_tool_fails(vault, monkeypatch):
    sub_task = {"id": 1, "needs": "forge", "action": "x"}
    out = executor_node(_state(current_sub_task=sub_task))
    assert out["sub_task_results"][0]["ok"] is False
    assert "no forged_tool" in out["sub_task_results"][0]["error"]


# ---- runtime errors -------------------------------------------------------


def test_executor_records_failure_on_vault_tool_error(vault, monkeypatch):
    """When a vault tool raises, executor should bump consecutive_failures.
    Two consecutive failures auto-prune the entry from the manifest."""
    vault.register(
        {
            "name": "boom",
            "description": "raises",
            "keywords": ["err"],
            "function": "boom",
            "signature": "boom() -> None",
        },
        "def boom():\n    raise ValueError('kaboom')\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "boom", "action": "explode"}

    # First failure — entry remains, counter at 1
    executor_node(_state(current_sub_task=sub_task))
    entry = next(e for e in vault.all() if e["name"] == "boom")
    assert entry["consecutive_failures"] == 1

    # Second failure — pruned
    executor_node(_state(current_sub_task=sub_task))
    assert not any(e["name"] == "boom" for e in vault.all())


def test_executor_captures_tool_runtime_error(vault, monkeypatch):
    vault.register(
        {
            "name": "boom",
            "description": "raises",
            "keywords": ["err"],
            "function": "boom",
            "signature": "boom() -> None",
        },
        "def boom():\n    raise ValueError('kaboom')\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "boom", "action": "explode"}

    out = executor_node(_state(current_sub_task=sub_task))
    rec = out["sub_task_results"][0]
    assert rec["ok"] is False
    assert "ValueError" in rec["error"]
    assert "kaboom" in rec["error"]


# ---- empty / missing sub-task --------------------------------------------


def test_executor_no_sub_task_returns_clean_state(vault, monkeypatch):
    out = executor_node(_state())
    assert out["execution_result"] is None


# ---- placeholder substitution (truncation fix) ---------------------------


def test_substitute_exact_placeholder_returns_raw_object(vault, monkeypatch, tmp_path: Path):
    """An arg that is EXACTLY `__SUBTASK_OUTPUT_N__` gets the raw prior
    output substituted in — no stringification, full content preserved."""
    target = tmp_path / "out.txt"
    huge = "X" * 5000  # well past the 500-char prompt-truncation
    _patch_resolver(
        monkeypatch,
        ResolvedArgs(
            args=[str(target), "__SUBTASK_OUTPUT_1__"],
            kwargs={},
        ),
    )
    sub_task = {"id": 2, "needs": "primitive", "tool_hint": "file_write", "action": "save"}
    state = _state(
        "save the page",
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": huge}],
    )
    out = executor_node(state)
    assert out["sub_task_results"][1]["ok"] is True
    assert target.read_text() == huge  # full 5000 chars, NOT truncated
    assert "...(truncated)" not in target.read_text()


def test_substitute_within_string_does_string_replace(vault, monkeypatch, tmp_path: Path):
    """A string CONTAINING a placeholder gets string-substituted."""
    target = tmp_path / "out.txt"
    _patch_resolver(
        monkeypatch,
        ResolvedArgs(
            args=[str(target), "Result was: __SUBTASK_OUTPUT_1__"],
            kwargs={},
        ),
    )
    sub_task = {"id": 2, "needs": "primitive", "tool_hint": "file_write", "action": "wrap"}
    state = _state(
        "wrap the result",
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": "hello"}],
    )
    executor_node(state)
    assert target.read_text() == "Result was: hello"


def test_substitute_with_index_accessor(vault, monkeypatch, tmp_path: Path):
    """`__SUBTASK_OUTPUT_1__[0]` → first list element."""
    target = tmp_path / "out.txt"
    _patch_resolver(
        monkeypatch,
        ResolvedArgs(
            args=[str(target), "__SUBTASK_OUTPUT_1__[0]"],
            kwargs={},
        ),
    )
    sub_task = {"id": 2, "needs": "primitive", "tool_hint": "file_write", "action": "save"}
    state = _state(
        "save first",
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": ["first", "second"]}],
    )
    executor_node(state)
    assert target.read_text() == "first"


def test_substitute_with_key_accessor(vault, monkeypatch):
    """`__SUBTASK_OUTPUT_1__["url"]` extracts dict value."""
    vault.register(
        {
            "name": "echo",
            "description": "echo",
            "keywords": ["echo"],
            "function": "echo",
            "signature": "echo(x) -> str",
        },
        "def echo(x):\n    return x\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=['__SUBTASK_OUTPUT_1__["url"]'], kwargs={}))
    sub_task = {"id": 2, "needs": "vault", "tool_hint": "echo", "action": "x"}
    state = _state(
        "extract",
        current_sub_task=sub_task,
        sub_task_results=[
            {"sub_task_id": 1, "ok": True, "output": {"url": "https://x.com", "title": "X"}}
        ],
    )
    out = executor_node(state)
    assert out["sub_task_results"][1]["output"] == "https://x.com"


def test_substitute_chained_accessors(vault, monkeypatch):
    """`__SUBTASK_OUTPUT_1__[0]["url"]` walks list-of-dicts."""
    vault.register(
        {
            "name": "echo",
            "description": "echo",
            "keywords": ["echo"],
            "function": "echo",
            "signature": "echo(x) -> str",
        },
        "def echo(x):\n    return x\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=['__SUBTASK_OUTPUT_1__[0]["url"]'], kwargs={}))
    sub_task = {"id": 2, "needs": "vault", "tool_hint": "echo", "action": "x"}
    state = _state(
        "first url",
        current_sub_task=sub_task,
        sub_task_results=[
            {
                "sub_task_id": 1,
                "ok": True,
                "output": [{"url": "https://a.com"}, {"url": "https://b.com"}],
            }
        ],
    )
    out = executor_node(state)
    assert out["sub_task_results"][1]["output"] == "https://a.com"


def test_substitute_preserves_type_for_dict_args(vault, monkeypatch):
    """If a prior output is a dict and the resolver puts a placeholder in a
    kwarg, the actual dict (not its str repr) reaches the tool."""
    vault.register(
        {
            "name": "echo",
            "description": "echo arg",
            "keywords": ["echo"],
            "function": "echo",
            "signature": "echo(x) -> object",
        },
        "def echo(x):\n    return x\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=["__SUBTASK_OUTPUT_1__"], kwargs={}))
    sub_task = {"id": 2, "needs": "vault", "tool_hint": "echo", "action": "passthrough"}
    state = _state(
        "echo prior",
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": {"a": 1, "b": [2, 3]}}],
    )
    out = executor_node(state)
    assert out["sub_task_results"][1]["output"] == {"a": 1, "b": [2, 3]}


# ---- arg resolver received the right context -----------------------------


def test_arg_resolver_sees_prior_results(vault, monkeypatch):
    # The resolver should be handed prior sub-task outputs in its prompt.
    # We don't care about the resolved args here — just that the prompt
    # contains the upstream output.
    fake = _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={}))
    vault.register(
        {
            "name": "sink",
            "description": "ignores input",
            "keywords": ["x"],
            "function": "sink",
            "signature": "sink() -> None",
        },
        "def sink():\n    return None\n",
    )
    sub_task = {"id": 2, "needs": "vault", "tool_hint": "sink", "action": "use upstream"}
    state = _state(
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": "hello-from-1"}],
    )
    executor_node(state)
    user_msg_content = fake.calls[0][1].content
    assert "hello-from-1" in user_msg_content
    assert "sub-task 1" in user_msg_content


# ---- typed contract path (Change 2) --------------------------------------


def test_typed_contract_skips_resolver_and_passes_kwargs(vault, monkeypatch):
    """When the Planner emits input_schema + param_bindings for a forge
    sub-task, the Executor builds kwargs from bindings (no LLM call) and
    calls the registered tool directly."""
    vault.register(
        {
            "name": "scale",
            "description": "scale x by k",
            "keywords": ["scale"],
            "function": "scale",
            "signature": "scale(x: float, k: float) -> float",
        },
        "def scale(x, k):\n    return x * k\n",
    )
    # If the resolver is touched, blow up loudly — proves we took the new path.
    monkeypatch.setattr(
        exec_mod,
        "_make_resolver_llm",
        lambda: (_ for _ in ()).throw(AssertionError("resolver should be skipped")),
    )

    sub_task = {
        "id": 1,
        "needs": "forge",
        "tool_hint": None,
        "action": "scale by 2.5",
        "input_schema": {"x": "float", "k": "float"},
        "output_schema": "float",
        "param_bindings": {"x": 4, "k": 2.5},
    }
    state = _state(
        "do it",
        current_sub_task=sub_task,
        forged_tool={"name": "scale"},
    )
    out = executor_node(state)
    rec = out["sub_task_results"][0]
    assert rec["ok"] is True
    assert rec["output"] == 10.0


def test_typed_contract_resolves_upstream_placeholder(vault, monkeypatch):
    """`__SUBTASK_OUTPUT_1__` in a binding pulls the prior result without
    going through the LLM resolver."""
    vault.register(
        {
            "name": "double",
            "description": "double x",
            "keywords": ["double"],
            "function": "double",
            "signature": "double(x: float) -> float",
        },
        "def double(x):\n    return x * 2\n",
    )
    monkeypatch.setattr(
        exec_mod,
        "_make_resolver_llm",
        lambda: (_ for _ in ()).throw(AssertionError("resolver should be skipped")),
    )
    sub_task = {
        "id": 2,
        "needs": "forge",
        "tool_hint": None,
        "action": "double upstream",
        "input_schema": {"x": "float"},
        "output_schema": "float",
        "param_bindings": {"x": "__SUBTASK_OUTPUT_1__"},
        "depends_on": [1],
    }
    state = _state(
        "double it",
        current_sub_task=sub_task,
        forged_tool={"name": "double"},
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": 7.0}],
    )
    out = executor_node(state)
    assert out["sub_task_results"][-1]["output"] == 14.0


def test_typed_contract_validation_catches_missing_param(vault, monkeypatch):
    """Required param missing from bindings → recorded as 'contract violation'
    BEFORE the function is invoked. The function never runs."""
    invocations = {"n": 0}

    def trace(x, k):
        invocations["n"] += 1
        return x * k

    vault.register(
        {
            "name": "scale2",
            "description": "scale",
            "keywords": ["scale"],
            "function": "scale2",
            "signature": "scale2(x: float, k: float) -> float",
        },
        "def scale2(x, k):\n    return x * k\n",
    )

    sub_task = {
        "id": 1,
        "needs": "forge",
        "tool_hint": None,
        "action": "scale",
        "input_schema": {"x": "float", "k": "float"},
        "output_schema": "float",
        "param_bindings": {"x": 4},  # missing 'k'
    }
    state = _state(
        "do it",
        current_sub_task=sub_task,
        forged_tool={"name": "scale2"},
    )
    out = executor_node(state)
    rec = out["sub_task_results"][0]
    assert rec["ok"] is False
    assert "contract violation" in (rec["error"] or "")
    assert "missing required args" in (rec["error"] or "")


# ---- live test (gated) ---------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1",
    reason="Set RUN_LIVE=1 to exercise real OpenAI arg resolution.",
)
def test_executor_live_arg_resolution(vault):
    """Real OpenAI arg-resolves a primitive call. file_write should be
    invoked with the path and content the user mentioned."""
    target = "/tmp/talos_live_executor_test.txt"
    if os.path.exists(target):
        os.unlink(target)

    sub_task = {
        "id": 1,
        "needs": "primitive",
        "tool_hint": "file_write",
        "action": "write the text 'hello world' to the file the user mentioned",
        "input_description": (
            "the path is mentioned in the user query; "
            "the content is the literal string 'hello world'"
        ),
        "depends_on": [],
    }
    out = executor_node(
        _state(
            f"please write 'hello world' to {target}",
            current_sub_task=sub_task,
        )
    )
    assert out["sub_task_results"][0]["ok"] is True
    assert os.path.exists(target)
    assert "hello world" in open(target).read()
    os.unlink(target)


def test_executor_records_failure_when_resolver_returns_none(vault, monkeypatch):
    """A model that skips the schema tool yields None; that must become a
    recorded sub-task failure, not an AttributeError that kills the graph."""
    _patch_resolver(monkeypatch, None)  # type: ignore[arg-type]
    sub_task = {"id": 1, "needs": "primitive", "tool_hint": "file_read", "action": "read"}
    out = executor_node(_state(current_sub_task=sub_task))
    rec = out["sub_task_results"][0]
    assert rec["ok"] is False
    assert "arg resolution failed" in rec["error"]


# ---- dependency short-circuit ---------------------------------------------


def test_executor_skips_subtask_when_upstream_failed(vault, monkeypatch):
    """#2 depends on #1, #1 failed → #2 must not run (e.g. must not write an
    empty file and report success)."""
    monkeypatch.setattr(
        exec_mod,
        "_make_resolver_llm",
        lambda: (_ for _ in ()).throw(AssertionError("must not resolve args")),
    )
    sub_task = {
        "id": 2,
        "needs": "primitive",
        "tool_hint": "file_write",
        "action": "save",
        "depends_on": [1],
    }
    prior = [{"sub_task_id": 1, "ok": False, "output": None, "error": "boom"}]
    out = executor_node(_state(current_sub_task=sub_task, sub_task_results=prior))
    rec = out["sub_task_results"][-1]
    assert rec["sub_task_id"] == 2
    assert rec["ok"] is False
    assert "skipped: upstream sub-task 1 failed" in rec["error"]


def test_executor_skip_propagates_transitively(vault, monkeypatch):
    """#3 depends on #2 which was itself skipped → #3 is skipped too."""
    sub_task = {
        "id": 3,
        "needs": "primitive",
        "tool_hint": "file_write",
        "action": "save",
        "depends_on": [2],
    }
    prior = [
        {"sub_task_id": 1, "ok": False, "output": None, "error": "boom"},
        {
            "sub_task_id": 2,
            "ok": False,
            "output": None,
            "error": "skipped: upstream sub-task 1 failed",
        },
    ]
    out = executor_node(_state(current_sub_task=sub_task, sub_task_results=prior))
    assert "skipped: upstream sub-task 2 failed" in out["sub_task_results"][-1]["error"]


# ---- type coercion at step boundaries -------------------------------------


@pytest.mark.parametrize(
    "value,type_str,expected",
    [
        ('{"a": 1}', "dict", {"a": 1}),
        ('{"a": 1}', "dict[str, Any]", {"a": 1}),
        ("[1, 2]", "list[int]", [1, 2]),
        ("[1, 2]", "List", [1, 2]),
        ("3.5", "float", 3.5),
        ("42", "int", 42),
        (" 7 ", "int", 7),
        ("not json", "dict", "not json"),  # unparseable → unchanged
        ("[1, 2]", "dict", "[1, 2]"),  # parses, wrong type → unchanged
        ("4.2", "int", "4.2"),  # not an int → unchanged
        ("hello", "str", "hello"),
        ({"a": 1}, "dict", {"a": 1}),  # already right type
        ("12", "Any", "12"),  # unknown/any → untouched
    ],
)
def test_coerce_to_schema(value, type_str, expected):
    out = exec_mod.coerce_to_schema({"x": value}, {"x": type_str})
    assert out == {"x": expected}


def test_typed_path_parses_upstream_json_string(vault, monkeypatch):
    """file_read returns a JSON *string*; a forged tool declaring a dict
    param must receive the parsed dict."""
    vault.register(
        {
            "name": "count_keys",
            "description": "count keys",
            "keywords": ["keys"],
            "function": "count_keys",
            "signature": "count_keys(data: dict) -> int",
        },
        "def count_keys(data):\n"
        "    if not isinstance(data, dict):\n"
        "        raise TypeError(f'data must be a dict, got {type(data).__name__}')\n"
        "    return len(data)\n",
    )
    sub_task = {
        "id": 2,
        "needs": "forge",
        "action": "count",
        "depends_on": [1],
        "input_schema": {"data": "dict"},
        "output_schema": "int",
        "param_bindings": {"data": "__SUBTASK_OUTPUT_1__"},
    }
    prior = [{"sub_task_id": 1, "ok": True, "output": '{"a": 1, "b": 2}', "error": None}]
    out = executor_node(
        _state(
            current_sub_task=sub_task, sub_task_results=prior, forged_tool={"name": "count_keys"}
        )
    )
    rec = out["sub_task_results"][-1]
    assert rec["ok"] is True, rec["error"]
    assert rec["output"] == 2


def test_vault_path_parses_json_string_using_type_hints(vault, monkeypatch):
    """Vault tools go through the LLM arg resolver (no input_schema); the
    function's own type hints drive coercion there."""
    vault.register(
        {
            "name": "flatten_json",
            "description": "flatten",
            "keywords": ["flatten"],
            "function": "flatten_json",
            "signature": "flatten_json(data: dict) -> dict",
        },
        "def flatten_json(data: dict) -> dict:\n"
        "    if not isinstance(data, dict):\n"
        "        raise TypeError(f'data must be a dict, got {type(data).__name__}')\n"
        "    return data\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=["__SUBTASK_OUTPUT_1__"], kwargs={}))
    sub_task = {
        "id": 2,
        "needs": "vault",
        "tool_hint": "flatten_json",
        "action": "flatten",
        "depends_on": [1],
    }
    prior = [{"sub_task_id": 1, "ok": True, "output": '{"app": "talos"}', "error": None}]
    out = executor_node(_state(current_sub_task=sub_task, sub_task_results=prior))
    rec = out["sub_task_results"][-1]
    assert rec["ok"] is True, rec["error"]
    assert rec["output"] == {"app": "talos"}


def test_schema_from_signature_reads_type_hints():
    def f(a: dict, b: list[int], c, *rest, d: float = 1.0):
        return a

    assert exec_mod.schema_from_signature(f) == {"a": "dict", "b": "list[int]", "d": "float"}


# ---- exec confirmation gate -----------------------------------------------


def _exec_graph():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("executor", executor_node)
    g.add_edge(START, "executor")
    g.add_edge("executor", END)
    return g.compile(checkpointer=MemorySaver())


def _exec_state(tool: str = "python_exec") -> dict:
    sub_task = {"id": 1, "needs": "primitive", "tool_hint": tool, "action": "run"}
    return _state(current_sub_task=sub_task, sub_task_results=[])


def test_exec_primitive_pauses_for_confirmation(vault, monkeypatch):
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print(1)"}))
    ran: list = []
    monkeypatch.setitem(exec_mod.PRIMITIVES, "python_exec", lambda **kw: ran.append(kw))

    app = _exec_graph()
    config = {"configurable": {"thread_id": "exec-pause"}}
    out = app.invoke(_exec_state(), config=config)

    payload = out["__interrupt__"][0].value
    assert payload["type"] == "confirm_exec"
    assert payload["preview"] == "print(1)"
    assert ran == []  # nothing runs before approval


def test_exec_decline_records_failure(vault, monkeypatch):
    from langgraph.types import Command

    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print(1)"}))
    ran: list = []
    monkeypatch.setitem(exec_mod.PRIMITIVES, "python_exec", lambda **kw: ran.append(kw))

    app = _exec_graph()
    config = {"configurable": {"thread_id": "exec-decline"}}
    app.invoke(_exec_state(), config=config)
    final = app.invoke(Command(resume={"approved": False}), config=config)

    assert ran == []
    rec = final["sub_task_results"][-1]
    assert rec["ok"] is False and rec["error"] == "declined by user"


def test_exec_approval_runs_the_args_the_user_saw(vault, monkeypatch):
    """On resume the node re-runs and the resolver may return different code;
    the approved args from the resume value must win."""
    from langgraph.types import Command

    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print('shown')"}))
    ran: list = []
    monkeypatch.setitem(exec_mod.PRIMITIVES, "shell_exec", lambda **kw: ran.append(kw) or "ok")

    app = _exec_graph()
    config = {"configurable": {"thread_id": "exec-approve"}}
    out = app.invoke(_exec_state("shell_exec"), config=config)
    payload = out["__interrupt__"][0].value

    # Resolver drifts on the re-run.
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "echo drifted"}))
    resume = {"approved": True, "args": payload["args"], "kwargs": payload["kwargs"]}
    final = app.invoke(Command(resume=resume), config=config)

    assert ran == [{"code": "print('shown')"}]
    assert final["sub_task_results"][-1]["ok"] is True


def test_exec_auto_approve_skips_prompt(vault, monkeypatch):
    monkeypatch.setenv("TALOS_AUTO_APPROVE_EXEC", "true")
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print(1)"}))
    monkeypatch.setitem(exec_mod.PRIMITIVES, "python_exec", lambda **kw: "done")

    result = executor_node(_exec_state())

    assert result["sub_task_results"][-1]["ok"] is True


# ---- call.* and vault.failure events (overview §4.4) ------------------------


def _exec_events(state: dict, config: dict | None = None, resume=None) -> list[dict]:
    """Stream the one-node executor graph and return its custom events."""
    from langgraph.types import Command

    app = _exec_graph()
    config = config or {"configurable": {"thread_id": "events"}}
    events = list(app.stream(state, config=config, stream_mode="custom"))
    if resume is not None:
        events += list(app.stream(Command(resume=resume), config=config, stream_mode="custom"))
    return events


def _add_tool(vault: SkillManager, body: str = "return a + b") -> None:
    vault.register(
        {
            "name": "add",
            "description": "add",
            "keywords": ["add"],
            "function": "add",
            "signature": "add(a: int, b: int) -> int",
        },
        f"def add(a: int, b: int) -> int:\n    {body}\n",
    )


def test_executor_emits_args_then_result(vault, monkeypatch):
    _add_tool(vault)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[2], kwargs={"b": "three"}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}

    events = _exec_events(_state(current_sub_task=sub_task))

    assert events[0] == {
        "type": "call.args",
        "data": {
            "tool": "add",
            "args": [["a", "2", False], ["b", "'three'", True]],
            "caption": None,
        },
    }
    assert events[1]["type"] == "call.error"  # 2 + "three" raises TypeError
    assert events[1]["data"]["when"] == "run"
    assert events[1]["data"]["error"].startswith("TypeError")


def test_executor_emits_result_for_a_successful_call(vault, monkeypatch):
    _add_tool(vault)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[2, 3], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}

    events = _exec_events(_state(current_sub_task=sub_task))

    assert [e["type"] for e in events] == ["call.args", "call.result"]
    assert events[1]["data"] == {"repr": "5", "type": "int", "small": True}


def test_executor_emits_vault_failure_with_streak_and_prune(vault, monkeypatch):
    _add_tool(vault, body="raise ValueError('kaboom')")
    _patch_resolver(monkeypatch, ResolvedArgs(args=[1, 2], kwargs={}))
    sub_task = {"id": 1, "needs": "vault", "tool_hint": "add", "action": "add"}

    first = _exec_events(_state(current_sub_task=sub_task), {"configurable": {"thread_id": "f1"}})
    second = _exec_events(_state(current_sub_task=sub_task), {"configurable": {"thread_id": "f2"}})

    assert first[-1] == {
        "type": "vault.failure",
        "data": {"tool": "add", "streak": 1, "pruned": False, "error": "ValueError: kaboom"},
    }
    assert second[-1]["data"]["streak"] == 2
    assert second[-1]["data"]["pruned"] is True


def test_executor_emits_call_error_when_dispatch_fails(vault, monkeypatch):
    sub_task = {"id": 1, "needs": "primitive", "tool_hint": "nope", "action": "x"}
    events = _exec_events(_state(current_sub_task=sub_task))
    assert events == [
        {
            "type": "call.error",
            "data": {"error": "dispatch error: Unknown primitive: 'nope'", "when": "dispatch"},
        }
    ]


def test_executor_emits_only_approved_args_after_resume(vault, monkeypatch):
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print('shown')"}))
    monkeypatch.setitem(exec_mod.PRIMITIVES, "python_exec", lambda code: "ok")
    config = {"configurable": {"thread_id": "approve-events"}}
    app = _exec_graph()

    paused = list(app.stream(_exec_state(), config=config, stream_mode="custom"))
    assert paused == []  # nothing emitted before approval

    from langgraph.types import Command

    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print('drifted')"}))
    resume = {"approved": True, "args": [], "kwargs": {"code": "print('shown')"}}
    events = list(app.stream(Command(resume=resume), config=config, stream_mode="custom"))

    assert events[0]["data"]["args"] == [["code", "\"print('shown')\"", False]]
    assert events[1]["type"] == "call.result"


def test_executor_emits_declined(vault, monkeypatch):
    monkeypatch.delenv("TALOS_AUTO_APPROVE_EXEC", raising=False)
    _patch_resolver(monkeypatch, ResolvedArgs(args=[], kwargs={"code": "print(1)"}))
    events = _exec_events(
        _exec_state(), {"configurable": {"thread_id": "decline-events"}}, {"approved": False}
    )
    assert events == [
        {"type": "call.error", "data": {"error": "declined by user", "when": "declined"}}
    ]


@pytest.mark.parametrize(
    ("declared", "value", "expected"),
    [
        ("int", 3, False),
        ("int", "three", True),
        ("int", True, True),
        ("float", 3, False),
        ("bool", True, False),
        ("str", 3, True),
        ("list[str]", ["a"], False),
        ("list[str]", "a", True),
        ("int | None", None, False),
        ("int | None", "x", True),
        ("dict", {}, False),
        ("Any", object(), False),
        ("MyThing", 1, False),
        (None, 1, False),
        ("", 1, False),
    ],
)
def test_is_suspicious(declared, value, expected):
    assert exec_mod.is_suspicious(declared, value) is expected


def test_describe_result_marks_long_output_as_not_small_and_caps_it():
    assert exec_mod.describe_result("x" * 100)["small"] is False
    assert exec_mod.describe_result("a\nb")["small"] is True  # repr escapes the newline
    big = exec_mod.describe_result(list(range(1000)))["repr"]
    assert big.endswith("…") and len(big) == 2000
