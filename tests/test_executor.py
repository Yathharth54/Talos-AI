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
        {"name": "boom", "description": "raises", "keywords": ["err"],
         "function": "boom", "signature": "boom() -> None"},
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
    _patch_resolver(monkeypatch, ResolvedArgs(
        args=[str(target), "__SUBTASK_OUTPUT_1__"],
        kwargs={},
    ))
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
    _patch_resolver(monkeypatch, ResolvedArgs(
        args=[str(target), "Result was: __SUBTASK_OUTPUT_1__"],
        kwargs={},
    ))
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
    _patch_resolver(monkeypatch, ResolvedArgs(
        args=[str(target), '__SUBTASK_OUTPUT_1__[0]'],
        kwargs={},
    ))
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
    captured: list = []
    vault.register(
        {"name": "echo", "description": "echo", "keywords": ["echo"],
         "function": "echo", "signature": "echo(x) -> str"},
        "def echo(x):\n    return x\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(args=['__SUBTASK_OUTPUT_1__["url"]'], kwargs={}))
    sub_task = {"id": 2, "needs": "vault", "tool_hint": "echo", "action": "x"}
    state = _state(
        "extract",
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True,
                           "output": {"url": "https://x.com", "title": "X"}}],
    )
    out = executor_node(state)
    assert out["sub_task_results"][1]["output"] == "https://x.com"


def test_substitute_chained_accessors(vault, monkeypatch):
    """`__SUBTASK_OUTPUT_1__[0]["url"]` walks list-of-dicts."""
    vault.register(
        {"name": "echo", "description": "echo", "keywords": ["echo"],
         "function": "echo", "signature": "echo(x) -> str"},
        "def echo(x):\n    return x\n",
    )
    _patch_resolver(monkeypatch, ResolvedArgs(
        args=['__SUBTASK_OUTPUT_1__[0]["url"]'], kwargs={}))
    sub_task = {"id": 2, "needs": "vault", "tool_hint": "echo", "action": "x"}
    state = _state(
        "first url",
        current_sub_task=sub_task,
        sub_task_results=[{"sub_task_id": 1, "ok": True, "output": [
            {"url": "https://a.com"}, {"url": "https://b.com"}
        ]}],
    )
    out = executor_node(state)
    assert out["sub_task_results"][1]["output"] == "https://a.com"


def test_substitute_preserves_type_for_dict_args(vault, monkeypatch):
    """If a prior output is a dict and the resolver puts a placeholder in a
    kwarg, the actual dict (not its str repr) reaches the tool."""
    received: list = []
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
        "input_description": "the path is mentioned in the user query; the content is the literal string 'hello world'",
        "depends_on": [],
    }
    out = executor_node(_state(
        f"please write 'hello world' to {target}",
        current_sub_task=sub_task,
    ))
    assert out["sub_task_results"][0]["ok"] is True
    assert os.path.exists(target)
    assert "hello world" in open(target).read()
    os.unlink(target)
