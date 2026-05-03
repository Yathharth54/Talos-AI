"""Fetch and pretty-print Talos LangSmith traces from the CLI.

Why this exists: LangSmith has no official MCP server, so Claude can't read
your traces directly. This script dumps a trace as plain text so you can
either read it yourself or paste it into a chat for debugging.

Usage:
    uv run python -m examples.show_trace               # latest root run, full
    uv run python -m examples.show_trace --list        # list 10 recent runs
    uv run python -m examples.show_trace <run_id>      # specific run, full
    uv run python -m examples.show_trace --list 25     # list 25 recent

Requires LANGSMITH_API_KEY in .env (already there).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from langsmith import Client

from talos.config import settings


def _client() -> Client:
    if not settings.LANGSMITH_API_KEY:
        sys.exit("LANGSMITH_API_KEY missing in environment")
    return Client(api_key=settings.LANGSMITH_API_KEY)


def _short(s: Any, n: int = 80) -> str:
    text = str(s).replace("\n", " ")
    return text if len(text) <= n else text[:n] + "..."


def _dumps(obj: Any, max_chars: int = 4000) -> str:
    """JSON dump with deep truncation of long string values inside the structure."""
    try:
        text = json.dumps(obj, default=str, indent=2, ensure_ascii=False)
    except Exception:
        text = repr(obj)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...(truncated, {len(text) - max_chars} more chars)"
    return text


def _fmt_time(t) -> str:
    if t is None:
        return "?"
    if isinstance(t, datetime):
        return t.astimezone(timezone.utc).strftime("%H:%M:%S")
    return str(t)


def list_runs(client: Client, project: str, limit: int) -> None:
    runs = client.list_runs(project_name=project, is_root=True, limit=limit)
    runs = list(runs)
    if not runs:
        print(f"(no runs found in project {project!r})")
        return
    print(f"{'time':<10} {'status':<10} {'name':<25} preview")
    print("-" * 100)
    for r in runs:
        status = "ERROR" if r.error else (r.status or "ok")
        preview = ""
        if r.inputs and isinstance(r.inputs, dict):
            msgs = r.inputs.get("messages") or []
            if msgs and isinstance(msgs, list):
                last = msgs[-1] if msgs else {}
                preview = _short(
                    last.get("content")
                    or last.get("kwargs", {}).get("content")
                    or last,
                    60,
                )
        print(f"{_fmt_time(r.start_time):<10} {status:<10} {_short(r.name, 25):<25} {preview}")
        print(f"           id={r.id}")


def show_run(client: Client, run_id: str) -> None:
    runs = list(client.list_runs(id=[run_id]))
    if not runs:
        sys.exit(f"run {run_id} not found")
    root = runs[0]

    descendants = list(client.list_runs(
        project_name=settings.LANGSMITH_PROJECT,
        trace_id=root.trace_id,
    ))
    descendants.sort(key=lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc))

    print(f"=== Trace {root.trace_id} — {root.name} ===")
    print(f"start: {_fmt_time(root.start_time)}   status: {'ERROR' if root.error else (root.status or 'ok')}")
    print(f"runs:  {len(descendants)}")
    if root.error:
        print(f"\nROOT ERROR:\n{root.error}")
    print()

    # Print each run's name, type, inputs, outputs, error.
    for i, r in enumerate(descendants):
        depth = _depth_of(r, descendants)
        indent = "  " * depth
        status = "ERROR" if r.error else (r.run_type or "ok")
        print(f"{indent}[{i}] {r.name}  ({status})  {_fmt_time(r.start_time)}")
        if r.inputs:
            print(f"{indent}  inputs:  {_dumps(r.inputs, 1200)}")
        if r.outputs:
            print(f"{indent}  outputs: {_dumps(r.outputs, 1200)}")
        if r.error:
            print(f"{indent}  error:   {r.error}")
        print()


def _depth_of(run, all_runs) -> int:
    by_id = {r.id: r for r in all_runs}
    depth = 0
    cur = run
    while getattr(cur, "parent_run_id", None):
        parent = by_id.get(cur.parent_run_id)
        if parent is None:
            break
        depth += 1
        cur = parent
    return depth


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch and dump LangSmith traces")
    ap.add_argument("target", nargs="?", help="run ID, or omit to show latest root run")
    ap.add_argument("--list", type=int, nargs="?", const=10,
                    help="List N most recent root runs (default 10) instead of dumping one")
    ap.add_argument("--project", default=settings.LANGSMITH_PROJECT,
                    help="LangSmith project name")
    args = ap.parse_args()

    client = _client()

    if args.list is not None:
        list_runs(client, args.project, args.list)
        return

    target = args.target
    if not target:
        latest = list(client.list_runs(
            project_name=args.project, is_root=True, limit=1,
        ))
        if not latest:
            sys.exit(f"no runs in project {args.project!r}")
        target = str(latest[0].id)
        print(f"(showing latest run: {target})\n")

    show_run(client, target)


if __name__ == "__main__":
    main()
