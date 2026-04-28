"""Phase 4 — Forger + forge sub-graph tests.

Strategy:
- Default tests use a fake LLM (monkeypatched factory) so no API key is
  needed and CI is free.
- ONE end-to-end live test, gated by `RUN_LIVE=1`, exercises the real
  OpenAI path. Run manually when validating the actual prompt.

LangChain testing pattern:
- We don't try to mock OpenAI at the HTTP level. Instead we replace
  `_make_llm()` (the factory in talos.agents.forger) with a fake
  callable that has an `.invoke()` method returning a canned ForgedTool.
- This is exactly how LangChain itself recommends testing structured-output
  agents — substitute the LLM client at the seam.
"""

from __future__ import annotations

import os

import pytest

from talos.agents import forger as forger_mod
from talos.agents.forge_subgraph import build_forge_subgraph
from talos.agents.forger import ForgedTool, forger_node


# ---- helpers ---------------------------------------------------------------

class _FakeLLM:
    """Stand-in for ChatOpenAI.with_structured_output(...).

    Holds a list of canned ForgedTool responses; each `.invoke()` pops one.
    Records the messages it received so tests can assert on prompt shape.
    """

    def __init__(self, responses: list[ForgedTool]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages):  # signature mimics LangChain Runnable
        self.calls.append(messages)
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _good_tool() -> ForgedTool:
    return ForgedTool(
        name="reverse_string",
        description="Reverse a string",
        keywords=["reverse", "string"],
        signature="reverse_string(s: str) -> str",
        code="def reverse_string(s: str) -> str:\n    return s[::-1]\n",
        test_code=(
            "def test_basic():\n    assert reverse_string('abc') == 'cba'\n\n"
            "def test_empty():\n    assert reverse_string('') == ''\n\n"
            "def test_unicode():\n    assert reverse_string('héllo') == 'olléh'\n"
        ),
    )


def _broken_tool() -> ForgedTool:
    # Off-by-one bug — tests will fail.
    return ForgedTool(
        name="reverse_string",
        description="Reverse a string (broken)",
        keywords=["reverse", "string"],
        signature="reverse_string(s: str) -> str",
        code="def reverse_string(s: str) -> str:\n    return s\n",
        test_code=(
            "def test_basic():\n    assert reverse_string('abc') == 'cba'\n\n"
            "def test_empty():\n    assert reverse_string('') == ''\n\n"
            "def test_other():\n    assert reverse_string('xy') == 'yx'\n"
        ),
    )


# ---- forger_node unit tests ------------------------------------------------

def test_forger_node_first_attempt(monkeypatch):
    fake = _FakeLLM([_good_tool()])
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake)

    out = forger_node({"current_sub_task": {"action": "reverse a string"}})  # type: ignore[arg-type]

    assert out["retry_count"] == 1
    assert out["forged_tool"]["name"] == "reverse_string"
    assert "s[::-1]" in out["forged_tool"]["code"]
    # First attempt: no retry context, just system + user message.
    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == 2  # SystemMessage + HumanMessage


def test_forger_node_retry_includes_previous_attempt(monkeypatch):
    fake = _FakeLLM([_good_tool()])
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake)

    out = forger_node({  # type: ignore[arg-type]
        "current_sub_task": {"action": "reverse a string"},
        "retry_count": 1,
        "forged_tool": _broken_tool().model_dump(),
        "test_result": {
            "passed": False,
            "stderr": "AssertionError",
            "error": "test_basic: AssertionError",
            "timed_out": False,
        },
    })

    assert out["retry_count"] == 2
    user_msg = fake.calls[0][1].content
    assert "previous attempt" in user_msg.lower()
    assert "AssertionError" in user_msg


# ---- forge sub-graph integration (mocked LLM) ------------------------------

def test_forge_subgraph_succeeds_first_try(monkeypatch):
    fake = _FakeLLM([_good_tool()])
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake)

    app = build_forge_subgraph().compile()
    final = app.invoke({"current_sub_task": {"action": "reverse a string"}})

    assert final["test_result"]["passed"] is True
    assert final["retry_count"] == 1
    assert final["forged_tool"]["name"] == "reverse_string"


def test_forge_subgraph_recovers_on_second_try(monkeypatch):
    # First attempt broken, second attempt good.
    fake = _FakeLLM([_broken_tool(), _good_tool()])
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake)

    app = build_forge_subgraph().compile()
    final = app.invoke({"current_sub_task": {"action": "reverse a string"}})

    assert final["test_result"]["passed"] is True
    assert final["retry_count"] == 2
    assert "s[::-1]" in final["forged_tool"]["code"]
    # Second forger call should have seen the failure context.
    assert len(fake.calls) == 2
    assert "previous attempt" in fake.calls[1][1].content.lower()


def test_forge_subgraph_exhausts_retries(monkeypatch):
    # All 3 attempts broken — should give up cleanly with passed=False.
    fake = _FakeLLM([_broken_tool(), _broken_tool(), _broken_tool()])
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake)

    app = build_forge_subgraph().compile()
    final = app.invoke({"current_sub_task": {"action": "reverse a string"}})

    assert final["test_result"]["passed"] is False
    assert final["retry_count"] == 3
    assert len(fake.calls) == 3


# ---- live OpenAI test (gated) -----------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1",
    reason="Set RUN_LIVE=1 to exercise the real OpenAI path (costs $).",
)
def test_forge_live_reverse_string():
    """End-to-end forge against real OpenAI. Asserts the forged code passes
    its own tests — does NOT pin the exact code, since LLMs vary."""
    app = build_forge_subgraph().compile()
    final = app.invoke({"current_sub_task": {"action": "Write a function that reverses a string."}})
    assert final["test_result"]["passed"] is True, final["test_result"].get("error")
    assert "def " in final["forged_tool"]["code"]
