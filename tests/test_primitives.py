"""Phase 2 primitive tests.

Network primitives (web_search, web_read) make live calls. They're cheap
on free tiers, so no `RUN_LIVE` flag yet. If a key is missing or the network
is unavailable, the test will fail loudly — that's the desired signal.
"""

from __future__ import annotations

import time

import pytest

from talos.primitives.file_ops import file_read, file_write
from talos.primitives.python_exec import python_exec
from talos.primitives.shell_exec import shell_exec
from talos.primitives.web_read import web_read
from talos.primitives.web_search import web_search


# --- web_search (live Tavily call) -------------------------------------------

def test_web_search_returns_results():
    results = web_search("LangGraph python framework", max_results=3)
    assert isinstance(results, list)
    assert len(results) > 0
    # Tavily result schema:
    assert {"title", "url", "content"}.issubset(results[0].keys())


# --- web_read (live Jina call) -----------------------------------------------

def test_web_read_returns_markdown():
    out = web_read("https://example.com")
    assert isinstance(out, str)
    assert len(out) > 0
    # example.com always contains the phrase "Example Domain".
    assert "Example Domain" in out


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
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict

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
