"""file_read / file_write primitives — wrappers around stdlib `open()`.

Concept:
- LangChain has `TextLoader` / `FileChain` document utilities. We don't use
  those — they wrap files in `Document` objects with metadata for RAG flows.
- We just need round-trip text I/O for the agent to read inputs and write
  outputs. UTF-8 throughout. Parent dirs auto-created on write so the agent
  doesn't need a separate "mkdir" primitive.
"""

from __future__ import annotations

from pathlib import Path


def file_read(path: str | Path) -> str:
    """Read a UTF-8 text file and return its contents.

    Raises FileNotFoundError if the path doesn't exist.
    """
    return Path(path).read_text(encoding="utf-8")


def file_write(path: str | Path, content: str) -> None:
    """Write `content` to `path` as UTF-8. Creates parent dirs if missing.

    Overwrites existing files without warning — by design; the agent owns
    its outputs. If we need append/safety later we add a separate primitive.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
