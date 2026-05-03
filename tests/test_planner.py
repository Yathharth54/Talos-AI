"""Phase 5 — Planner tests.

Same mocking pattern as the Forger: monkeypatch `_make_llm()` with a fake
that returns canned `Plan` objects. We also swap `_get_skill_manager()` so
tests don't depend on the real vault state.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from talos.agents import planner as planner_mod
from talos.agents.planner import Plan, SubTask, planner_node
from talos.vault.manager import SkillManager


# ---- helpers --------------------------------------------------------------

class _FakeLLM:
    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self._plan


@pytest.fixture
def empty_vault(tmp_path: Path, monkeypatch) -> SkillManager:
    mgr = SkillManager(vault_dir=tmp_path)
    monkeypatch.setattr(planner_mod, "_get_skill_manager", lambda: mgr)
    return mgr


@pytest.fixture
def vault_with_csv_tool(tmp_path: Path, monkeypatch) -> SkillManager:
    mgr = SkillManager(vault_dir=tmp_path)
    mgr.register(
        {
            "name": "csv_top_rows",
            "description": "parse a CSV and return top N rows by a column",
            "keywords": ["csv", "parse", "top", "rows"],
            "function": "csv_top_rows",
            "signature": "csv_top_rows(filepath: str, column: str, n: int = 5) -> list[dict]",
        },
        "def csv_top_rows(filepath, column, n=5):\n    return []\n",
    )
    monkeypatch.setattr(planner_mod, "_get_skill_manager", lambda: mgr)
    return mgr


def _state(query: str) -> dict:
    return {"messages": [HumanMessage(content=query)]}


# ---- structure tests -------------------------------------------------------

def test_planner_emits_well_formed_plan(empty_vault, monkeypatch):
    canned = Plan(sub_tasks=[
        SubTask(id=1, action="fetch", needs="primitive", tool_hint="web_read",
                keywords=["fetch", "url"], input_description="literal url",
                depends_on=[]),
        SubTask(id=2, action="parse", needs="forge",
                keywords=["parse", "html"], input_description="output of 1",
                depends_on=[1]),
    ])
    fake = _FakeLLM(canned)
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)

    out = planner_node(_state("scrape and parse this page"))
    assert out["plan"]["sub_tasks"][0]["needs"] == "primitive"
    assert out["plan"]["sub_tasks"][0]["tool_hint"] == "web_read"
    assert out["plan"]["sub_tasks"][1]["needs"] == "forge"
    assert out["plan"]["sub_tasks"][1]["depends_on"] == [1]
    assert out["current_sub_task"]["id"] == 1
    assert out["sub_task_results"] == []


def test_planner_empty_plan_for_conversational_query(empty_vault, monkeypatch):
    fake = _FakeLLM(Plan(sub_tasks=[]))
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)

    out = planner_node(_state("hi"))
    assert out["plan"]["sub_tasks"] == []
    assert out["current_sub_task"] is None


# ---- vault-awareness tests -------------------------------------------------

def test_planner_uses_vault_hint_when_match_exists(vault_with_csv_tool, monkeypatch):
    canned = Plan(sub_tasks=[
        SubTask(id=1, action="get top rows of CSV", needs="vault",
                tool_hint="csv_top_rows",
                keywords=["csv", "top"], input_description="literal path",
                depends_on=[]),
    ])
    fake = _FakeLLM(canned)
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)

    out = planner_node(_state("show me top rows of data.csv"))
    st = out["plan"]["sub_tasks"][0]
    assert st["needs"] == "vault"
    assert st["tool_hint"] == "csv_top_rows"


def test_planner_injects_vault_summary_into_prompt(vault_with_csv_tool, monkeypatch):
    fake = _FakeLLM(Plan(sub_tasks=[]))
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)

    planner_node(_state("anything"))
    user_msg = fake.calls[0][1].content
    assert "csv_top_rows" in user_msg
    assert "parse a CSV" in user_msg


def test_planner_handles_empty_vault_gracefully(empty_vault, monkeypatch):
    fake = _FakeLLM(Plan(sub_tasks=[]))
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)

    planner_node(_state("anything"))
    user_msg = fake.calls[0][1].content
    assert "vault is empty" in user_msg


def test_planner_injects_recent_history(empty_vault, monkeypatch):
    """Phase 7.5: planner sees prior conversation turns."""
    from langchain_core.messages import AIMessage

    fake = _FakeLLM(Plan(sub_tasks=[]))
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)

    state = {"messages": [
        HumanMessage(content="what's the temp in mumbai"),
        AIMessage(content="It's 28°C."),
        HumanMessage(content="is that high or low?"),
    ]}
    planner_node(state)
    user_msg = fake.calls[0][1].content
    assert "28°C" in user_msg
    assert "what's the temp in mumbai" in user_msg
    # The CURRENT query should NOT be duplicated in the history block
    # (history excludes the trailing HumanMessage).
    assert user_msg.count("is that high or low?") == 1


def test_planner_first_turn_history_says_so(empty_vault, monkeypatch):
    fake = _FakeLLM(Plan(sub_tasks=[]))
    monkeypatch.setattr(planner_mod, "_make_llm", lambda: fake)
    planner_node(_state("first ever query"))
    user_msg = fake.calls[0][1].content
    assert "first turn" in user_msg.lower()


# ---- live test (gated) -----------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1",
    reason="Set RUN_LIVE=1 to exercise the real OpenAI Planner.",
)
def test_planner_live_multi_step(monkeypatch, tmp_path):
    """Real OpenAI: must produce ≥2 sub-tasks for a 2-step query, and at
    least one of them should be labelled `primitive` for the URL fetch."""
    mgr = SkillManager(vault_dir=tmp_path)
    monkeypatch.setattr(planner_mod, "_get_skill_manager", lambda: mgr)

    out = planner_node(_state(
        "Read https://example.com and save the body to /tmp/out.txt"
    ))
    sub_tasks = out["plan"]["sub_tasks"]
    assert len(sub_tasks) >= 2, f"expected ≥2 sub-tasks, got: {sub_tasks}"
    needs_set = {st["needs"] for st in sub_tasks}
    assert "primitive" in needs_set, f"expected at least one primitive, got: {sub_tasks}"
