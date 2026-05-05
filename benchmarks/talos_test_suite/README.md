# Talos Test Suite

65 end-to-end queries that exercise every Talos component (Planner, Forger, Tester, Skill Manager, Researcher, Executor, Orchestrator). Source-of-truth doc is `SUITE.md`. Machine-readable spec is `queries.json`. The runner is `run_suite.py`.

## Files

```
SUITE.md            Human-readable test plan (Q01–Q65, organized in 11 categories)
queries.json        Same queries with per-query setup + assertions
run_suite.py        Live-graph runner; writes report to workspace/suite_report.md
fixtures/           Static test inputs copied to /tmp before relevant queries
__init__.py         Makes the folder a Python module (needed for `python -m`)
```

## Run order matters

Some queries (Q12, Q31, Q34, Q42, Q48, Q63, Q64, Q65) reuse tools forged by
earlier ones. By default the runner **wipes the vault once at the start** and
keeps it warm across queries — that's how the reuse tests actually exercise
reuse. Use `--wipe-each` only if you want to test cold-start behaviour for
every query.

## Quickstart

```bash
# Full suite, default model (whatever's in .env → currently gpt-5.1)
uv run python -m benchmarks.talos_test_suite.run_suite

# Just one query / a category / a list
uv run python -m benchmarks.talos_test_suite.run_suite --only Q06,Q12
uv run python -m benchmarks.talos_test_suite.run_suite --category 2

# Override the model just for this run
uv run python -m benchmarks.talos_test_suite.run_suite --model gpt-5.1

# Skip LangSmith trace fetch (faster turnaround)
uv run python -m benchmarks.talos_test_suite.run_suite --no-trace

# Include the human-input queries (Q35–Q37, you'll need to drive interrupts)
uv run python -m benchmarks.talos_test_suite.run_suite --include-hitl
```

## Setup behaviour

Each query that depends on a fixture file declares a `setup` shell command
in `queries.json`. The runner runs it before invoking the graph. All setup
commands are **idempotent** so you can run any subset in any order:

| Query | Setup |
|---|---|
| Q27 | writes `/tmp/talos_test.txt` |
| Q52 | copies `fixtures/sales.csv` to `/tmp/sales.csv` |
| Q55 | writes `/tmp/talos_upper.txt` |
| Q58 | creates `/tmp/rename_test/` with sample files |
| Q59 | writes both test files |
| Q64 | writes a sample `/tmp/config.json` |

## Expectations

`queries.json` uses the same assertion schema as `examples/benchmarks.json`:

- `should_succeed`, `forge_count_max`, `vault_growth_min`
- `answer_contains` / `answer_contains_any` / `answer_contains_all` / `answer_matches_regex`
- `file_should_exist` / `file_contains` / `file_contains_any` / `file_contains_all` / `file_size_min_bytes`

## Output

- `workspace/suite_report.md` — Markdown report with pass/fail per query, failure clusters, trace IDs.
- `workspace/suite_runs.jsonl` — One JSON record per query (append-only, useful for diffing across runs).
