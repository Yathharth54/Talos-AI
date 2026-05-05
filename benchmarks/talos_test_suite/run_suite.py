"""Talos end-to-end test-suite runner — drives queries.json through the live graph.

Differences from examples/run_benchmarks.py:
  - Suite-aware: per-query bash setup steps (creates fixture files like /tmp/sales.csv).
  - Warm-vault by default: queries Q12+ depend on tools forged by Q06–Q11. We wipe
    once at the start of the run, then keep the vault across queries so the reuse
    tests (Q12, Q31, Q63 etc.) actually exercise reuse.
  - HITL-aware: queries with `requires_hitl=true` are skipped by default (use
    --include-hitl to opt in; you'll need to drive the interrupt yourself).
  - --model flag: overrides OPENAI_MODEL env var BEFORE talos imports load settings.
  - Long-input expansion: handles `query_repeat` for Q45.

Usage:
    uv run python -m benchmarks.talos_test_suite.run_suite
    uv run python -m benchmarks.talos_test_suite.run_suite --only Q01,Q06,Q12
    uv run python -m benchmarks.talos_test_suite.run_suite --category 2
    uv run python -m benchmarks.talos_test_suite.run_suite --model gpt-5.1 --no-trace
    uv run python -m benchmarks.talos_test_suite.run_suite --wipe-each   # cold-start every query
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
SUITE_FILE = HERE / "queries.json"
REPORT_FILE = PROJECT_ROOT / "workspace" / "suite_report.md"
RUN_LOG_FILE = PROJECT_ROOT / "workspace" / "suite_runs.jsonl"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def expand_query(q: dict) -> str:
    """Resolve `query` or expand `query_repeat`."""
    if "query" in q and q["query"] is not None:
        return q["query"]
    qr = q.get("query_repeat")
    if not qr:
        raise ValueError(f"{q['id']}: neither query nor query_repeat set")
    return qr["prefix"] + (qr["repeat"] * int(qr["times"]))


def run_setup(q: dict) -> str | None:
    """Execute the per-query bash setup. Returns error text on failure."""
    cmd = q.get("setup")
    if not cmd:
        return None
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "setup timed out (>30s)"
    if r.returncode != 0:
        return f"setup exit {r.returncode}: {r.stderr.strip() or r.stdout.strip()}"
    return None


def select(queries: list[dict], args) -> list[dict]:
    out = queries
    if args.category is not None:
        out = [q for q in out if q.get("category") == args.category]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        out = [q for q in out if q["id"] in wanted]
    if args.skip:
        skip = {s.strip() for s in args.skip.split(",")}
        out = [q for q in out if q["id"] not in skip]
    if not args.include_hitl:
        out = [q for q in out if not q.get("requires_hitl")]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Comma-separated query IDs (e.g. Q01,Q06,Q12)")
    ap.add_argument("--skip", help="Comma-separated query IDs to exclude")
    ap.add_argument("--category", type=int, help="Run only queries from this category (1-11)")
    ap.add_argument("--include-hitl", action="store_true",
                    help="Include human-input queries (Q35-Q37); you must drive the interrupt")
    ap.add_argument("--wipe-each", action="store_true",
                    help="Wipe vault before EVERY query (default: wipe once at start, warm vault after)")
    ap.add_argument("--no-wipe", action="store_true", help="Do not wipe vault at all")
    ap.add_argument("--no-trace", action="store_true", help="Skip LangSmith trace summaries")
    ap.add_argument("--model", help="Override OPENAI_MODEL for this run (e.g. gpt-5.1)")
    ap.add_argument("--out", default=str(REPORT_FILE), help="Report path")
    args = ap.parse_args()

    # Apply model override BEFORE importing talos (settings reads env at import time).
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
        print(f"[suite] OPENAI_MODEL = {args.model}")

    # Late imports so the env override above takes effect.
    from talos.config.logging import setup_logging
    from examples.run_benchmarks import (
        evaluate_expectations, fetch_trace_summary, run_one_query,
        vault_snapshot, wipe_vault, write_report, append_jsonl, _classify_failure,
    )
    setup_logging()

    if not SUITE_FILE.exists():
        sys.exit(f"missing suite file: {SUITE_FILE}")
    spec = json.loads(SUITE_FILE.read_text())
    queries = select(spec["queries"], args)
    if not queries:
        sys.exit("no queries selected")

    print(f"Will run {len(queries)} queries (model={os.environ.get('OPENAI_MODEL', 'gpt-4o')})")
    print(f"Report → {args.out}")
    skipped = [q["id"] for q in spec["queries"] if q.get("requires_hitl") and not args.include_hitl]
    if skipped:
        print(f"Skipping HITL queries (use --include-hitl to opt in): {skipped}")

    if not args.no_wipe and not args.wipe_each:
        print("[suite] wiping vault once at start (warm vault after)")
        wipe_vault()

    started = _ts()
    t0 = time.monotonic()
    results: list[dict] = []
    fetch_traces = not args.no_trace

    for i, q in enumerate(queries, 1):
        print(f"  [{i}/{len(queries)}] {q['id']} — {q.get('title', '')}", flush=True)

        if args.wipe_each:
            wipe_vault()

        # Per-query setup (idempotent shell command).
        setup_err = run_setup(q)
        if setup_err:
            print(f"     ! setup failed: {setup_err}", flush=True)

        # Materialise the query string (handles query_repeat for Q45).
        try:
            q_text = expand_query(q)
        except Exception as e:
            print(f"     ! cannot expand query: {e}", flush=True)
            continue

        query_obj = {**q, "query": q_text}

        try:
            result = run_one_query(query_obj)
        except Exception as e:
            result = {
                "id": q["id"], "tier": q.get("category"),
                "queries": [q_text[:200]],
                "succeeded": False, "duration_s": 0, "answer": "",
                "error": f"harness error: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                "vault_before_count": -1, "vault_after_count": -1,
                "vault_added_names": [], "vault_added_full": [],
            }

        passed_assert, failed_descs = evaluate_expectations(
            q.get("expects", {}),
            succeeded=result.get("succeeded", False),
            answer=result.get("answer", ""),
            vault_before=[{"name": n} for n in [None] * (result.get("vault_before_count") or 0)],
            vault_after=result.get("vault_added_full", []) + [
                {"name": n} for n in [None] * max(
                    0, (result.get("vault_after_count") or 0) - len(result.get("vault_added_full", []))
                )
            ],
        )
        # `file_contains_all` is supported by evaluate_expectations already.
        if setup_err:
            failed_descs.append(f"setup error: {setup_err}")
            passed_assert = False

        result["assertion_passed"] = passed_assert
        result["expectation_failures"] = failed_descs
        result["expectation_failures_str"] = "; ".join(failed_descs)
        result["category"] = q.get("category")
        result["title"] = q.get("title", "")

        if fetch_traces and result.get("run_id"):
            result["trace_summary"] = fetch_trace_summary(result["run_id"])

        results.append(result)
        append_jsonl(RUN_LOG_FILE, {**result, "ts": _ts()})
        print(f"     → {'PASS' if passed_assert else 'FAIL'} ({result.get('duration_s')}s)", flush=True)

    duration_s = time.monotonic() - t0
    pass_obj = {
        "mode": f"talos test suite ({os.environ.get('OPENAI_MODEL', 'gpt-4o')})",
        "started": started, "duration_s": duration_s, "results": results,
    }
    write_report([pass_obj], Path(args.out))

    n = len(results)
    passed = sum(1 for r in results if r.get("assertion_passed"))
    print(f"\nDone. {passed}/{n} passed in {duration_s:.0f}s. Report: {args.out}")


if __name__ == "__main__":
    main()
