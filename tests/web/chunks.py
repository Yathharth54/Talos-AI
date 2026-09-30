"""Recorded astream chunks for the translator tests.

There are no model keys in CI, so "recorded from real runs" means: the real
compiled Talos graph, driven with the same LLM fakes as
tests/test_orchestrator.py (canned Plan / ForgedTool / ResolvedArgs, and a
streaming fake chat model for the answer), streamed with the web app's
exact `astream` arguments. Every node, the tester subprocess, the smoke
gate, the vault and the checkpointer are real.

Regenerate the JSON after a LangGraph upgrade:

    uv run python -m tests.web.chunks

`test_translator.py::test_recorded_fixtures_match_a_live_capture` fails
when the stored fixtures drift from what the installed LangGraph emits.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    message_to_dict,
    messages_from_dict,
)
from langgraph.types import Command, Interrupt

from talos.agents import executor as exec_mod
from talos.agents import forger as forger_mod
from talos.agents import hitl as hitl_mod
from talos.agents import learner as learner_mod
from talos.agents import orchestrator as orch_mod
from talos.agents import planner as planner_mod
from talos.agents.executor import ResolvedArgs
from talos.agents.forger import ForgedTool
from talos.agents.planner import Plan, SubTask
from talos.graph import build_app
from talos.vault.manager import SkillManager
from talos.web.demo_sources import CAESAR, CAESAR_BAD_SOURCE, CAESAR_SOURCE, WEATHER, WEATHER_SOURCE
from talos.web.translator import STREAM_MODES

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIOS = ("forge_retry", "vault", "chat", "exec_pause", "exec_approve", "key_pause", "key_skip")

CAESAR_TESTS = """def test_encrypt_shifts_forward():
    assert caesar_cipher("TALOS AGENT", 7, "encrypt") == "AHSVZ HNLUA"


def test_decrypt_reverses_encrypt():
    result = caesar_cipher("AHSVZ HNLUA", 7, "decrypt")
    assert result == "TALOS AGENT", f"{result!r} != 'TALOS AGENT'"


def test_preserves_case_and_spaces():
    assert caesar_cipher("Hi there", 1, "encrypt") == "Ij uifsf"


def test_wraps_past_z():
    assert caesar_cipher("xyz", 3, "encrypt") == "abc"


def test_rejects_unknown_mode():
    try:
        caesar_cipher("a", 1, "rot")
    except ValueError:
        return
    raise AssertionError("no ValueError")
"""

WEATHER_TESTS = """def test_reads_temperature_from_response():
    import os

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"main": {"temp": 31.5}}

    os.environ["OPENWEATHERMAP_API_KEY"] = "test"
    requests.get = lambda *a, **k: _Resp()
    assert get_current_temperature("Mumbai") == 31.5


def test_raises_when_key_missing():
    import os

    os.environ.pop("OPENWEATHERMAP_API_KEY", None)
    try:
        get_current_temperature("Mumbai")
    except RuntimeError:
        return
    raise AssertionError("no RuntimeError")


def test_raises_on_unknown_city():
    import os

    class _Resp:
        status_code = 404

    os.environ["OPENWEATHERMAP_API_KEY"] = "test"
    requests.get = lambda *a, **k: _Resp()
    try:
        get_current_temperature("Nowhere")
    except ValueError:
        return
    raise AssertionError("no ValueError")
"""


class _Canned:
    """A structured-output model that returns canned objects in order."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def invoke(self, _messages: Any) -> Any:
        return self._items.pop(0)


def _forged(name: str, code: str, tests: str, signature: str, env: list[str] | None = None):
    return ForgedTool(
        name=name,
        description="d",
        keywords=[name],
        signature=signature,
        code=code + "\n",
        test_code=tests,
        needs_env_vars=env or [],
    )


def _caesar_signature() -> str:
    return f"{CAESAR['name']}({CAESAR['args']}) -> {CAESAR['ret']}"


