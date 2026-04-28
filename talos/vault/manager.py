"""SkillManager — the only component that touches vault state on disk.

Concept (LangChain/LangGraph context):
- LangChain has `BaseTool` / `StructuredTool` for LLM tool-calling. We're
  not using those because the Planner picks tools by *keyword search against
  the manifest*, not by the LLM tool-calling loop. So our "tool registry"
  is a JSON file + a folder of .py files, owned by this class.
- The manifest IS our schema. Each entry is a `SkillEntry` (TypedDict below).
- LangGraph stays out of this entirely — SkillManager is plain Python.
  Nodes will hold a reference to one shared SkillManager instance.

PydanticAI analogue: the metadata that `@agent.tool` accumulates at startup
(name, args, return type, docstring) — except here it's a JSON file the
*running agent* writes to at runtime.

Persistence design:
- Manifest writes go through tmp-file-then-rename so a crash mid-write
  cannot corrupt the index.
- `load()` uses importlib and handles the "module already cached" footgun:
  if a tool is re-registered (overwritten on disk), we must `reload()` so
  the next `load()` returns the new code, not the cached old object.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypedDict

from talos.config import settings


class SkillEntry(TypedDict, total=False):
    name: str                # unique identifier; matches the .py filename and the function name
    description: str         # one-liner used by Planner
    keywords: list[str]      # lowercase tokens for search
    file: str                # relative path within vault (e.g. "tools/csv_top_rows.py")
    function: str            # the symbol to call inside the file
    signature: str           # human-readable signature for prompts
    created_at: str          # ISO 8601
    usage_count: int
    last_used: str | None    # ISO 8601 or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SkillManager:
    """Read/write/search the on-disk skill vault.

    Cheap to construct — just opens (or creates) the manifest. Nodes can
    hold one shared instance for the whole graph run.
    """

    def __init__(self, vault_dir: Path | None = None) -> None:
        self.vault_dir: Path = Path(vault_dir) if vault_dir else settings.VAULT_DIR
        self.tools_dir: Path = self.vault_dir / "tools"
        self.manifest_path: Path = self.vault_dir / "manifest.json"

        # Make sure the layout exists. cheap & idempotent.
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write_manifest([])

    # ---- public API ---------------------------------------------------------

    def all(self) -> list[SkillEntry]:
        """Return every entry in the manifest. Mostly for tests/debugging."""
        return self._read_manifest()

    def search(self, keywords: list[str]) -> list[SkillEntry]:
        """Rank entries by lowercase keyword overlap.

        Args:
            keywords: query tokens (case-insensitive).

        Returns:
            Matching entries sorted by descending overlap count.
            Entries with zero overlap are excluded.
        """
        query = {k.lower() for k in keywords if k}
        if not query:
            return []
        scored: list[tuple[int, SkillEntry]] = []
        for entry in self._read_manifest():
            entry_kws = {k.lower() for k in entry.get("keywords", [])}
            score = len(query & entry_kws)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [entry for _, entry in scored]

    def register(self, entry: SkillEntry, code: str) -> SkillEntry:
        """Write the .py file and append/replace the manifest entry.

        If a tool with the same name already exists, both the file and the
        manifest entry are overwritten. The next `load()` will reload the
        module so callers always get the latest code.

        Args:
            entry: SkillEntry — `name` and `function` are required.
            code: full Python source for the tool's file.

        Returns:
            The finalised entry (with `created_at`, `usage_count`, `last_used` set).
        """
        if not entry.get("name"):
            raise ValueError("SkillEntry.name is required")
        if not entry.get("function"):
            raise ValueError("SkillEntry.function is required")

        name = entry["name"]
        rel_file = f"tools/{name}.py"
        full_file = self.vault_dir / rel_file
        full_file.write_text(code, encoding="utf-8")

        finalised: SkillEntry = {
            **entry,
            "file": rel_file,
            "created_at": entry.get("created_at") or _now_iso(),
            "usage_count": int(entry.get("usage_count", 0)),
            "last_used": entry.get("last_used"),
        }

        manifest = self._read_manifest()
        manifest = [e for e in manifest if e.get("name") != name]  # drop old if any
        manifest.append(finalised)
        self._write_manifest(manifest)
        return finalised

    def load(self, name: str) -> Callable[..., Any]:
        """Return the callable for a registered tool.

        Reads the source file as text and `exec()`s it into a fresh dict.
        We deliberately avoid the import system entirely because Python's
        .pyc cache uses second-resolution mtimes — two `register()` calls
        within the same second can otherwise serve stale bytecode (the
        Forger absolutely will hit this during retry loops). Plain `exec()`
        is cache-free, predictable, and fast enough for vault-sized files.
        """
        entry = self._find(name)
        if entry is None:
            raise KeyError(f"No skill named {name!r} in manifest")

        file_path = self.vault_dir / entry.get("file", f"tools/{name}.py")
        source = file_path.read_text(encoding="utf-8")
        namespace: dict[str, Any] = {"__name__": f"talos.vault.tools.{name}"}
        exec(compile(source, str(file_path), "exec"), namespace)

        fn_name = entry.get("function") or name
        if fn_name not in namespace:
            raise AttributeError(
                f"Skill {name!r} is registered with function {fn_name!r}, "
                f"but the file {file_path} defines no such symbol"
            )
        fn = namespace[fn_name]
        if not callable(fn):
            raise TypeError(f"Skill {name!r}: {fn_name!r} is not callable")
        return fn

    def record_usage(self, name: str) -> None:
        """Bump usage_count and stamp last_used. Silently no-ops if missing."""
        manifest = self._read_manifest()
        for entry in manifest:
            if entry.get("name") == name:
                entry["usage_count"] = int(entry.get("usage_count", 0)) + 1
                entry["last_used"] = _now_iso()
                break
        else:
            return
        self._write_manifest(manifest)

    # ---- internal helpers ---------------------------------------------------

    def _find(self, name: str) -> SkillEntry | None:
        for entry in self._read_manifest():
            if entry.get("name") == name:
                return entry
        return None

    def _read_manifest(self) -> list[SkillEntry]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Vault manifest at {self.manifest_path} is corrupted: {e}"
            ) from e
        if not isinstance(data, list):
            raise RuntimeError(
                f"Vault manifest at {self.manifest_path} must be a JSON list, got {type(data).__name__}"
            )
        return data  # type: ignore[return-value]

    def _write_manifest(self, manifest: list[SkillEntry]) -> None:
        """Atomic write: tmp file → rename."""
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(tmp, self.manifest_path)
