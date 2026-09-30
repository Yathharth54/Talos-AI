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

import subprocess
import sys
import tempfile

from talos.config import settings
from talos.events import emit
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
    """Execute forged code + test code in a subprocess inside a tmp cwd.

    Why our own subprocess instead of python_exec: we need to control `cwd`
    so that ill-behaved tests (which sometimes write files despite the
    prompt forbidding it) leak into a tmp dir, not the project root.

    Args / Returns: same shape as before.
    """
    full_source = code + "\n\n" + test_code + _RUNNER
    t = timeout if timeout is not None else settings.SUBPROCESS_TIMEOUT
    # Sandbox cwd so any rogue file writes happen in a tmp dir we discard.
    # tempfile.TemporaryDirectory cleans itself up on context exit.
    with tempfile.TemporaryDirectory(prefix="talos_test_") as tmp_cwd:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", full_source],
                capture_output=True,
                text=True,
                timeout=t,
                cwd=tmp_cwd,
            )
            result = {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as e:
            result = {
                "ok": False,
                "returncode": None,
                "stdout": _coerce_io(e.stdout),
                "stderr": _coerce_io(e.stderr),
                "timed_out": True,
            }

    if result["timed_out"]:
        return {
            "passed": False,
            "n_passed": 0,
            "n_failed": 0,
            "n_total": 0,
            "failures": [],
            "results": [],
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
        stderr = result["stderr"].strip()
        parsed["error"] = (
            "Code did not run to completion. "
            f"stderr: {stderr.splitlines()[-1] if stderr else 'unknown'}"
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

    Reads:  forged_tool {name, code, test_code}, retry_count (the attempt number)
    Writes: test_result {passed, results, ...full run_tests output}
    Emits:  forge.tests {tool, attempt, results}
    """
    forged = state.get("forged_tool") or {}
    code = forged.get("code", "")
    test_code = forged.get("test_code", "")
    if not code or not test_code:
        result = {
            "passed": False,
            "n_passed": 0,
            "n_failed": 0,
            "n_total": 0,
            "failures": [],
            "results": [],
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "error": "Forger produced no code or no test_code.",
        }
    else:
        result = run_tests(code, test_code)
    emit(
        "forge.tests",
        tool=forged.get("name") or "",
        attempt=state.get("retry_count", 0),
        results=result["results"],
    )
    return {"test_result": result}


# ---- internal -------------------------------------------------------------


def _parse_runner_output(stdout: str) -> dict:
    """Parse our TALOS_TEST markers out of subprocess stdout.

    `results` lists every test in run order as `{name, passed, why}`. `why`
    is the last non-empty line of a failing test's traceback (e.g.
    "AssertionError: expected 'cba'"), and None for a passing test.
    """
    n_passed = 0
    n_failed = 0
    n_total = 0
    failures: list[dict] = []
    results: list[dict] = []
    by_name: dict[str, dict] = {}
    in_trace_for: str | None = None
    trace_buf: list[str] = []

    for line in stdout.splitlines():
        if line.startswith("TALOS_TEST PASS "):
            n_passed += 1
            name = line[len("TALOS_TEST PASS ") :].strip()
            results.append({"name": name, "passed": True, "why": None})
        elif line.startswith("TALOS_TEST FAIL "):
            n_failed += 1
            name = line[len("TALOS_TEST FAIL ") :].strip()
            record = {"name": name, "passed": False, "why": None}
            results.append(record)
            by_name[name] = record
        elif line.startswith("TALOS_TEST TRACE_START "):
            in_trace_for = line[len("TALOS_TEST TRACE_START ") :].strip()
            trace_buf = []
        elif line.startswith("TALOS_TEST TRACE_END "):
            if in_trace_for is not None:
                failures.append({"name": in_trace_for, "trace": "\n".join(trace_buf)})
                if in_trace_for in by_name:
                    by_name[in_trace_for]["why"] = _last_line(trace_buf)
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
        "results": results,
    }


def _last_line(lines: list[str]) -> str | None:
    """Last non-empty line of a traceback, stripped; None if there is none."""
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return None


def _coerce_io(x: object) -> str:
    """Subprocess io can be bytes, None, or str depending on platform/timeout."""
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x)


def _summarise_failures(failures: list[dict]) -> str:
    if not failures:
        return "Tests failed but no traces were captured."
    parts = [f"{f['name']}:\n{f['trace']}" for f in failures[:3]]
    suffix = "" if len(failures) <= 3 else f"\n(+{len(failures) - 3} more failures)"
    return "\n\n".join(parts) + suffix