@contextmanager
def scenario_env(name: str) -> Iterator[dict[str, Any]]:
    """Patch the LLM seams and the vault for one scenario.

    Yields:
        `{"inputs": [graph input, ...], "vault": SkillManager}`. Inputs after
        the first are resume Commands on the same thread.
    """
    saved: dict[tuple[Any, str], Any] = {}

    def patch(module: Any, attr: str, value: Any) -> None:
        saved[(module, attr)] = getattr(module, attr)
        setattr(module, attr, value)

    old_key = os.environ.pop(WEATHER["env"], None)
    with tempfile.TemporaryDirectory(prefix="talos_chunks_") as tmp:
        vault = SkillManager(vault_dir=Path(tmp) / "vault")
        for module in (planner_mod, exec_mod, learner_mod):
            patch(module, "_get_skill_manager", lambda: vault)
        patch(forger_mod, "should_research", lambda _task: False)
        patch(hitl_mod, "DOTENV_PATH", Path(tmp) / ".env")
        answers = {
            "forge_retry": '"TALOS AGENT" encrypted with a shift of 7 is AHSVZ HNLUA.',
            "vault": "It decrypts to TALOS AGENT.",
            "chat": "I plan, then forge tools.",
            "exec_pause": "The code prints 5050.",
            "exec_approve": "The code prints 5050.",
            "key_pause": "I couldn't get the temperature.",
            "key_skip": "I couldn't get the temperature.",
        }
        chat = GenericFakeChatModel(messages=iter([AIMessage(content=answers[name])]))
        patch(orch_mod, "_make_llm", lambda: chat)
        inputs: list[Any] = []
        query = {
            "forge_retry": 'Encrypt "TALOS AGENT" with a shift of 7.',
            "vault": 'Decrypt "AHSVZ HNLUA" with shift 7',
            "chat": "What can you do?",
            "exec_pause": "Run this Python code: print(sum(range(1, 101)))",
            "exec_approve": "Run this Python code: print(sum(range(1, 101)))",
            "key_pause": "Get the current temperature in Mumbai.",
            "key_skip": "Get the current temperature in Mumbai.",
        }[name]
        inputs.append({"messages": [HumanMessage(content=query)]})

        if name == "forge_retry":
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Encrypt text with a Caesar cipher",
                        needs="forge",
                        keywords=["caesar", "cipher", "encrypt"],
                        input_description="the quoted text, shift 7, encrypt",
                        input_schema={"text": "str", "shift": "int", "mode": "str"},
                        output_schema="str",
                        param_bindings={"text": "TALOS AGENT", "shift": 7, "mode": "encrypt"},
                    )
                ]
            )
            forger = _Canned(
                [
                    _forged("caesar_cipher", CAESAR_BAD_SOURCE, CAESAR_TESTS, _caesar_signature()),
                    _forged("caesar_cipher", CAESAR_SOURCE, CAESAR_TESTS, _caesar_signature()),
                ]
            )
            patch(forger_mod, "_make_llm", lambda: forger)
        elif name == "vault":
            vault.register(
                {
                    "name": "caesar_cipher",
                    "function": "caesar_cipher",
                    "description": CAESAR["description"],
                    "keywords": CAESAR["keywords"],
                    "signature": _caesar_signature(),
                    "created_at": "2026-09-30T10:00:00+00:00",
                },
                CAESAR_SOURCE + "\n",
            )
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Decrypt with the Caesar cipher tool",
                        needs="vault",
                        tool_hint="caesar_cipher",
                        keywords=["caesar", "cipher", "decrypt"],
                        input_description="quoted text, shift 7, decrypt",
                    )
                ]
            )
            resolver = _Canned(
                [
                    ResolvedArgs(
                        args=[], kwargs={"text": "AHSVZ HNLUA", "shift": 7, "mode": "decrypt"}
                    )
                ]
            )
            patch(exec_mod, "_make_resolver_llm", lambda: resolver)
        elif name == "chat":
            plan = Plan(sub_tasks=[])
        elif name in ("exec_pause", "exec_approve"):
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Run the Python code",
                        needs="primitive",
                        tool_hint="python_exec",
                        keywords=["python"],
                        input_description="the code after the colon",
                    )
                ]
            )
            code = "print(sum(range(1, 101)))"
            resolver = _Canned([ResolvedArgs(args=[], kwargs={"code": code})] * 2)
            patch(exec_mod, "_make_resolver_llm", lambda: resolver)
            if name == "exec_approve":
                inputs.append(
                    Command(resume={"approved": True, "args": [], "kwargs": {"code": code}})
                )
        else:  # key_pause, key_skip
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        id=1,
                        action="Get the current temperature for a city from OpenWeatherMap",
                        needs="forge",
                        keywords=["weather", "temperature"],
                        input_description="the city",
                        input_schema={"city": "str"},
                        output_schema="float",
                        param_bindings={"city": "Mumbai"},
                    )
                ]
            )
            forger = _Canned(
                [
                    _forged(
                        WEATHER["name"],
                        WEATHER_SOURCE,
                        WEATHER_TESTS,
                        f"{WEATHER['name']}({WEATHER['args']}) -> {WEATHER['ret']}",
                        env=[WEATHER["env"]],
                    )
                ]
            )
            patch(forger_mod, "_make_llm", lambda: forger)
            if name == "key_skip":
                inputs.append(Command(resume="skip"))

        planner = _Canned([plan])
        patch(planner_mod, "_make_llm", lambda: planner)
        try:
            yield {"inputs": inputs, "vault": vault}
        finally:
            for (module, attr), value in saved.items():
                setattr(module, attr, value)
            os.environ.pop(WEATHER["env"], None)
            if old_key is not None:
                os.environ[WEATHER["env"]] = old_key


