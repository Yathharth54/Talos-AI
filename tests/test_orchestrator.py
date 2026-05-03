"""Phase 7 — end-to-end multi-step tests.

We monkeypatch the LLM factories at the seams so the entire graph runs
without hitting OpenAI:
- planner._make_llm        → returns canned Plan
- forger._make_llm         → returns canned ForgedTool sequence
- executor._make_resolver_llm → returns canned ResolvedArgs
- orchestrator._make_llm   → returns canned final response (AIMessage-shaped)

Vault is pointed at tmp_path so each test has a clean slate.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from talos.agents import executor as exec_mod
from talos.agents import forger as forger_mod
from talos.agents import learner as learner_mod
from talos.agents import orchestrator as orch_mod
from talos.agents import planner as planner_mod
from talos.agents.executor import ResolvedArgs
from talos.agents.forger import ForgedTool
from talos.agents.planner import Plan, SubTask
from talos.graph import build_graph
from talos.vault.manager import SkillManager


# ---- fakes ----------------------------------------------------------------

class _FakeStructured:
    def __init__(self, items: list) -> None:
        self._items = list(items)

    def invoke(self, _messages):
        if not self._items:
            raise RuntimeError("FakeStructured exhausted")
        return self._items.pop(0)


class _FakeChat:
    """Mimics ChatOpenAI for orchestrator_out — returns an AIMessage-ish object."""

    def __init__(self, content: str = "ok") -> None:
        self._content = content

    def invoke(self, _messages):
        class _Msg:
            content = self._content
        return _Msg()


# ---- fixtures -------------------------------------------------------------

@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch) -> SkillManager:
    mgr = SkillManager(vault_dir=tmp_path)
    # Point every module that constructs a SkillManager at this one.
    monkeypatch.setattr(planner_mod, "_get_skill_manager", lambda: mgr)
    monkeypatch.setattr(exec_mod, "_get_skill_manager", lambda: mgr)
    monkeypatch.setattr(learner_mod, "_get_skill_manager", lambda: mgr)
    return mgr


def _patch_orchestrator_llm(monkeypatch, response: str = "done"):
    chat = _FakeChat(response)
    monkeypatch.setattr(orch_mod, "_make_llm", lambda: chat)


# IMPORTANT: every helper below SHARES one fake across all factory invocations.
# The graph calls e.g. `_make_resolver_llm()` once per sub-task, so each call
# must keep popping from the SAME list — otherwise every sub-task gets the
# first canned response and later items are never seen.

def _patch_planner(monkeypatch, plan: Plan):
    fake = _FakeStructured([plan])
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)


def _patch_forger(monkeypatch, tools: list[ForgedTool]):
    fake = _FakeStructured(tools)
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake)


def _patch_resolver(monkeypatch, resolved: list[ResolvedArgs]):
    fake = _FakeStructured(resolved)
    monkeypatch.setattr(exec_mod, "_make_resolver_llm", lambda: fake)


def _state(query: str) -> dict:
    return {"messages": [HumanMessage(content=query)]}


def _good_reverse_string() -> ForgedTool:
    return ForgedTool(
        name="reverse_string",
        description="Reverse a string",
        keywords=["reverse", "string"],
        signature="reverse_string(s: str) -> str",
        code="def reverse_string(s: str) -> str:\n    return s[::-1]\n",
        test_code=(
            "def test_basic():\n    assert reverse_string('abc') == 'cba'\n\n"
            "def test_empty():\n    assert reverse_string('') == ''\n\n"
            "def test_x():\n    assert reverse_string('x') == 'x'\n"
        ),
    )


# ---- end-to-end tests -----------------------------------------------------

def test_e2e_single_primitive_subtask(tmp_vault, monkeypatch, tmp_path: Path):
    """One sub-task, primitive only. No vault, no forging."""
    target = tmp_path / "out.txt"
    plan = Plan(sub_tasks=[
        SubTask(id=1, action="write file", needs="primitive",
                tool_hint="file_write",
                keywords=["write"], input_description="literal",
                depends_on=[]),
    ])
    _patch_planner(monkeypatch, plan)
    _patch_resolver(monkeypatch, [ResolvedArgs(args=[str(target), "hello"], kwargs={})])
    _patch_orchestrator_llm(monkeypatch, "wrote the file")

    app = build_graph().compile()
    final = app.invoke(_state(f"write hello to {target}"))

    assert target.read_text() == "hello"
    assert final["sub_task_results"][0]["ok"] is True
    assert any(getattr(m, "content", "") == "wrote the file"
               for m in final["messages"])


def test_e2e_two_primitive_subtasks(tmp_vault, monkeypatch, tmp_path: Path):
    """Two sub-tasks in sequence, both primitives. Results accumulate."""
    target = tmp_path / "out.txt"
    plan = Plan(sub_tasks=[
        SubTask(id=1, action="write file", needs="primitive",
                tool_hint="file_write",
                keywords=["write"], input_description="literal",
                depends_on=[]),
        SubTask(id=2, action="read file", needs="primitive",
                tool_hint="file_read",
                keywords=["read"], input_description="output of 1",
                depends_on=[1]),
    ])
    _patch_planner(monkeypatch, plan)
    _patch_resolver(monkeypatch, [
        ResolvedArgs(args=[str(target), "talos"], kwargs={}),
        ResolvedArgs(args=[str(target)], kwargs={}),
    ])
    _patch_orchestrator_llm(monkeypatch, "done")

    app = build_graph().compile()
    final = app.invoke(_state("write talos and read back"))

    assert len(final["sub_task_results"]) == 2
    assert all(r["ok"] for r in final["sub_task_results"])
    assert final["sub_task_results"][1]["output"] == "talos"


def test_e2e_forge_then_execute(tmp_vault, monkeypatch):
    """Single forge sub-task: forge → test passes → learn → execute."""
    plan = Plan(sub_tasks=[
        SubTask(id=1, action="reverse a string", needs="forge",
                keywords=["reverse"], input_description="literal string",
                depends_on=[]),
    ])
    _patch_planner(monkeypatch, plan)
    _patch_forger(monkeypatch, [_good_reverse_string()])
    _patch_resolver(monkeypatch, [ResolvedArgs(args=["hello"], kwargs={})])
    _patch_orchestrator_llm(monkeypatch, "reversed it")

    app = build_graph().compile()
    final = app.invoke(_state("reverse 'hello'"))

    # Vault grew by one
    names = [e["name"] for e in tmp_vault.all()]
    assert "reverse_string" in names
    # Tool ran successfully
    assert final["sub_task_results"][0]["output"] == "olleh"


def test_e2e_forge_then_vault_reuse(tmp_vault, monkeypatch):
    """Two sub-tasks: forge first (registers tool), then re-use as vault."""
    plan = Plan(sub_tasks=[
        SubTask(id=1, action="reverse 'foo'", needs="forge",
                keywords=["reverse"], input_description="literal",
                depends_on=[]),
        SubTask(id=2, action="reverse 'bar' too", needs="vault",
                tool_hint="reverse_string",
                keywords=["reverse"], input_description="literal",
                depends_on=[]),
    ])
    _patch_planner(monkeypatch, plan)
    _patch_forger(monkeypatch, [_good_reverse_string()])
    _patch_resolver(monkeypatch, [
        ResolvedArgs(args=["foo"], kwargs={}),
        ResolvedArgs(args=["bar"], kwargs={}),
    ])
    _patch_orchestrator_llm(monkeypatch, "done")

    app = build_graph().compile()
    final = app.invoke(_state("reverse foo and bar"))

    assert final["sub_task_results"][0]["output"] == "oof"
    assert final["sub_task_results"][1]["output"] == "rab"
    # Usage counter bumped on the second (vault) call
    entry = next(e for e in tmp_vault.all() if e["name"] == "reverse_string")
    assert entry["usage_count"] >= 1


def test_e2e_forge_fails_graph_terminates(tmp_vault, monkeypatch):
    """Forger emits broken code 3 times in a row; graph still terminates."""
    broken = ForgedTool(
        name="reverse_string",
        description="broken",
        keywords=["reverse"],
        signature="reverse_string(s: str) -> str",
        code="def reverse_string(s):\n    return s\n",  # no-op (wrong)
        test_code="def test_x():\n    assert reverse_string('a') == 'A'\n",  # always fails
    )
    plan = Plan(sub_tasks=[
        SubTask(id=1, action="reverse a string", needs="forge",
                keywords=["reverse"], input_description="literal",
                depends_on=[]),
    ])
    _patch_planner(monkeypatch, plan)
    _patch_forger(monkeypatch, [broken, broken, broken])
    _patch_resolver(monkeypatch, [])  # never reached — execute won't run
    _patch_orchestrator_llm(monkeypatch, "couldn't forge it")

    app = build_graph().compile()
    final = app.invoke(_state("reverse 'a'"))

    # Forge failed → no learn → no execute → no sub_task_results.
    assert final["test_result"]["passed"] is False
    assert tmp_vault.all() == []
    # The graph still terminated and emitted a final message.
    assert any(getattr(m, "content", "") for m in final["messages"])


def test_e2e_conversational_query_short_circuits(tmp_vault, monkeypatch):
    """Empty plan (conversational query) → straight to respond."""
    _patch_planner(monkeypatch, Plan(sub_tasks=[]))
    _patch_orchestrator_llm(monkeypatch, "Hi! How can I help?")

    app = build_graph().compile()
    final = app.invoke(_state("hi"))

    assert final["sub_task_results"] == []
    assert any(getattr(m, "content", "") == "Hi! How can I help?"
               for m in final["messages"])


def test_e2e_multi_turn_history_accumulates(tmp_vault, monkeypatch):
    """Phase 7.5: same thread_id over two turns -> messages accumulate via
    the checkpointer. The planner of turn 2 sees turn 1 in its prompt."""
    from langgraph.checkpoint.memory import MemorySaver

    captured_user_messages: list[str] = []

    class _CapturingPlanner:
        def __init__(self):
            self._plans = [Plan(sub_tasks=[]), Plan(sub_tasks=[])]

        def invoke(self, messages):
            captured_user_messages.append(messages[1].content)
            return self._plans.pop(0)

    fake_planner = _CapturingPlanner()
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake_planner)

    # Two consecutive responses for orchestrator_out
    chats = iter([_FakeChat("It's 28°C."), _FakeChat("It's average.")])
    monkeypatch.setattr(orch_mod, "_make_llm", lambda: next(chats))

    app = build_graph().compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    app.invoke(_state("temp in mumbai?"), config=config)
    app.invoke(_state("is that high?"), config=config)

    # Turn 2's planner prompt must contain turn 1's user msg + assistant reply.
    second_prompt = captured_user_messages[1]
    assert "temp in mumbai?" in second_prompt
    assert "28°C" in second_prompt


# ---- live -----------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1",
    reason="Set RUN_LIVE=1 to run the full pipeline against real OpenAI.",
)
def test_e2e_live_read_url_and_write_file(tmp_vault, tmp_path):
    """Real end-to-end: read example.com, write body to a file."""
    target = tmp_path / "talos_e2e.txt"
    app = build_graph().compile()
    final = app.invoke(_state(
        f"Read https://example.com and save the body to {target}"
    ))
    assert target.exists(), final.get("sub_task_results")
    assert "Example Domain" in target.read_text()
