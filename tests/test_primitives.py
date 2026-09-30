"""Phase 2 primitive tests.

Network primitives (web_search, web_read) make live calls, so those tests
are gated behind RUN_LIVE=1 like every other live test. That keeps the
default suite (and CI) runnable with no keys and no network.
"""

from __future__ import annotations

import os
import time

import pytest

from talos.primitives.file_ops import file_read, file_write
from talos.primitives.python_exec import python_exec
from talos.primitives.shell_exec import shell_exec
from talos.primitives.web_read import web_read
from talos.primitives.web_search import web_search

live = pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1",
    reason="Set RUN_LIVE=1 to hit the real Tavily/Jina APIs.",
)

# --- web_search (live Tavily call) -------------------------------------------


@live
def test_web_search_returns_results():
    results = web_search("LangGraph python framework", max_results=3)
    assert isinstance(results, list)
    assert len(results) > 0
    # Tavily result schema:
    assert {"title", "url", "content"}.issubset(results[0].keys())


# --- web_read (live Jina call) -----------------------------------------------


@live
def test_web_read_returns_markdown():
    out = web_read("https://example.com")
    assert isinstance(out, str)
    assert len(out) > 0
    # Check Jina's response envelope, not page text: Jina sometimes serves a
    # cached snapshot of example.com whose body differs from the live page.
    assert "example.com" in out


def test_web_read_rejects_bare_string():
    with pytest.raises(ValueError):
        web_read("not-a-url")


# --- file_read / file_write ---------------------------------------------------


def test_file_round_trip(tmp_path):
    p = tmp_path / "nested" / "thing.txt"  # nested → exercises mkdir
    file_write(p, "hello, talos")
    assert file_read(p) == "hello, talos"


def test_file_read_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        file_read(tmp_path / "nope.txt")


def test_relative_paths_anchor_to_workspace(tmp_path, monkeypatch):
    """Bare filenames (no leading /) land in WORKSPACE_DIR, not cwd."""
    from talos.config import settings as s

    monkeypatch.setattr(s, "WORKSPACE_DIR", tmp_path)
    monkeypatch.chdir(tmp_path / "..")  # confirm cwd doesn't get the file

    file_write("report.md", "hello")
    assert (tmp_path / "report.md").read_text() == "hello"
    assert file_read("report.md") == "hello"


def test_absolute_paths_respected_verbatim(tmp_path, monkeypatch):
    """Explicit absolute paths win — workspace is bypassed."""
    from talos.config import settings as s

    bogus_workspace = tmp_path / "wrong"
    monkeypatch.setattr(s, "WORKSPACE_DIR", bogus_workspace)

    target = tmp_path / "explicit.txt"
    file_write(target, "yo")
    assert target.read_text() == "yo"
    assert not bogus_workspace.exists()  # workspace not touched


def test_file_write_encodes_dict_as_json(tmp_path):
    p = tmp_path / "data.json"
    file_write(p, {"city": "Mumbai", "temp": 28.5})
    import json

    assert json.loads(p.read_text()) == {"city": "Mumbai", "temp": 28.5}


def test_file_write_encodes_list_as_json(tmp_path):
    p = tmp_path / "list.json"
    file_write(p, [1, 2, 3])
    import json

    assert json.loads(p.read_text()) == [1, 2, 3]


def test_file_write_decodes_bytes(tmp_path):
    p = tmp_path / "b.txt"
    file_write(p, "héllo".encode())
    assert p.read_text(encoding="utf-8") == "héllo"


def test_file_write_handles_non_serialisable_via_default(tmp_path):
    """default=str ensures dict with datetime etc. doesn't crash."""
    from datetime import datetime

    p = tmp_path / "dt.json"
    file_write(p, {"t": datetime(2026, 5, 5, 12, 0, 0)})
    assert "2026-05-05" in p.read_text()


# --- python_exec --------------------------------------------------------------


def test_python_exec_happy_path():
    r = python_exec("print(2 + 2)")
    assert r["ok"] is True
    assert r["returncode"] == 0
    assert r["stdout"].strip() == "4"
    assert r["timed_out"] is False


def test_python_exec_syntax_error_captured():
    r = python_exec("def broken(:")
    assert r["ok"] is False
    assert r["returncode"] != 0
    assert "SyntaxError" in r["stderr"]
    assert r["timed_out"] is False


def test_python_exec_timeout_fires():
    start = time.monotonic()
    r = python_exec("import time; time.sleep(30)", timeout=1)
    elapsed = time.monotonic() - start
    assert r["timed_out"] is True
    assert r["ok"] is False
    assert r["returncode"] is None
    assert elapsed < 5  # sanity: timeout actually killed it, not just waited


# --- shell_exec ---------------------------------------------------------------


def test_shell_exec_happy_path():
    r = shell_exec("echo hi")
    assert r["ok"] is True
    assert r["stdout"].strip() == "hi"


def test_shell_exec_nonzero_exit():
    r = shell_exec("exit 7")
    assert r["ok"] is False
    assert r["returncode"] == 7


def test_shell_exec_timeout_fires():
    r = shell_exec("sleep 30", timeout=1)
    assert r["timed_out"] is True
    assert r["ok"] is False


# --- human_input --------------------------------------------------------------
# Real interrupt+resume needs a checkpointed graph (Phase 9). For Phase 2 we
# just verify the wrapper invokes `interrupt()` correctly inside a tiny graph
# and that the runtime emits the expected interrupt payload.


def test_human_input_pauses_graph():
    from typing import TypedDict

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    from talos.primitives.human_input import human_input

    class S(TypedDict, total=False):
        answer: str

    def ask(state: S) -> dict:
        a = human_input("What is your name?", hint="just first name")
        return {"answer": a}

    g = StateGraph(S)
    g.add_node("ask", ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    app = g.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "t1"}}
    # First invoke should NOT complete — it should pause at interrupt.
    result = app.invoke({}, config=config)
    # When a graph interrupts, `invoke` returns the partial state plus
    # an `__interrupt__` marker. We assert the interrupt payload reached us.
    assert "__interrupt__" in result
    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["message"] == "What is your name?"
    assert payload["hint"] == "just first name"


# --- vault_list (self-introspection) ------------------------------------------


def test_vault_list_reports_registered_tools(tmp_path, monkeypatch):
    from talos.primitives import vault_list as vl_mod
    from talos.vault.manager import SkillManager

    mgr = SkillManager(vault_dir=tmp_path)
    mgr.register(
        {
            "name": "slugify",
            "description": "make a slug",
            "keywords": ["slug"],
            "function": "slugify",
            "signature": "slugify(s: str) -> str",
        },
        "def slugify(s):\n    return s\n",
    )
    monkeypatch.setattr(vl_mod, "_get_skill_manager", lambda: mgr)

    out = vl_mod.vault_list()
    assert out == [
        {
            "name": "slugify",
            "description": "make a slug",
            "signature": "slugify(s: str) -> str",
            "usage_count": 0,
        }
    ]


def test_vault_list_is_a_planner_visible_primitive():
    from talos.agents.executor import PRIMITIVES
    from talos.prompts.planner import PLANNER_SYSTEM_PROMPT

    assert "vault_list" in PRIMITIVES
    assert "- vault_list:" in PLANNER_SYSTEM_PROMPT
