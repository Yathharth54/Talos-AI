"""shell_exec primitive — run a shell command in a subprocess with a timeout.

Same shape as python_exec. Returned errors are data, not exceptions.

Security note: `shell=True` means shell metacharacters (|, &, $) are honored.
This is intentional for the POC — the agent needs pipes/redirects to do
useful work. Real isolation comes via Docker in Phase 3 (deferred).
"""

from __future__ import annotations

import subprocess

from talos.config import settings


def shell_exec(command: str, timeout: int | None = None) -> dict:
    """Run `command` via /bin/sh.

    Returns the same dict shape as python_exec.
    """
    t = timeout if timeout is not None else settings.SUBPROCESS_TIMEOUT
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=t,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "returncode": None,
            "stdout": _coerce(e.stdout),
            "stderr": _coerce(e.stderr),
            "timed_out": True,
        }

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "timed_out": False,
    }


def _coerce(x: object) -> str:
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x)
