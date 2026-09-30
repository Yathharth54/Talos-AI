"""run_tool: forged tools run in a time-limited subprocess (spec 03 §2.1, §2.4)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from talos.config import settings
from talos.sandbox import ToolResult, run_tool
from talos.sandbox.runner import STDOUT_LIMIT

FIXTURES = Path(__file__).parent / "fixtures" / "sandbox"


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setattr(settings, "WORKSPACE_DIR", ws)
    return ws


def _tool(tmp_path: Path, source: str, name: str = "tool.py") -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_returns_the_value(tmp_path):
    path = _tool(tmp_path, "def add(a: int, b: int) -> int:\n    return a + b\n")
    assert run_tool(path, "add", [2], {"b": 3}) == ToolResult(ok=True, value=5)


def test_tagged_values_cross_both_ways(tmp_path):
    path = _tool(tmp_path, "def echo(x):\n    return (x, {1: b'raw'}, 2**60)\n")
    result = run_tool(path, "echo", [{"k": (1, 2)}], {})
    assert result.value == ({"k": (1, 2)}, {1: b"raw"}, 2**60)


def test_raised_error_uses_the_executor_format(tmp_path):
    path = _tool(tmp_path, "def boom():\n    raise ValueError('kaboom')\n")
    result = run_tool(path, "boom", [], {})
    assert result.ok is False
    assert result.error == "ValueError: kaboom"
    assert result.timed_out is False


def test_real_vault_caesar_cipher_word_shift_error_is_unchanged():
    result = run_tool(
        FIXTURES / "caesar_cipher.py",
        "caesar_cipher",
        [],
        {"text": "TALOS AGENT", "shift": "seven", "mode": "encrypt"},
    )
    assert result.error == "TypeError: shift must be an int, got str"


def test_real_vault_caesar_cipher_works():
    result = run_tool(
        FIXTURES / "caesar_cipher.py",
        "caesar_cipher",
        [],
        {"text": "TALOS AGENT", "shift": 7, "mode": "encrypt"},
    )
    assert result.value == "AHSVZ HNLUA"


def test_sleeping_tool_is_killed_at_the_timeout(tmp_path):
    path = _tool(tmp_path, "import time\ndef slow():\n    time.sleep(60)\n")
    started = time.monotonic()
    result = run_tool(path, "slow", [], {}, timeout=1)
    assert time.monotonic() - started < 10
    assert result.ok is False
    assert result.timed_out is True
    assert result.error == "TimeoutError: tool ran longer than 1s"


def test_timeout_kills_processes_the_tool_started(tmp_path):
    marker = tmp_path / "grandchild.pid"
    path = _tool(
        tmp_path,
        "import subprocess, sys, time\n"
        "def spawn(marker):\n"
        "    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "    open(marker, 'w').write(str(p.pid))\n"
        "    time.sleep(60)\n",
    )
    result = run_tool(path, "spawn", [str(marker)], {}, timeout=2)
    assert result.timed_out is True
    pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild process survived the timeout")


def test_default_timeout_comes_from_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TOOL_TIMEOUT", 1.0)
    path = _tool(tmp_path, "import time\ndef slow():\n    time.sleep(60)\n")
    result = run_tool(path, "slow", [], {})
    assert result.error == "TimeoutError: tool ran longer than 1s"


def test_prints_are_captured_and_do_not_corrupt_the_reply(tmp_path):
    path = _tool(
        tmp_path,
        "import sys\n"
        "def chatty():\n"
        "    print('hello')\n"
        "    print('{\"ok\": false}')\n"
        "    sys.stdout.write('no newline')\n"
        "    return 'done'\n",
    )
    result = run_tool(path, "chatty", [], {})
    assert result.ok is True
    assert result.value == "done"
    assert result.stdout == 'hello\n{"ok": false}\nno newline'


def test_output_written_straight_to_the_fd_is_kept_as_stdout(tmp_path):
    path = _tool(
        tmp_path, "import os\ndef raw():\n    os.write(1, b'raw bytes\\n')\n    return 1\n"
    )
    result = run_tool(path, "raw", [], {})
    assert result.value == 1
    assert "raw bytes" in result.stdout


def test_stdout_is_truncated(tmp_path):
    path = _tool(tmp_path, "def loud():\n    print('x' * 200_000)\n")
    result = run_tool(path, "loud", [], {})
    assert result.ok is True
    assert len(result.stdout) <= STDOUT_LIMIT + 20


def test_returned_objects_arrive_as_repr_strings(tmp_path):
    path = _tool(
        tmp_path,
        "import os\n"
        "class Evil:\n"
        "    def __reduce__(self):\n"
        "        return (os.system, ('touch pwned',))\n"
        "    def __repr__(self):\n"
        "        return '<Evil>'\n"
        "def make():\n"
        "    return Evil()\n",
    )
    result = run_tool(path, "make", [], {})
    assert result.ok is True
    assert result.value == "<Evil>"
    assert not (Path.cwd() / "pwned").exists()


def test_self_referencing_value_falls_back_to_repr(tmp_path):
    path = _tool(tmp_path, "def loop():\n    x = []\n    x.append(x)\n    return x\n")
    assert run_tool(path, "loop", [], {}).value == "[[...]]"


def test_input_gets_eof_instead_of_hanging(tmp_path):
    path = _tool(tmp_path, "def ask():\n    return input('name? ')\n")
    result = run_tool(path, "ask", [], {}, timeout=5)
    assert result.timed_out is False
    assert result.error == "EOFError: EOF when reading a line"


def test_hard_exit_is_reported_as_a_crash(tmp_path):
    path = _tool(tmp_path, "import os\ndef die():\n    os._exit(3)\n")
    result = run_tool(path, "die", [], {})
    assert result.ok is False
    assert result.error.startswith("SandboxError: tool process exited with code 3")


def test_sys_exit_is_a_tool_error(tmp_path):
    path = _tool(tmp_path, "import sys\ndef leave():\n    sys.exit('bye')\n")
    assert run_tool(path, "leave", [], {}).error == "SystemExit: bye"


def test_missing_function_is_an_error(tmp_path):
    path = _tool(tmp_path, "def other():\n    return 1\n")
    assert (
        run_tool(path, "absent", [], {}).error
        == "AttributeError: tool.py defines no function 'absent'"
    )


def test_syntax_error_is_an_error(tmp_path):
    path = _tool(tmp_path, "def broken(:\n")
    assert run_tool(path, "broken", [], {}).error.startswith("SyntaxError:")


def test_cwd_is_the_workspace(tmp_path, workspace):
    path = _tool(tmp_path, "def write():\n    open('out.txt', 'w').write('hi')\n    return 'ok'\n")
    assert run_tool(path, "write", [], {}).ok is True
    assert (workspace / "out.txt").read_text() == "hi"


def test_workspace_module_does_not_shadow_the_stdlib(tmp_path, workspace):
    workspace.mkdir(parents=True)
    (workspace / "json.py").write_text("raise RuntimeError('shadowed')\n")
    path = _tool(tmp_path, "import json\ndef dump():\n    return json.dumps([1])\n")
    assert run_tool(path, "dump", [], {}).value == "[1]"


def test_tool_sees_the_parent_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TALOS_SANDBOX_TEST_KEY", "secret-123")
    path = _tool(
        tmp_path, "import os\ndef key():\n    return os.environ['TALOS_SANDBOX_TEST_KEY']\n"
    )
    assert run_tool(path, "key", [], {}).value == "secret-123"


def test_state_does_not_leak_between_calls(tmp_path):
    path = _tool(
        tmp_path,
        "COUNTER = []\ndef bump():\n    COUNTER.append(1)\n    return len(COUNTER)\n",
    )
    assert run_tool(path, "bump", [], {}).value == 1
    assert run_tool(path, "bump", [], {}).value == 1
