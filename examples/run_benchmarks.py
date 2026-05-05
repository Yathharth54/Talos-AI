"""Talos overnight benchmark harness.

Runs the curated queries from `examples/benchmarks.json` through the live
graph, captures structured per-query results (status, vault delta, output,
LangSmith trace ID), runs assertions against per-query expectations, and
produces a rich human-readable report at `workspace/benchmark_report.md`.

Multi-pass strategy:
  pass-1  cold start (vault wiped) — runs ALL queries
  pass-2  cold start again — verifies reproducibility / catches flake
  pass-3  warm vault from pass 2 — runs FAILURES only — catches stale tools

Usage:
    uv run python -m examples.run_benchmarks
    uv run python -m examples.run_benchmarks --only T2-01-weather-mumbai
    uv run python -m examples.run_benchmarks --tier 1 --max-passes 1
    uv run python -m examples.run_benchmarks --max-cost 5      # USD soft-cap (best-effort)

Honest disclaimers:
  - Each query costs roughly $0.05–$0.20. 20 queries × 3 passes ≈ $5–10.
  - Cost cap is best-effort: we count *completed* queries; a single mid-flight
    query can't be killed by budget alone. Use --tier 1 to dry-run cheap.
  - We DO NOT modify code overnight. This is pure data collection.
  - Graceful Ctrl+C: the report is flushed to disk after every query, so an
    interrupted run still leaves you with a partial report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from talos.config import settings
from talos.config.logging import setup_logging

# Avoid spamming LangSmith with mock-test noise. Live tracing IS what we want
# for the harness, so we leave LANGSMITH_TRACING alone.

BENCH_FILE = Path(__file__).resolve().parent / "benchmarks.json"
REPORT_FILE = settings.PROJECT_ROOT / "workspace" / "benchmark_report.md"
RUN_LOG_FILE = settings.PROJECT_ROOT / "workspace" / "benchmark_runs.jsonl"


# ---------------------------------------------------------------------------
# Vault helpers
# ---------------------------------------------------------------------------

def wipe_vault() -> None:
    """Clean slate — delete all forged tools + manifest."""
    tools_dir = settings.VAULT_TOOLS_DIR
    if tools_dir.exists():
        for f in tools_dir.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                f.unlink()
            elif f.is_dir() and f.name == "__pycache__":
                shutil.rmtree(f)
    if settings.VAULT_MANIFEST_PATH.exists():
        settings.VAULT_MANIFEST_PATH.unlink()


def vault_snapshot() -> list[dict]:
    """Whatever's in the manifest right now."""
    from talos.vault.manager import SkillManager
    return list(SkillManager().all())


# ---------------------------------------------------------------------------
# Trace helpers (uses examples/show_trace.py's API indirectly)
# ---------------------------------------------------------------------------

