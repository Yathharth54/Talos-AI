"""run_tool: call one forged-tool function in a time-limited subprocess.

Spec 03 §2.1. The parent never unpickles anything: arguments and the
return value cross the boundary as tagged JSON (`talos.sandbox.codec`).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import select
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from talos.config import settings
from talos.sandbox.codec import decode, encode

logger = logging.getLogger(__name__)

# Captured tool output kept in ToolResult.stdout (characters).
STDOUT_LIMIT = 64 * 1024

# Largest reply (the encoded return value) the parent accepts, in bytes.
REPLY_LIMIT = 16 * 1024 * 1024

# Bytes of the tool's stray stdout kept (enough for STDOUT_LIMIT characters
# of UTF-8); the rest is read and discarded.
_STRAY_BYTES = 4 * STDOUT_LIMIT + 4

# Bytes of stderr kept (from the end); only the last line is reported.
_STDERR_BYTES = 8 * 1024

# Bytes read from a pipe at a time.
_READ_SIZE = 64 * 1024

# How often the pump checks the clock and whether the child has exited.
_POLL_INTERVAL = 0.05

# The directory that holds the `talos` package, so the child can import
# talos.sandbox.child even when its cwd is the workspace.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

# How long to wait for pipes to close (and the child to be reaped) after the
# process group has been killed.
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


class _StdoutCollector:
    """Bounded reader for the child's stdout.

    Keeps the first `_STRAY_BYTES` of the tool's stray output and, after the
    last sentinel marker, up to `REPLY_LIMIT` bytes of the reply. Everything
    else is discarded as it arrives, so a tool that floods stdout can't grow
    the parent's memory.
    """

    def __init__(self, marker: bytes) -> None:
        self._marker = marker
        # Bytes held back because they might be the start of a marker.
        self._carry = b""
        self._newline_seen = False
        self.stray = bytearray()
        self.reply: bytearray | None = None
        self.reply_overflow = False

    def feed(self, chunk: bytes) -> None:
        """Consume one chunk read from the pipe."""
        data = self._carry + chunk
        idx = data.rfind(self._marker)
        if idx >= 0:
            self._emit(data[:idx])
            if self.reply is not None:
                # An earlier "marker" wasn't the last one: it was output.
                self._keep_stray(self._marker + bytes(self.reply))
            self.reply = bytearray()
            self.reply_overflow = False
            self._newline_seen = False
            data = data[idx + len(self._marker) :]
        keep = len(self._marker) - 1
        if len(data) > keep:
            self._emit(data[: len(data) - keep])
            data = data[len(data) - keep :]
        self._carry = data

    def finish(self) -> None:
        """Flush the held-back bytes once the pipe is done."""
        self._emit(self._carry)
        self._carry = b""

    @property
    def reply_complete(self) -> bool:
        """True once the whole reply line (ending in a newline) has arrived."""
        return self.reply is not None and (self._newline_seen or b"\n" in self._carry)

    def _emit(self, data: bytes) -> None:
        if self.reply is None:
            self._keep_stray(data)
            return
        if b"\n" in data:
            self._newline_seen = True
        room = REPLY_LIMIT - len(self.reply)
        if len(data) > room:
            self.reply_overflow = True
        self.reply += data[: max(room, 0)]

    def _keep_stray(self, data: bytes) -> None:
        room = _STRAY_BYTES - len(self.stray)
        if room > 0:
            self.stray += data[:room]


class _Tail:
    """Keeps only the last `limit` bytes written to it."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> None:
        """Consume one chunk read from the pipe."""
        self._buf += chunk
        if len(self._buf) > 2 * self._limit:
            del self._buf[: -self._limit]

    def text(self) -> str:
        """The kept bytes, decoded."""
        return bytes(self._buf[-self._limit :]).decode("utf-8", errors="replace")


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    """Kill the child and everything it started (it leads its own session)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except OSError:
            pass


def _pump(
    proc: subprocess.Popen[bytes],
    request: bytes,
    stdout: _StdoutCollector,
    stderr: _Tail,
    limit: float,
) -> bool:
    """Send the request and read both pipes until the reply is in or the
    call is over.

    Stops as soon as the reply line is complete, when both pipes close, or
    `_REAP_TIMEOUT` after the child exits or is killed (a detached process
    can hold the pipes open forever).

    Returns:
        True when the call ran past `limit` and the group was killed.
    """
    assert proc.stdin and proc.stdout and proc.stderr
    readers = {proc.stdout.fileno(): stdout.feed, proc.stderr.fileno(): stderr.feed}
    stdin_fd = proc.stdin.fileno()
    pending = memoryview(request)
    deadline = time.monotonic() + limit
    drain_until: float | None = None
    timed_out = False
    with selectors.DefaultSelector() as sel:
        for fd in readers:
            sel.register(fd, selectors.EVENT_READ)
        sel.register(stdin_fd, selectors.EVENT_WRITE)
        while any(fd in readers for fd in sel.get_map()):
            if stdout.reply_complete:
                break
            now = time.monotonic()
            if drain_until is None:
                if now >= deadline:
                    timed_out = True
                    _kill_group(proc)
                    drain_until = now + _REAP_TIMEOUT
                elif proc.poll() is not None:
                    _kill_group(proc)
                    drain_until = now + _REAP_TIMEOUT
            elif now >= drain_until:
                break
            wait = min(_POLL_INTERVAL, (drain_until or deadline) - now)
            for key, _ in sel.select(max(wait, 0.0)):
                fd = key.fd
                if fd == stdin_fd:
                    try:
                        written = os.write(fd, pending[: select.PIPE_BUF])
                    except BrokenPipeError:
                        written = len(pending)
                    pending = pending[written:]
                    if not pending:
                        sel.unregister(fd)
                        proc.stdin.close()
                    continue
                data = os.read(fd, _READ_SIZE)
                if data:
                    readers[fd](data)
                else:
                    sel.unregister(fd)
    return timed_out


def _close_and_reap(proc: subprocess.Popen[bytes]) -> None:
    """Close our ends of the pipes and wait for the killed child."""
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass
    try:
        proc.wait(timeout=_REAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("sandbox child %s did not exit after SIGKILL", proc.pid)


def _parse_reply(line: str) -> dict[str, Any] | None:
    """Decode the JSON reply line that follows the sentinel, or None."""
    try:
        reply = json.loads(line.strip().splitlines()[0])
    except (ValueError, IndexError, RecursionError):
        return None
    return reply if isinstance(reply, dict) else None


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

    The child's output is read with bounded buffers (the first 64 KB of
    printed output, the reply, the end of stderr). When the call is over,
    however it ended, the child's whole process group is killed, so
    processes a tool starts never outlive the call.

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

    stdout = _StdoutCollector(("\n" + sentinel + "\n").encode("utf-8"))
    stderr = _Tail(_STDERR_BYTES)
    proc = subprocess.Popen(
        [sys.executable, "-P", "-m", "talos.sandbox.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=workdir,
        env=_child_env(),
        start_new_session=True,
    )
    try:
        timed_out = _pump(proc, request.encode("utf-8"), stdout, stderr, limit)
    finally:
        _kill_group(proc)
        _close_and_reap(proc)
    stdout.finish()

    stray = bytes(stdout.stray).decode("utf-8", errors="replace")
    reply = None
    if stdout.reply is not None:
        if stdout.reply_overflow:
            return ToolResult(
                ok=False,
                error=f"SandboxError: result is larger than {REPLY_LIMIT // (1024 * 1024)} MB",
                stdout=_truncate(stray),
            )
        reply = _parse_reply(bytes(stdout.reply).decode("utf-8", errors="replace"))
    if reply is None:
        if timed_out:
            logger.warning("sandboxed tool %s timed out after %ss", function, limit)
            return ToolResult(
                ok=False,
                error=f"TimeoutError: tool ran longer than {limit:g}s",
                timed_out=True,
                stdout=_truncate(stray),
            )
        return ToolResult(
            ok=False, error=_crash_error(proc.returncode, stderr.text()), stdout=_truncate(stray)
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
