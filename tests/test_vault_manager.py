"""Phase 3 tests — SkillManager.

We use a per-test tmp_path vault for full isolation. Because `load()` runs
the source file via `exec()` (not the import system), it works against any
vault directory — no need to touch the real talos/vault/ folder.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from talos.vault.manager import SkillManager, SkillEntry


@pytest.fixture
def manager(tmp_path) -> SkillManager:
    return SkillManager(vault_dir=tmp_path)


# --- manifest lifecycle ------------------------------------------------------

def test_manifest_created_on_init(tmp_path):
    mgr = SkillManager(vault_dir=tmp_path)
    assert mgr.manifest_path.exists()
    assert mgr.all() == []


def test_register_writes_file_and_manifest(manager: SkillManager, tmp_path: Path):
    entry: SkillEntry = {
        "name": "echo_tool",
        "description": "echoes input",
        "keywords": ["echo", "string"],
        "function": "echo_tool",
        "signature": "echo_tool(s: str) -> str",
    }
    code = "def echo_tool(s):\n    return s\n"
    saved = manager.register(entry, code)

    assert saved["created_at"]
    assert saved["usage_count"] == 0
    assert saved["last_used"] is None
    assert saved["file"] == "tools/echo_tool.py"

    # File is on disk
    assert (tmp_path / "tools" / "echo_tool.py").read_text() == code

    # Manifest contains exactly one entry
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert len(on_disk) == 1
    assert on_disk[0]["name"] == "echo_tool"


def test_register_replaces_existing_entry(manager: SkillManager):
    entry: SkillEntry = {"name": "foo", "function": "foo", "keywords": ["a"]}
    manager.register(entry, "def foo():\n    return 1\n")
    manager.register({**entry, "keywords": ["b"]}, "def foo():\n    return 2\n")

    all_entries = manager.all()
    assert len(all_entries) == 1
    assert all_entries[0]["keywords"] == ["b"]


def test_register_requires_name_and_function(manager: SkillManager):
    with pytest.raises(ValueError):
        manager.register({"function": "x"}, "def x(): pass")  # type: ignore[typeddict-item]
    with pytest.raises(ValueError):
        manager.register({"name": "x"}, "def x(): pass")  # type: ignore[typeddict-item]


# --- search ------------------------------------------------------------------

def test_search_ranks_by_overlap(manager: SkillManager):
    manager.register(
        {"name": "a", "function": "a", "keywords": ["csv", "parse"]},
        "def a(): pass\n",
    )
    manager.register(
        {"name": "b", "function": "b", "keywords": ["csv", "parse", "sort"]},
        "def b(): pass\n",
    )
    manager.register(
        {"name": "c", "function": "c", "keywords": ["yaml"]},
        "def c(): pass\n",
    )

    hits = manager.search(["csv", "parse", "sort"])
    names = [h["name"] for h in hits]
    assert names == ["b", "a"]  # b has 3 hits, a has 2, c excluded


def test_search_case_insensitive(manager: SkillManager):
    manager.register(
        {"name": "a", "function": "a", "keywords": ["CSV", "Parse"]},
        "def a(): pass\n",
    )
    assert len(manager.search(["csv"])) == 1


def test_search_empty_query_returns_empty(manager: SkillManager):
    manager.register(
        {"name": "a", "function": "a", "keywords": ["csv"]},
        "def a(): pass\n",
    )
    assert manager.search([]) == []
    assert manager.search([""]) == []


# --- load --------------------------------------------------------------------

def test_load_returns_working_callable(manager: SkillManager):
    manager.register(
        {"name": "adder", "function": "adder", "keywords": ["add"]},
        "def adder(a, b):\n    return a + b\n",
    )
    fn = manager.load("adder")
    assert callable(fn)
    assert fn(2, 3) == 5


def test_load_unknown_skill_raises(manager: SkillManager):
    with pytest.raises(KeyError):
        manager.load("does_not_exist")


def test_reload_picks_up_overwritten_code(manager: SkillManager):
    """The footgun test: re-register same name → next load() sees new code,
    not the cached old bytecode. Two writes within the same wall-clock
    second would otherwise hit Python's .pyc cache."""
    manager.register(
        {"name": "versioned", "function": "versioned", "keywords": ["v"]},
        "def versioned():\n    return 'v1'\n",
    )
    assert manager.load("versioned")() == "v1"

    manager.register(
        {"name": "versioned", "function": "versioned", "keywords": ["v"]},
        "def versioned():\n    return 'v2'\n",
    )
    assert manager.load("versioned")() == "v2"


# --- usage tracking ----------------------------------------------------------

def test_record_usage_bumps_counter_and_timestamp(manager: SkillManager):
    manager.register(
        {"name": "a", "function": "a", "keywords": ["x"]},
        "def a(): pass\n",
    )
    manager.record_usage("a")
    manager.record_usage("a")
    entry = manager.all()[0]
    assert entry["usage_count"] == 2
    assert entry["last_used"] is not None


def test_record_usage_unknown_is_silent(manager: SkillManager):
    manager.record_usage("nope")  # should not raise