async def capture(name: str) -> list[list[Any]]:
    """Run one scenario on the real graph and return its chunks (last input only
    for resume scenarios: `exec_approve` and `key_skip` are the post-resume half)."""
    with scenario_env(name) as env:
        app = build_app()
        config = {"configurable": {"thread_id": f"capture-{name}"}}
        chunks: list[list[Any]] = []
        for graph_input in env["inputs"]:
            chunks = []
            async for ns, mode, data in app.astream(
                graph_input, config, stream_mode=STREAM_MODES, subgraphs=True
            ):
                chunks.append([list(ns), mode, _slim(mode, data)])
        return chunks


def _slim(mode: str, data: Any) -> Any:
    """Keep what the translator reads; drop task inputs/results (whole state copies)."""
    if mode == "tasks":
        keep = {"id", "name", "error", "interrupts", "triggers"}
        out = {k: v for k, v in data.items() if k in keep}
        if "input" in data:
            out["input"] = None
        return out
    return data


# ---- JSON round trip ----------------------------------------------------------------


def _encode(obj: Any) -> Any:
    if isinstance(obj, BaseMessage):
        return {"__message__": message_to_dict(obj)}
    if isinstance(obj, Interrupt):
        return {"__lg_interrupt__": {"value": obj.value, "id": obj.id}}
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=repr)
    return repr(obj)


def _decode(obj: dict[str, Any]) -> Any:
    if "__message__" in obj:
        return messages_from_dict([obj["__message__"]])[0]
    if "__lg_interrupt__" in obj:
        return Interrupt(value=obj["__lg_interrupt__"]["value"], id=obj["__lg_interrupt__"]["id"])
    return obj


def dumps(chunks: list[list[Any]]) -> str:
    return json.dumps(chunks, default=_encode, indent=1) + "\n"


def load(name: str) -> list[tuple[tuple[str, ...], str, Any]]:
    """Load a fixture as `(namespace, mode, data)` chunks with real message objects."""
    raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"), object_hook=_decode)
    out = []
    for ns, mode, data in raw:
        if mode == "messages":
            data = (data[0], data[1])
        elif mode == "updates" and "__interrupt__" in data:
            data = {"__interrupt__": tuple(data["__interrupt__"])}
        out.append((tuple(ns), mode, data))
    return out


_TASK_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def shape(chunks: list[Any]) -> list[tuple[Any, ...]]:
    """What must stay stable across captures: namespace kind, mode, and the keys."""
    out = []
    for ns, mode, data in chunks:
        where = tuple(_TASK_ID.sub("*", str(part)) for part in ns)
        if mode == "tasks":
            key: Any = (data.get("name"), "input" in data)
        elif mode == "custom":
            key = (data.get("type"), tuple(sorted(data.get("data", {}))))
        elif mode == "updates":
            key = tuple(sorted(data))
        else:
            key = (type(data[0]).__name__, data[1].get("langgraph_node"))
        out.append((where, mode, key))
    return out


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for name in SCENARIOS:
        chunks = asyncio.run(capture(name))
        (FIXTURES / f"{name}.json").write_text(dumps(chunks), encoding="utf-8")


if __name__ == "__main__":
    main()
