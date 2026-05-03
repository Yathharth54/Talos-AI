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

from pathlib import Path

from talos.config import settings


def _resolve(path: str | Path) -> Path:
    """Anchor relative paths to the workspace; respect absolute paths."""
    p = Path(path)
    if p.is_absolute():
        return p
    return settings.WORKSPACE_DIR / p


def file_read(path: str | Path) -> str:
    """Read a UTF-8 text file. Relative paths resolve under WORKSPACE_DIR."""
    return _resolve(path).read_text(encoding="utf-8")


def file_write(path: str | Path, content: str) -> None:
    """Write `content` to `path` as UTF-8. Relative paths resolve under
    WORKSPACE_DIR. Creates parent dirs if missing.

    Overwrites existing files without warning — the agent owns its outputs.
    """
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
