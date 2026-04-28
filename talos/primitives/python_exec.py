"""python_exec primitive — run Python code in a subprocess with a timeout.

Concept:
- This is the *only* sandbox in the POC. Not airtight — just a subprocess
  with a wall-clock timeout. CLAUDE.md acknowledges this limitation.
- Errors return as data, not exceptions. The Tester (Phase 4) reads the
  result dict and decides whether the forged code passed.
- We deliberately don't use LangChain's `PythonREPLTool`: it runs in-process
  via `exec()` — no isolation, can't enforce a timeout cleanly, and can
  contaminate the parent's globals. Subprocess is safer.
"""

from __future__ import annotations

import subprocess
import sys

from talos.config import settings


def python_exec(code: str, timeout: int | None = None) -> dict:
    """Execute Python `code` in a fresh subprocess.

    Args:
        code: Python source to run. Whole stdin is fed to `python -c`.
        timeout: seconds; defaults to settings.SUBPROCESS_TIMEOUT.

    Returns:
        {
          "ok":          bool — true iff exit 0 AND no timeout,
          "returncode":  int | None — None if timed out,
          "stdout":      str,
          "stderr":      str,
          "timed_out":   bool,
        }
    """
    t = timeout if timeout is not None else settings.SUBPROCESS_TIMEOUT
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=t,
        )
    except subprocess.TimeoutExpired as e:
        # `e.stdout` / `e.stderr` may be bytes or None depending on platform.
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
