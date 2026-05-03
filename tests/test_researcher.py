"""Phase 8 — Researcher tests.

Mock the ReAct agent factory so we don't burn API tokens. The live test
is gated.
"""

from __future__ import annotations

import os

import pytest

from talos.agents import forger as forger_mod
from talos.agents import researcher as research_mod
from talos.agents.forger import ForgedTool, forger_node


# ---- should_research heuristic --------------------------------------------

def test_should_research_triggers_on_api_keywords():
    assert research_mod.should_research("call the OpenWeather API")
    assert research_mod.should_research("scrape https://example.com")
    assert research_mod.should_research("get current weather in mumbai")
    assert research_mod.should_research("fetch from a github endpoint")


def test_should_research_skips_pure_python_tasks():
    assert not research_mod.should_research("reverse a string")
    assert not research_mod.should_research("compute factorial")
    assert not research_mod.should_research("merge two dicts")


# ---- research() utility ---------------------------------------------------

def test_research_uses_react_agent(monkeypatch):
    """research() should construct an agent and return its final message."""

    class _FakeAgent:
        def invoke(self, _input, config=None):
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="open-meteo.com works keyless")]}

    monkeypatch.setattr(research_mod, "_make_react_agent", lambda: _FakeAgent())
    out = research_mod.research("how do I get weather data")
    assert "open-meteo" in out


def test_research_handles_empty_response(monkeypatch):
    class _FakeAgent:
        def invoke(self, _input, config=None):
            return {"messages": []}

    monkeypatch.setattr(research_mod, "_make_react_agent", lambda: _FakeAgent())
    out = research_mod.research("anything")
    assert out == ""


# ---- forger × researcher integration -------------------------------------

class _FakeLLM:
    def __init__(self, tool: ForgedTool) -> None:
        self.tool = tool
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.tool


def _good_tool() -> ForgedTool:
    return ForgedTool(
        name="get_weather",
        description="get weather",
        keywords=["weather"],
        signature="get_weather(city: str) -> dict",
        code="def get_weather(city: str) -> dict:\n    return {}\n",
        test_code="def test_basic():\n    assert isinstance(get_weather('x'), dict)\n",
    )


def test_forger_calls_research_on_api_task(monkeypatch):
    """Task mentions 'API' → research() runs → notes appear in user message."""
    fake_llm = _FakeLLM(_good_tool())
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake_llm)
    monkeypatch.setattr(forger_mod, "research", lambda q: "FAKE-RESEARCH-NOTES")
    monkeypatch.setattr(forger_mod, "should_research", lambda t: True)

    forger_node({"current_sub_task": {"action": "call the weather API for mumbai"}})

    user_msg = fake_llm.calls[0][1].content
    assert "FAKE-RESEARCH-NOTES" in user_msg
    assert "Research notes" in user_msg


def test_forger_skips_research_for_pure_python(monkeypatch):
    fake_llm = _FakeLLM(_good_tool())
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake_llm)
    research_called = []
    monkeypatch.setattr(forger_mod, "research", lambda q: research_called.append(q) or "X")
    monkeypatch.setattr(forger_mod, "should_research", lambda t: False)

    forger_node({"current_sub_task": {"action": "reverse a string"}})
    assert research_called == []


def test_forger_skips_research_on_retry(monkeypatch):
    """Retries don't re-research — the error trace is enough context."""
    fake_llm = _FakeLLM(_good_tool())
    monkeypatch.setattr(forger_mod, "_make_llm", lambda: fake_llm)
    research_called = []
    monkeypatch.setattr(forger_mod, "research", lambda q: research_called.append(q) or "X")
    monkeypatch.setattr(forger_mod, "should_research", lambda t: True)

    state = {
        "current_sub_task": {"action": "call the weather API"},
        "retry_count": 1,
        "forged_tool": {"code": "def x(): pass", "test_code": "def test_x(): pass"},
        "test_result": {"passed": False, "stderr": "boom"},
    }
    forger_node(state)
    assert research_called == []  # no research on retry


# ---- live ----------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1",
    reason="Set RUN_LIVE=1 to run the real Researcher (multiple LLM + Tavily/Jina calls).",
)
def test_research_live_finds_free_weather_api():
    """The Researcher should mention a free weather API for Mumbai."""
    out = research_mod.research(
        "What is a free, no-auth weather API I can call to get current temperature in Mumbai? "
        "Give me the URL pattern and the key field for temperature."
    )
    assert out
    text = out.lower()
    # We expect open-meteo or similar free API to surface.
    assert any(kw in text for kw in ["open-meteo", "openweathermap", "wttr.in", "weather"])
