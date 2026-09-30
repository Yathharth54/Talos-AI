"""Phase 4 — Tester tests. No LLM involved. Pure subprocess validation."""

from __future__ import annotations

from talos.agents.tester import run_tests, tester_node

# --- run_tests utility --------------------------------------------------------


def test_run_tests_passes_when_code_is_correct():
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    test_code = (
        "def test_basic():\n    assert add(2, 3) == 5\n\n"
        "def test_zero():\n    assert add(0, 0) == 0\n"
    )
    r = run_tests(code, test_code)
    assert r["passed"] is True
    assert r["n_passed"] == 2
    assert r["n_failed"] == 0
    assert r["n_total"] == 2
    assert r["error"] is None


def test_run_tests_fails_when_assertion_fails():
    code = "def add(a: int, b: int) -> int:\n    return a + b + 1\n"  # off by one
    test_code = "def test_basic():\n    assert add(2, 3) == 5\n"
    r = run_tests(code, test_code)
    assert r["passed"] is False
    assert r["n_failed"] == 1
    assert r["error"] is not None
    assert "test_basic" in r["error"]


def test_run_tests_handles_syntax_error():
    code = "def add(a: int b: int) -> int:\n    return a + b\n"  # missing comma
    test_code = "def test_basic():\n    assert add(2, 3) == 5\n"
    r = run_tests(code, test_code)
    assert r["passed"] is False
    assert r["n_total"] == 0
    assert r["error"] is not None


def test_run_tests_handles_runtime_error():
    code = "def divide(a: int, b: int) -> float:\n    return a / b\n"
    test_code = (
        "def test_zero_div():\n"
        "    try:\n"
        "        divide(1, 0)\n"
        "        assert False, 'should have raised'\n"
        "    except ZeroDivisionError:\n"
        "        pass\n"
    )
    r = run_tests(code, test_code)
    assert r["passed"] is True


def test_run_tests_times_out_on_infinite_loop():
    code = "def loop() -> None:\n    while True:\n        pass\n"
    test_code = "def test_loop():\n    loop()\n"
    r = run_tests(code, test_code, timeout=2)
    assert r["timed_out"] is True
    assert r["passed"] is False
    assert "timed out" in (r["error"] or "").lower()


def test_run_tests_does_not_leak_files_to_cwd(tmp_path, monkeypatch):
    """Even if a test writes to a relative path, it must NOT land in cwd —
    the test subprocess runs in an isolated temp dir."""
    import os

    monkeypatch.chdir(tmp_path)
    code = "def stash(p: str, c: str) -> None:\n    open(p, 'w').write(c)\n"
    test_code = "def test_a():\n    stash('leaked_evil_file.txt', 'haha')\n    assert True\n"
    r = run_tests(code, test_code)
    assert r["passed"] is True
    # Most importantly — the file is NOT in the test's cwd.
    assert not (tmp_path / "leaked_evil_file.txt").exists()
    # And it's not in the project root either (sanity).
    assert not os.path.exists(os.path.join(os.getcwd(), "leaked_evil_file.txt"))


def test_run_tests_partial_failure_summary():
    code = "def f(x: int) -> int:\n    return x * 2\n"
    test_code = (
        "def test_a():\n    assert f(1) == 2\n\n"
        "def test_b():\n    assert f(2) == 999\n"  # fails
    )
    r = run_tests(code, test_code)
    assert r["passed"] is False
    assert r["n_passed"] == 1
    assert r["n_failed"] == 1
    assert len(r["failures"]) == 1
    assert r["failures"][0]["name"] == "test_b"


# --- tester_node (LangGraph contract) ----------------------------------------


def test_tester_node_reads_forged_tool_from_state():
    state = {
        "forged_tool": {
            "code": "def x():\n    return 1\n",
            "test_code": "def test_x():\n    assert x() == 1\n",
        }
    }
    out = tester_node(state)  # type: ignore[arg-type]
    assert out["test_result"]["passed"] is True


def test_tester_node_handles_missing_forged_tool():
    out = tester_node({})  # type: ignore[arg-type]
    assert out["test_result"]["passed"] is False
    assert "no code" in out["test_result"]["error"].lower()


# --- per-test results (spec 01 §9.2) ------------------------------------------


def test_run_tests_reports_each_test_in_order():
    code = "def add(a: int, b: int) -> int:\n    return a + b + (1 if a == 2 else 0)\n"
    test_code = (
        "def test_zero():\n    assert add(0, 0) == 0\n\n"
        "def test_two():\n    assert add(2, 3) == 5, 'add(2, 3) should be 5'\n\n"
        "def test_one():\n    assert add(1, 1) == 2\n"
    )
    r = run_tests(code, test_code)
    assert r["results"] == [
        {"name": "test_zero", "passed": True, "why": None},
        {"name": "test_two", "passed": False, "why": "AssertionError: add(2, 3) should be 5"},
        {"name": "test_one", "passed": True, "why": None},
    ]


def test_run_tests_results_empty_when_code_does_not_compile():
    r = run_tests("def broken(:\n    pass\n", "def test_x():\n    assert True\n")
    assert r["results"] == []


def test_run_tests_results_empty_on_timeout():
    code = "def loop() -> None:\n    while True:\n        pass\n"
    r = run_tests(code, "def test_loop():\n    loop()\n", timeout=2)
    assert r["results"] == []


def test_failing_test_without_message_uses_exception_name():
    code = "def f() -> int:\n    return 1\n"
    r = run_tests(code, "def test_f():\n    assert f() == 2\n")
    assert r["results"] == [{"name": "test_f", "passed": False, "why": "AssertionError"}]


def test_tester_node_emits_forge_tests():
    from langgraph.graph import END, START, StateGraph

    from talos.state import TalosState

    g: StateGraph = StateGraph(TalosState)
    g.add_node("test", tester_node)
    g.add_edge(START, "test")
    g.add_edge("test", END)
    forged = {
        "name": "add",
        "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
        "test_code": "def test_add():\n    assert add(1, 2) == 3\n",
    }
    chunks = list(
        g.compile().stream({"forged_tool": forged, "retry_count": 2}, stream_mode="custom")
    )
    assert chunks == [
        {
            "type": "forge.tests",
            "data": {
                "tool": "add",
                "attempt": 2,
                "results": [{"name": "test_add", "passed": True, "why": None}],
            },
        }
    ]


def test_tester_node_without_code_reports_no_results():
    out = tester_node({"forged_tool": {"name": "x", "code": "", "test_code": ""}})  # type: ignore[arg-type]
    assert out["test_result"]["results"] == []
    assert out["test_result"]["passed"] is False
