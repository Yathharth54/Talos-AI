"""file_read / file_write primitives — wrappers around stdlib `open()`.

Path policy (introduced after files kept landing in unpredictable places):
- ABSOLUTE paths are respected as-is. The user's explicit choice wins.
- RELATIVE paths (and bare filenames like "report.md") are anchored to
  `settings.WORKSPACE_DIR`. The workspace is gitignored, so Talos can't
  accidentally commit garbage into the repo.

This keeps user agency for "/tmp/foo" while corralling the LLM's habit
of writing to cwd or wherever.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from talos.config import settings

log = logging.getLogger(__name__)


def _resolve(path: str | Path) -> Path:
    """Anchor relative paths to the workspace; respect absolute paths."""
    p = Path(path)
    if p.is_absolute():
        return p
    return settings.WORKSPACE_DIR / p


def _encode(content: Any) -> str:
    """Coerce arbitrary content to a UTF-8 string for writing.

    Forged tools commonly return dicts/lists. Rather than force every caller
    to remember to str/json.dumps, file_write does the obvious thing:
        str / bytes  -> as-is (decoded)
        dict / list  -> json.dumps with indent=2 and default=str (datetimes etc.)
        anything else -> repr(), with a warning logged
    """
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        return content.decode("utf-8")
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2, default=str, ensure_ascii=False)
    log.warning("file_write received unsupported type %s; falling back to repr()", type(content).__name__)
    return repr(content)


def file_read(path: str | Path) -> str:
    """Read a UTF-8 text file. Relative paths resolve under WORKSPACE_DIR."""
    return _resolve(path).read_text(encoding="utf-8")


def file_write(path: str | Path, content: Any) -> None:
    """Write `content` to `path` as UTF-8. Relative paths resolve under
    WORKSPACE_DIR. Creates parent dirs if missing.

    Accepts str, bytes, dict, or list. Dicts/lists are JSON-encoded
    (indent=2, default=str) so callers can write structured data without
    a separate serialisation step. Overwrites existing files.
    """
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_encode(content), encoding="utf-8")
