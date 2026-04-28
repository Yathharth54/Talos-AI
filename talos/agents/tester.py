"""Tester agent — runs forged code in a subprocess and reports results.

No LLM here. The Tester is "the Forger's inner critic" but in Phase 4 it's
purely mechanical: stitch the forged code + test code into one Python file,
run it, parse pass/fail.

Why an in-line runner instead of pytest? Because pytest as a subprocess
adds startup time, depends on filesystem layout, and parses output via
exit codes rather than structured data. A 30-line custom runner gives us
direct control over what each test reports.
"""

from __future__ import annotations

from talos.primitives.python_exec import python_exec
from talos.state import TalosState

# A small runner appended to the forged code. It discovers test_* functions,
# calls each one, and prints a single-line marker per test that we can parse.
_RUNNER = """

# --- talos test runner ---
import traceback as _tb

_failures = []
_passes = []
_tests = [
    (_n, _f) for _n, _f in list(globals().items())
    if _n.startswith("test_") and callable(_f)
]
for _name, _fn in _tests:
    try:
        _fn()
        _passes.append(_name)
        print(f"TALOS_TEST PASS {_name}")
    except Exception as _e:
        _failures.append((_name, _tb.format_exc()))
        print(f"TALOS_TEST FAIL {_name}")
        print(f"TALOS_TEST TRACE_START {_name}")
        print(_tb.format_exc())
        print(f"TALOS_TEST TRACE_END {_name}")

print(f"TALOS_TEST SUMMARY pass={len(_passes)} fail={len(_failures)} total={len(_tests)}")
if _failures:
    raise SystemExit(1)
"""


def run_tests(code: str, test_code: str, timeout: int | None = None) -> dict:
    """Execute forged code + test code in a subprocess. Pure utility — no state.

    Args:
        code: the forged tool's source.
        test_code: the forged tests' source.
        timeout: subprocess timeout (seconds). Defaults via python_exec.

    Returns:
        {
          passed:    bool,
          n_passed:  int,
          n_failed:  int,
          n_total:   int,
          failures:  list[{name, trace}],
          stdout:    str,
          stderr:    str,
          timed_out: bool,
          error:     str | None,   # high-level summary for retry context
        }
    """
    full_source = code + "\n\n" + test_code + _RUNNER
    result = python_exec(full_source, timeout=timeout)

    if result["timed_out"]:
        return {
            "passed": False,
            "n_passed": 0,
            "n_failed": 0,
            "n_total": 0,
            "failures": [],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "timed_out": True,
            "error": "Subprocess timed out (likely infinite loop).",
        }

    parsed = _parse_runner_output(result["stdout"])
    parsed["stdout"] = result["stdout"]
    parsed["stderr"] = result["stderr"]
    parsed["timed_out"] = False

    # If subprocess crashed before tests ran (e.g. SyntaxError, ImportError),
    # stderr will have the trace and stdout will have no markers.
    if parsed["n_total"] == 0 and not result["ok"]:
        parsed["passed"] = False
        parsed["error"] = (
            "Code did not run to completion. "
            f"stderr: {result['stderr'].strip().splitlines()[-1] if result['stderr'].strip() else 'unknown'}"
        )
    elif parsed["n_failed"] > 0:
        parsed["passed"] = False
        parsed["error"] = _summarise_failures(parsed["failures"])
    else:
        parsed["passed"] = parsed["n_total"] > 0
        parsed["error"] = None

    return parsed


def tester_node(state: TalosState) -> dict:
    """LangGraph node: run the forged_tool through tests.

    Reads:  forged_tool {code, test_code}
    Writes: test_result {passed, ...full run_tests output}
    """
    forged = state.get("forged_tool") or {}
    code = forged.get("code", "")
    test_code = forged.get("test_code", "")
    if not code or not test_code:
        return {
            "test_result": {
                "passed": False,
                "n_passed": 0,
                "n_failed": 0,
                "n_total": 0,
                "failures": [],
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "error": "Forger produced no code or no test_code.",
            }
        }
    return {"test_result": run_tests(code, test_code)}


# ---- internal -------------------------------------------------------------

def _parse_runner_output(stdout: str) -> dict:
    """Parse our TALOS_TEST markers out of subprocess stdout."""
    n_passed = 0
    n_failed = 0
    n_total = 0
    failures: list[dict] = []
    in_trace_for: str | None = None
    trace_buf: list[str] = []

    for line in stdout.splitlines():
        if line.startswith("TALOS_TEST PASS "):
            n_passed += 1
        elif line.startswith("TALOS_TEST FAIL "):
            n_failed += 1
        elif line.startswith("TALOS_TEST TRACE_START "):
            in_trace_for = line[len("TALOS_TEST TRACE_START "):].strip()
            trace_buf = []
        elif line.startswith("TALOS_TEST TRACE_END "):
            if in_trace_for is not None:
                failures.append({"name": in_trace_for, "trace": "\n".join(trace_buf)})
            in_trace_for = None
            trace_buf = []
        elif line.startswith("TALOS_TEST SUMMARY "):
            for tok in line.split()[2:]:
                k, _, v = tok.partition("=")
                if k == "total":
                    n_total = int(v)
        elif in_trace_for is not None:
            trace_buf.append(line)

    return {
        "passed": False,  # caller overrides based on counts + crash detection
        "n_passed": n_passed,
        "n_failed": n_failed,
        "n_total": n_total,
        "failures": failures,
    }


def _summarise_failures(failures: list[dict]) -> str:
    if not failures:
        return "Tests failed but no traces were captured."
    parts = [f"{f['name']}:\n{f['trace']}" for f in failures[:3]]
    suffix = "" if len(failures) <= 3 else f"\n(+{len(failures) - 3} more failures)"
    return "\n\n".join(parts) + suffix
