"""GraphDriver: the astream call it makes, and LangGraph's fresh-turn behaviour."""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from talos.agents import executor as exec_mod
from talos.agents import learner as learner_mod
from talos.agents import orchestrator as orch_mod
from talos.agents import planner as planner_mod
from talos.agents.executor import PRIMITIVES, ResolvedArgs
from talos.agents.planner import Plan, SubTask
from talos.graph import build_app
from talos.vault.manager import SkillManager
from talos.web.runner import GraphDriver, Pause, Resume, graph_signatures, signature_text
from tests.web import chunks


class StubGraph:
    """Replays fixture chunks and records how astream was called."""

    def __init__(self, *names: str) -> None:
        self.batches = [chunks.load(n) for n in names]
        self.calls: list[tuple] = []

    async def astream(self, graph_input, config, *, stream_mode, subgraphs):
        self.calls.append((graph_input, config, stream_mode, subgraphs))
        for chunk in self.batches.pop(0):
            yield chunk


async def collect(driver, state, **kwargs):
    return [item async for item in driver.run(state, **kwargs)]


async def test_graph_driver_streams_with_the_contract_arguments_and_pauses():
    graph = StubGraph("exec_pause", "exec_approve")
    driver = GraphDriver(graph)
    state = driver.initial_state()
    items = await collect(driver, state, query="run it", thread_id="session-1", resume=None)

    graph_input, config, modes, subgraphs = graph.calls[0]
    assert graph_input["messages"][0].content == "run it"
    assert config == {"configurable": {"thread_id": "session-1"}}
    assert (modes, subgraphs) == (["updates", "custom", "messages", "tasks"], True)
    assert isinstance(items[-1], Pause)
    assert items[-1].kind == "confirm_exec"
    assert state["approval"] == "waiting"

    value = {"approved": True, "args": [], "kwargs": {"code": "print(sum(range(1, 101)))"}}
    resume = Resume("confirm_exec", "approve", value)
    items = await collect(driver, state, query="run it", thread_id="session-1", resume=resume)
    command = graph.calls[1][0]
    assert isinstance(command, Command) and command.resume == value
    assert items[0] == ("log.pop", {})
    assert items[-1][0] == "run.finished"


def test_primitive_signatures_read_like_the_demo():
    assert signature_text(PRIMITIVES["python_exec"]) == (
        "python_exec(code: str, timeout: int | None = None) -> dict"
    )
    assert graph_signatures("primitive", "vault_list") == "vault_list() -> list[dict]"
    assert graph_signatures("forge", None) is None


class _Canned:
    def __init__(self, items):
        self.items = list(items)

    def invoke(self, _messages):
        return self.items.pop(0)


async def test_new_input_after_a_pause_starts_a_fresh_turn(monkeypatch, tmp_path: Path):
    """Spec 02 §6: a stopped (paused) run's thread must restart from START."""
    vault = SkillManager(vault_dir=tmp_path)
    for module in (planner_mod, exec_mod, learner_mod):
        monkeypatch.setattr(module, "_get_skill_manager", lambda: vault)
    exec_plan = Plan(
        sub_tasks=[
            SubTask(
                id=1,
                action="run code",
                needs="primitive",
                tool_hint="python_exec",
                keywords=["python"],
                input_description="code",
            )
        ]
    )
    planner = _Canned([exec_plan, Plan(sub_tasks=[])])
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: planner)
    resolver = _Canned([ResolvedArgs(args=[], kwargs={"code": "print(1)"})])
    monkeypatch.setattr(exec_mod, "_make_resolver_llm", lambda: resolver)
    chat = GenericFakeChatModel(messages=iter([AIMessage(content="Hi.")]))
    monkeypatch.setattr(orch_mod, "_make_llm", lambda: chat)

    app = build_app()
    config = {"configurable": {"thread_id": "fresh"}}
    first = [c async for c in app.astream(
        {"messages": [HumanMessage("run print(1)")]}, config, stream_mode="updates"
    )]  # fmt: skip
    assert "__interrupt__" in first[-1]
    assert (await app.aget_state(config)).next == ("executor",)

    second = [c async for c in app.astream(
        {"messages": [HumanMessage("hello")]}, config, stream_mode="updates"
    )]  # fmt: skip
    assert list(second[0]) == ["orchestrator_in"]
    assert list(second[-1]) == ["orchestrator_out"]
    state = await app.aget_state(config)
    assert state.next == () and not state.interrupts
