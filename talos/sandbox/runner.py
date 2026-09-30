"""run_tool: call one forged-tool function in a time-limited subprocess.

Spec 03 §2.1. The parent never unpickles anything: arguments and the
return value cross the boundary as tagged JSON (`talos.sandbox.codec`).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from talos.config import settings
from talos.sandbox.codec import decode, encode

logger = logging.getLogger(__name__)

# Captured tool output kept in ToolResult.stdout (characters).
STDOUT_LIMIT = 64 * 1024

# The directory that holds the `talos` package, so the child can import
# talos.sandbox.child even when its cwd is the workspace.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

# How long to wait for a killed child's pipes to close.
_REAP_TIMEOUT = 5.0


@dataclass
class ToolResult:
    """Outcome of one sandboxed tool call.

    Attributes:
        ok: True when the function returned normally.
        value: The decoded return value when ok.
        error: `"TypeError: shift must be an int, got str"` style text.
        timed_out: True when the call was killed for running too long.
        stdout: The tool's printed output, truncated to 64 KB.
    """

    ok: bool
    value: Any = None
    error: str | None = None
    timed_out: bool = False
    stdout: str = ""


def _truncate(text: str) -> str:
    if len(text) <= STDOUT_LIMIT:
        return text
    return text[:STDOUT_LIMIT] + "\n…(truncated)"


def _child_env() -> dict[str, str]:
    """The parent's environment (tools need their API keys), plus a
    PYTHONPATH entry so the child can import the talos package."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_PACKAGE_ROOT) + (os.pathsep + existing if existing else "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """Kill the child and everything it started (it leads its own session)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _parse_reply(stdout: str, sentinel: str) -> tuple[str, dict[str, Any] | None]:
    """Split raw child stdout into (stray output, reply dict or None)."""
    marker = "\n" + sentinel + "\n"
    head, found, tail = stdout.rpartition(marker)
    if not found:
        return stdout, None
    try:
        reply = json.loads(tail.strip().splitlines()[0])
    except (ValueError, IndexError):
        return head, None
    return head, reply if isinstance(reply, dict) else None


def _crash_error(returncode: int | None, stderr: str) -> str:
    last = next((ln for ln in reversed(stderr.strip().splitlines()) if ln.strip()), "")
    detail = f": {last}" if last else ""
    return f"SandboxError: tool process exited with code {returncode} and no result{detail}"


def run_tool(
    source_path: Path,
    function: str,
    args: list[Any],
    kwargs: dict[str, Any],
    timeout: float | None = None,
) -> ToolResult:
    """Run `function` from the file at `source_path` in a subprocess.

    Args:
        source_path: The tool's .py file.
        function: Name of the function to call in that file.
        args: Positional arguments.
        kwargs: Keyword arguments.
        timeout: Seconds before the child is killed; defaults to
            `settings.TOOL_TIMEOUT` (TALOS_TOOL_TIMEOUT, 30 s).

    Returns:
        A ToolResult. It never raises for tool failures, timeouts or crashes.
    """
    limit = settings.TOOL_TIMEOUT if timeout is None else timeout
    sentinel = f"__TALOS_SANDBOX_REPLY_{secrets.token_hex(16)}__"
    request = json.dumps(
        {
            "source_path": str(Path(source_path).resolve()),
            "function": function,
            "args": encode(list(args)),
            "kwargs": encode(dict(kwargs)),
            "sentinel": sentinel,
        }
    )
    workdir = Path(settings.WORKSPACE_DIR)
    workdir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, "-P", "-m", "talos.sandbox.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=workdir,
        env=_child_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(request, timeout=limit)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            stdout, _ = proc.communicate(timeout=_REAP_TIMEOUT)
        except subprocess.TimeoutExpired:
            stdout = ""
        logger.warning("sandboxed tool %s timed out after %ss", function, limit)
        return ToolResult(
            ok=False,
            error=f"TimeoutError: tool ran longer than {limit:g}s",
            timed_out=True,
            stdout=_truncate(stdout or ""),
        )

    stray, reply = _parse_reply(stdout, sentinel)
    if reply is None:
        return ToolResult(
            ok=False, error=_crash_error(proc.returncode, stderr), stdout=_truncate(stray)
        )
    printed = stray.rstrip("\n") + str(reply.get("stdout") or "")
    if not reply.get("ok"):
        return ToolResult(ok=False, error=str(reply.get("error")), stdout=_truncate(printed))
    try:
        value = decode(reply.get("value"))
    except (ValueError, RecursionError) as e:
        return ToolResult(
            ok=False, error=f"SandboxError: bad result: {e}", stdout=_truncate(printed)
        )
    return ToolResult(ok=True, value=value, stdout=_truncate(printed))