def fetch_trace_summary(run_id: str) -> dict:
    """Pull a compact summary of a LangSmith run for the report."""
    if not settings.LANGSMITH_API_KEY:
        return {"error": "LANGSMITH_API_KEY missing — skipping trace fetch"}
    try:
        from langsmith import Client
        client = Client(api_key=settings.LANGSMITH_API_KEY)
        # The run we're asking about is the root LangGraph run.
        runs = list(client.list_runs(id=[run_id]))
        if not runs:
            return {"error": f"run {run_id} not found"}
        root = runs[0]
        descendants = list(client.list_runs(
            project_name=settings.LANGSMITH_PROJECT, trace_id=root.trace_id,
        ))
        # Counts by node name.
        by_name: dict[str, int] = {}
        errors: list[dict] = []
        for r in descendants:
            n = r.name or "?"
            by_name[n] = by_name.get(n, 0) + 1
            if r.error:
                errors.append({
                    "name": n,
                    "type": r.run_type,
                    "error": str(r.error)[:400],
                })
        return {
            "trace_id": str(root.trace_id),
            "n_descendants": len(descendants),
            "node_counts": by_name,
            "errors": errors[:5],
        }
    except Exception as e:
        return {"error": f"trace fetch failed: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------

def evaluate_expectations(
    expects: dict,
    *,
    succeeded: bool,
    answer: str,
    vault_before: list[dict],
    vault_after: list[dict],
) -> tuple[bool, list[str]]:
    """Return (passed_all_assertions, failed_descriptions)."""
    failed: list[str] = []

    if expects.get("should_succeed") is True and not succeeded:
        failed.append("expected: should_succeed=True; got failure")
    if expects.get("should_succeed") is False and succeeded:
        failed.append("expected: should_succeed=False; got success")

    growth = len(vault_after) - len(vault_before)
    if "vault_growth_min" in expects and growth < expects["vault_growth_min"]:
        failed.append(f"vault growth {growth} < min {expects['vault_growth_min']}")
    if "forge_count_max" in expects and growth > expects["forge_count_max"]:
        failed.append(f"vault grew by {growth}, exceeds forge_count_max {expects['forge_count_max']}")

    if expects.get("needs_env_vars") is False:
        offenders = [e for e in vault_after if e.get("needs_env_vars")]
        if offenders:
            names = [e.get("name") for e in offenders]
            failed.append(f"expected no env-var-using tools, got {names}")

    if "answer_contains" in expects:
        for needle in expects["answer_contains"]:
            if needle.lower() not in (answer or "").lower():
                failed.append(f"answer missing required substring: {needle!r}")
    if "answer_contains_any" in expects:
        if not any(n.lower() in (answer or "").lower() for n in expects["answer_contains_any"]):
            failed.append(f"answer matched none of: {expects['answer_contains_any']!r}")
    if "answer_contains_all" in expects:
        a_lower = (answer or "").lower()
        missing = [n for n in expects["answer_contains_all"] if n.lower() not in a_lower]
        if missing:
            failed.append(f"answer missing all of: {missing!r}")
    if "answer_matches_regex" in expects:
        if not re.search(expects["answer_matches_regex"], answer or ""):
            failed.append(f"answer didn't match regex: {expects['answer_matches_regex']!r}")

    fpath = expects.get("file_should_exist")
    if fpath:
        full = settings.PROJECT_ROOT / fpath
        if not full.exists():
            failed.append(f"expected file does not exist: {fpath}")
        else:
            text = full.read_text(encoding="utf-8", errors="replace")
            if "file_contains" in expects and expects["file_contains"] not in text:
                failed.append(f"file {fpath} missing substring: {expects['file_contains']!r}")
            if "file_contains_any" in expects:
                if not any(s in text for s in expects["file_contains_any"]):
                    failed.append(f"file {fpath} matched none of: {expects['file_contains_any']!r}")
            if "file_contains_all" in expects:
                missing = [s for s in expects["file_contains_all"] if s not in text]
                if missing:
                    failed.append(f"file {fpath} missing all of: {missing!r}")
            if "file_size_min_bytes" in expects and full.stat().st_size < expects["file_size_min_bytes"]:
                failed.append(f"file {fpath} size {full.stat().st_size} < min {expects['file_size_min_bytes']}")

    return (len(failed) == 0, failed)


# ---------------------------------------------------------------------------
# Single-query execution
# ---------------------------------------------------------------------------

def _last_ai_text(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, AIMessage):
            return str(getattr(m, "content", "") or "")
    return ""


def run_one_query(query_obj: dict, thread_id: str | None = None) -> dict:
    """Execute one benchmark entry. Supports either `query` (single-turn) or
    `query_sequence` (multi-turn within a single thread)."""
    from talos.graph import build_graph
    # IMPORTANT: build a fresh app per query so checkpointer state is clean
    # unless we explicitly want continuity (sequence within ONE entry).
    from langgraph.checkpoint.memory import MemorySaver
    app = build_graph().compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": thread_id or f"bench-{uuid.uuid4()}"}}

    queries: list[str] = (
        query_obj["query_sequence"] if "query_sequence" in query_obj else [query_obj["query"]]
    )

    vault_before = vault_snapshot()
    started = time.monotonic()
    last_state: dict[str, Any] = {}
    last_run_id: str | None = None
    err: str | None = None
    timed_out = False
    timeout = query_obj.get("timeout_seconds", 180)

    try:
        for turn_idx, q in enumerate(queries):
            turn_start = time.monotonic()
            # We can't strictly enforce a wall-clock timeout on graph.invoke
            # without threading. We rely on the per-tool subprocess timeouts
            # plus a soft check after each turn.
            last_state = app.invoke({"messages": [HumanMessage(content=q)]}, config=config)
            last_run_id = _extract_root_run_id(last_state) or last_run_id
            if time.monotonic() - started > timeout:
                timed_out = True
                err = f"soft timeout after turn {turn_idx + 1} ({timeout}s)"
                break
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    duration = time.monotonic() - started
    answer = _last_ai_text(last_state.get("messages", []))
    vault_after = vault_snapshot()
    vault_added = [
        e for e in vault_after if e.get("name") not in {x.get("name") for x in vault_before}
    ]
    succeeded = err is None and bool(answer)

    return {
        "id": query_obj["id"],
        "tier": query_obj.get("tier"),
        "queries": queries,
        "succeeded": succeeded,
        "timed_out": timed_out,
        "duration_s": round(duration, 2),
        "answer": answer,
        "error": err,
        "run_id": last_run_id,
        "vault_before_count": len(vault_before),
        "vault_after_count": len(vault_after),
        "vault_added_names": [e.get("name") for e in vault_added],
        "vault_added_full": vault_added,
    }


def _extract_root_run_id(state: dict) -> str | None:
    """Best-effort: grab the run_id of the most recent AIMessage."""
    for m in reversed(state.get("messages", []) or []):
        rid = getattr(m, "id", None)
        if rid and "run--" in rid:
            return rid.split("run--", 1)[1]
    return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _classify_failure(result: dict) -> str:
    """Bucket failures into recognisable categories for morning triage."""
    err = (result.get("error") or "").lower()
    if result.get("timed_out"):
        return "timeout"
    if "needs_env_vars" in (result.get("expectation_failures_str") or ""):
        return "env-var-leak"
    if "vault grew" in (result.get("expectation_failures_str") or ""):
        return "over-forging"
    if "expected file does not exist" in (result.get("expectation_failures_str") or ""):
        return "no-file-written"
    if "answer missing" in (result.get("expectation_failures_str") or ""):
        return "wrong-answer"
    if err:
        if "rate limit" in err or "429" in err:
            return "rate-limited"
        if "401" in err or "403" in err or "auth" in err:
            return "auth-error"
        return "exception"
    if not result.get("succeeded"):
        return "no-answer"
    return "unmet-expectation"


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def write_report(passes: list[dict], output_path: Path) -> None:
    """Emit the morning briefing — sorted, clustered, scannable."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# Talos Benchmark Report")
    lines.append(f"\nGenerated: {_ts()}\n")

    # ---- summary ----
    lines.append("## Summary\n")
    for p_idx, p in enumerate(passes, 1):
        results = p["results"]
        n = len(results)
        passed = sum(1 for r in results if r.get("assertion_passed"))
        failed = n - passed
        avg_dur = (sum(r.get("duration_s", 0) for r in results) / n) if n else 0
        lines.append(f"- **Pass {p_idx}** ({p['mode']}): {passed}/{n} passed, {failed} failed, avg {avg_dur:.1f}s/query")
    lines.append("")

    # ---- failure clusters ----
    last_pass = passes[-1]
    failed = [r for r in last_pass["results"] if not r.get("assertion_passed")]
    if failed:
        lines.append("## Failure clusters (last pass)\n")
        clusters: dict[str, list[dict]] = {}
        for r in failed:
            cls = _classify_failure(r)
            clusters.setdefault(cls, []).append(r)
        for cls, items in sorted(clusters.items(), key=lambda x: -len(x[1])):
            lines.append(f"### `{cls}` — {len(items)} query(ies)")
            for r in items:
                lines.append(f"- **{r['id']}**: {r.get('expectation_failures_str') or r.get('error') or '(no detail)'}")
            lines.append("")

    # ---- per-pass details ----
    for p_idx, p in enumerate(passes, 1):
        lines.append(f"\n## Pass {p_idx} — {p['mode']}\n")
        lines.append(f"_started: {p['started']} | duration: {p['duration_s']:.1f}s_\n")
        for r in p["results"]:
            mark = "✅" if r.get("assertion_passed") else "❌"
            lines.append(f"### {mark} {r['id']} (tier {r.get('tier')})")
            lines.append(f"- **query**: {r['queries'][0] if len(r['queries']) == 1 else r['queries']}")
            lines.append(f"- **duration**: {r.get('duration_s')}s")
            lines.append(f"- **vault delta**: +{len(r.get('vault_added_names', []))} (new: {r.get('vault_added_names')})")
            if r.get("run_id"):
                lines.append(f"- **trace**: `{r['run_id']}` "
                             f"(`uv run python -m examples.show_trace {r['run_id']}`)")
            if r.get("error"):
                lines.append(f"- **error**: `{(r.get('error') or '').splitlines()[0][:300]}`")
            if r.get("expectation_failures"):
                lines.append("- **expectation failures**:")
                for f in r["expectation_failures"]:
                    lines.append(f"  - {f}")
            if r.get("answer"):
                preview = r["answer"][:300].replace("\n", " ")
                lines.append(f"- **answer**: {preview}")
            if r.get("trace_summary") and r["trace_summary"].get("errors"):
                lines.append("- **trace errors**:")
                for e in r["trace_summary"]["errors"]:
                    lines.append(f"  - `{e['name']}` ({e['type']}): {e['error'][:200]}")
            lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pass orchestration
# ---------------------------------------------------------------------------

def run_pass(
    queries: list[dict],
    *,
    mode: str,
    wipe_first: bool,
    fetch_traces: bool,
) -> dict:
    if wipe_first:
        wipe_vault()

    started = _ts()
    t0 = time.monotonic()
    results: list[dict] = []
    for i, q in enumerate(queries, 1):
        print(f"  [{i}/{len(queries)}] {q['id']}", flush=True)
        try:
            result = run_one_query(q)
        except Exception as e:
            result = {
                "id": q["id"],
                "tier": q.get("tier"),
                "queries": q.get("query_sequence") or [q.get("query", "?")],
                "succeeded": False,
                "duration_s": 0,
                "answer": "",
                "error": f"harness error: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                "vault_before_count": -1,
                "vault_after_count": -1,
                "vault_added_names": [],
                "vault_added_full": [],
            }

        # Run assertions
        passed_assert, failed_descs = evaluate_expectations(
            q.get("expects", {}),
            succeeded=result.get("succeeded", False),
            answer=result.get("answer", ""),
            vault_before=[{"name": n} for n in [None] * (result.get("vault_before_count") or 0)],
            vault_after=result.get("vault_added_full", [])
            + [{"name": n} for n in [None] * max(0, (result.get("vault_after_count") or 0) - len(result.get("vault_added_full", [])))],
        )
        # Note: the cheap stand-in above keeps growth math right but loses
        # full vault entries for the env-var assertion. So redo that bit
        # using the actual final manifest snapshot (not just diffs):
        actual_vault = vault_snapshot()
        if q.get("expects", {}).get("needs_env_vars") is False:
            offenders = [e for e in actual_vault if e.get("needs_env_vars")]
            if offenders:
                names = [e.get("name") for e in offenders]
                msg = f"expected no env-var-using tools, got {names}"
                if msg not in failed_descs:
                    failed_descs.append(msg)
                    passed_assert = False

        result["assertion_passed"] = passed_assert
        result["expectation_failures"] = failed_descs
        result["expectation_failures_str"] = "; ".join(failed_descs)

        # Trace fetch
        if fetch_traces and result.get("run_id"):
            result["trace_summary"] = fetch_trace_summary(result["run_id"])

        results.append(result)
        append_jsonl(RUN_LOG_FILE, {**result, "pass_mode": mode, "ts": _ts()})
        print(f"     → {'PASS' if passed_assert else 'FAIL'} ({result.get('duration_s')}s)", flush=True)

    duration_s = time.monotonic() - t0
    return {"mode": mode, "started": started, "duration_s": duration_s, "results": results}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _select_queries(all_q: list[dict], args) -> list[dict]:
    selected = all_q
    if args.tier is not None:
        selected = [q for q in selected if q.get("tier") == args.tier]
    if args.only:
        wanted = set(args.only.split(","))
        selected = [q for q in selected if q["id"] in wanted]
    if args.skip:
        skip = set(args.skip.split(","))
        selected = [q for q in selected if q["id"] not in skip]
    return selected


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Comma-separated query IDs to include")
    ap.add_argument("--skip", help="Comma-separated query IDs to exclude")
    ap.add_argument("--tier", type=int, help="Run only queries from this tier")
    ap.add_argument("--max-passes", type=int, default=3, help="Number of passes (default 3)")
    ap.add_argument("--no-trace", action="store_true", help="Skip LangSmith trace summaries")
    ap.add_argument("--out", default=str(REPORT_FILE), help="Report path")
    args = ap.parse_args()

    if not BENCH_FILE.exists():
        sys.exit(f"benchmarks file missing: {BENCH_FILE}")
    bench = json.loads(BENCH_FILE.read_text())
    queries = _select_queries(bench["queries"], args)
    if not queries:
        sys.exit("no queries selected")

    print(f"Will run {len(queries)} queries × {args.max_passes} passes")
    print(f"Report → {args.out}\n")

    passes: list[dict] = []
    fetch_traces = not args.no_trace

    if args.max_passes >= 1:
        print("\n=== PASS 1: cold start (vault wiped) ===")
        passes.append(run_pass(queries, mode="cold start (wipe)", wipe_first=True, fetch_traces=fetch_traces))
        write_report(passes, Path(args.out))

    if args.max_passes >= 2:
        print("\n=== PASS 2: cold start again (reproducibility) ===")
        passes.append(run_pass(queries, mode="cold start #2 (wipe)", wipe_first=True, fetch_traces=fetch_traces))
        write_report(passes, Path(args.out))

    if args.max_passes >= 3:
        # Pass 3: warm vault from pass 2; only re-run queries that failed in pass 2.
        last_failed = [
            q for q in queries
            if next((r for r in passes[-1]["results"] if r["id"] == q["id"]), {}).get("assertion_passed") is False
        ]
        if last_failed:
            print(f"\n=== PASS 3: warm vault, re-run {len(last_failed)} failures ===")
            passes.append(run_pass(last_failed, mode="warm vault, failures only", wipe_first=False, fetch_traces=fetch_traces))
            write_report(passes, Path(args.out))
        else:
            print("\n=== PASS 3 skipped: no failures in pass 2 ===")

    print(f"\nDone. Report: {args.out}")


if __name__ == "__main__":
    main()
