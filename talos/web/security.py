"""Keep API key values out of logs (spec 02 §10).

A key pasted into the key dialog reaches the server once, in the `/resume`
body. The route calls `remember_secret(value)` before anything else, and
`install_log_redaction()` wraps the logging record factory so every log
record, from any logger or handler (uvicorn's included), has remembered
values replaced by `[redacted]` before it is formatted or stored.
"""

from __future__ import annotations

import logging
from typing import Any

REDACTED = "[redacted]"
_MIN_SECRET = 4
_secrets: set[str] = set()
_installed = False


def remember_secret(value: str | None) -> None:
    """Redact `value` from every log record from now on (process lifetime)."""
    if value and len(value.strip()) >= _MIN_SECRET:
        _secrets.add(value.strip())
        if value != value.strip():
            _secrets.add(value)


def redact(text: str) -> str:
    """`text` with every remembered secret replaced by `[redacted]`."""
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def install_log_redaction() -> None:
    """Wrap the log record factory once so remembered secrets never reach a handler."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if _secrets:
            try:
                message = record.getMessage()
            except Exception:  # noqa: BLE001 - a bad format string is not our problem
                return record
            cleaned = redact(message)
            if cleaned != message:
                record.msg, record.args = cleaned, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
