"""Pull only the architecturally-relevant bits from a LangSmith trace.

For each trace we extract:
- The planner's output (sub-tasks emitted)
- For each forge: the resulting code, signature, needs_env_vars
- For each executor call: input sub-task + output (or error)
- For each test: passed/failed + error summary

Discards: LLM call schemas, prompt bodies, message metadata, retries (unless they failed).

Usage:
    uv run python -m examples.compact_trace <run_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from langsmith import Client

from talos.config import settings


def _truncate(s: Any, n: int = 600) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f"...({len(s) - n} more)"


def compact(run_id: str) -> str:
    client = Client(api_key=settings.LANGSMITH_API_KEY)
    runs = list(client.list_runs(id=[run_id]))
    if not runs:
        return f"run {run_id} not found"
    root = runs[0]

    descendants = list(client.list_runs(
        project_name=settings.LANGSMITH_PROJECT,
        trace_id=root.trace_id,
    ))
    descendants.sort(key=lambda r: r.start_time)

    out: list[str] = []
    out.append(f"=== {run_id} ===")
    out.append(f"query: {_truncate(root.inputs)}\n")

    for r in descendants:
        name = r.name or "?"
        if name == "planner":
            plan = (r.outputs or {}).get("plan", {}).get("sub_tasks", [])
            out.append(f"[planner] emitted {len(plan)} sub-tasks:")
            for st in plan:
                out.append(
                    f"  #{st.get('id')} [{st.get('needs')}] "
                    f"hint={st.get('tool_hint')!r} "
                    f"action={_truncate(st.get('action'), 120)}"
                )
            out.append("")

        elif name == "forge":
            tool = (r.outputs or {}).get("forged_tool") or {}
            if tool:
                out.append(f"[forge] -> {tool.get('name')} ({tool.get('signature')})")
                out.append(f"  needs_env_vars: {tool.get('needs_env_vars')}")
                code = tool.get("code", "")
                # Trim code to just signature + first few non-trivial lines
                code_head = "\n  ".join(code.splitlines()[:30])
                out.append(f"  code_head:\n  {code_head}")
                out.append("")

        elif name == "test":
            tr = (r.outputs or {}).get("test_result") or {}
            if tr:
                if tr.get("passed"):
                    out.append(f"[test] PASS ({tr.get('n_passed')}/{tr.get('n_total')})")
                else:
                    err = tr.get("error", "")
                    out.append(f"[test] FAIL: {_truncate(err, 600)}")

        elif name == "executor":
            inp_st = (r.inputs or {}).get("current_sub_task") or {}
            outp = (r.outputs or {}) or {}
            results = outp.get("sub_task_results") or []
            this_result = results[-1] if results else {}
            ok = this_result.get("ok")
            out.append(
                f"[executor] sub-task #{inp_st.get('id')} ({inp_st.get('needs')}) "
                f"-> {'OK' if ok else 'FAIL'}"
            )
            if ok:
                out.append(f"  output: {_truncate(this_result.get('output'), 400)}")
            else:
                out.append(f"  error: {_truncate(this_result.get('error'), 400)}")
            out.append("")

        elif name == "hitl_check" and (r.outputs or {}).get("available_integrations"):
            out.append(f"[hitl] keys collected: {list((r.outputs or {}).get('available_integrations', {}).keys())}")

        elif name == "orchestrator_out":
            outp = r.outputs or {}
            msgs = outp.get("messages") or []
            if msgs:
                last = msgs[-1]
                content = last.get("content") if isinstance(last, dict) else getattr(last, "content", "")
                out.append(f"[final] {_truncate(content, 400)}")
                out.append("")

    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    args = ap.parse_args()
    print(compact(args.run_id))


if __name__ == "__main__":
    main()
