"""Phase 6 — Learn node tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from talos.agents import learner as learner_mod
from talos.agents.learner import learn_node
from talos.vault.manager import SkillManager


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> SkillManager:
    mgr = SkillManager(vault_dir=tmp_path)
    monkeypatch.setattr(learner_mod, "_get_skill_manager", lambda: mgr)
    return mgr


def _good_forged() -> dict:
    return {
        "name": "reverse_string",
        "description": "reverse a string",
        "keywords": ["reverse", "string"],
        "signature": "reverse_string(s: str) -> str",
        "code": "def reverse_string(s: str) -> str:\n    return s[::-1]\n",
        "test_code": "def test_basic():\n    assert reverse_string('a') == 'a'\n",
    }


def test_learn_registers_when_tests_passed(vault):
    state = {
        "forged_tool": _good_forged(),
        "test_result": {"passed": True},
    }
    learn_node(state)  # type: ignore[arg-type]
    entries = vault.all()
    assert len(entries) == 1
    assert entries[0]["name"] == "reverse_string"
    assert entries[0]["function"] == "reverse_string"
    # File on disk:
    assert (vault.tools_dir / "reverse_string.py").exists()


def test_learn_noops_when_tests_failed(vault):
    state = {
        "forged_tool": _good_forged(),
        "test_result": {"passed": False},
    }
    learn_node(state)  # type: ignore[arg-type]
    assert vault.all() == []


def test_learn_noops_without_forged_tool(vault):
    state = {"test_result": {"passed": True}}
    learn_node(state)  # type: ignore[arg-type]
    assert vault.all() == []


def test_learn_noops_without_test_result(vault):
    state = {"forged_tool": _good_forged()}
    learn_node(state)  # type: ignore[arg-type]
    assert vault.all() == []


def test_learn_skips_invalid_forged_tool(vault):
    """If forged_tool is missing required fields, register cleanly skips."""
    state = {
        "forged_tool": {"name": "x"},  # missing description, code, etc.
        "test_result": {"passed": True},
    }
    out = learn_node(state)  # type: ignore[arg-type]
    assert vault.all() == []
    assert "learn skipped" in (out.get("execution_result") or "")


def test_learn_idempotent_overwrites(vault):
    """Re-learning a tool with the same name overwrites cleanly."""
    state1 = {"forged_tool": _good_forged(), "test_result": {"passed": True}}
    learn_node(state1)  # type: ignore[arg-type]

    forged2 = _good_forged()
    forged2["description"] = "v2"
    forged2["code"] = "def reverse_string(s):\n    return s\n"
    state2 = {"forged_tool": forged2, "test_result": {"passed": True}}
    learn_node(state2)  # type: ignore[arg-type]

    entries = vault.all()
    assert len(entries) == 1
    assert entries[0]["description"] == "v2"
    assert vault.load("reverse_string")("abc") == "abc"


def _learn_graph():
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("learn", learn_node)
    g.add_edge(START, "learn")
    g.add_edge("learn", END)
    return g.compile()


def test_learn_emits_vault_saved_with_the_manifest_entry(vault):
    state = {"forged_tool": _good_forged(), "test_result": {"passed": True}}

    [event] = list(_learn_graph().stream(state, stream_mode="custom"))

    assert event["type"] == "vault.saved"
    assert event["data"]["sub"] is None
    assert event["data"]["tool"] == vault.get("reverse_string")


def test_learn_emits_nothing_when_tests_failed(vault):
    state = {"forged_tool": _good_forged(), "test_result": {"passed": False}}
    assert list(_learn_graph().stream(state, stream_mode="custom")) == []
