# Talos Web App Stage 04 Part B (Live mode, e2e, CI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put real data behind the React Workbench that part A built: a live transport over the stage 2 REST API and SSE streams, live-mode boot and session handling, the §8.2 live copy differences and nothing else. Then prove it with Playwright (visual parity of demo mode against the reference file, live end-to-end against the fake graph and Postgres, axe, keyboard-only) and run all of it in a CI `frontend` job.

**Architecture:** `transport/live.ts` implements part A's `Transport` interface, the same one `transport/demo.ts` implements, so every live event still goes through `player.ts` and the same stores and components. `transport/api.ts` is a thin typed `fetch` client for `/api`. `transport/stream.ts` wraps one `EventSource` per run with `?after=` reconnect and `seq` de-duplication. `transport/mappers.ts` turns API shapes into the demo's store shapes. Playwright runs from `frontend/` with two configs: `playwright.visual.config.ts` (the reference `index.html` against `vite preview` of `/?demo`, fake clock, frozen animations) and `playwright.live.config.ts` (the built app served by `talos-web` with `TALOS_FAKE_GRAPH=1`, a throwaway Postgres database, and a temporary vault, workspace and `.env`).

**Tech Stack:** React 18, TypeScript (strict), Vite 5 and Vitest, all from part A. `@playwright/test` 1.63.0 and `@axe-core/playwright` 4.13.0, pinned exactly (verified in a scratch project on 30 Sep 2026 with Chromium headless shell 153). Python 3.11+ and uv for the backend harness. GitHub Actions with Node 22 and a `postgres:16` service.

**Specs, in order of authority:**

1. The reference file `docs/superpowers/specs/reference/workbench-demo/artifact-body.html`. It wins over everything below.
2. `docs/superpowers/specs/2026-09-30-talos-web-04-frontend-design.md`: §5, §6 (replay), §8.1–8.3, §9, §10.
3. Overview `2026-09-30-talos-web-app-overview-design.md` §4: the event contract.
4. `2026-09-30-talos-web-02-api-design.md`: endpoints, SSE, fake graph.
5. `2026-09-30-talos-web-03-docker-sandbox-design.md` §5–6: dev commands and CI.

Sibling plans: part A `2026-09-30-talos-web-04a-frontend-demo.md` (every frontend name this plan builds on), stage 2 `2026-09-30-talos-web-02-api.md`, stage 3 `2026-09-30-talos-web-03-docker-sandbox.md`.

## Global Constraints

- Branch `feat/web-04-frontend`, continuing after part A's last task. Same branch, same PR. Do not start until part A's final verification is green.
- **The UI is the demo.** The only differences from the reference are §8.1 (Demo controls hidden in live mode) and §8.2 (the six rows of live copy), plus data that comes from the server (tool names, counts, times, the model name, captions, log lines, answers). Every string the frontend owns is word for word from the reference. When a live-mode need seems to call for a new string, stop and ask the controller. Don't invent copy.
- No component, class name, attribute or CSS change for live mode. Live mode changes what goes into the stores, not what the components render. Part A's DOM-parity and `styles.css` tests must stay green untouched.
- TypeScript strict, no `any` (use `unknown` and narrow). ESLint and `tsc` clean. No new runtime dependencies. New dev dependencies, exactly: `@playwright/test@1.63.0`, `@axe-core/playwright@4.13.0`.
- Python: `uv run pytest` stays green with no database and no Docker. `uv run ruff check .` and `uv run ruff format --check .` are clean, including the new `frontend/e2e/serve_backend.py`.
- The live e2e suite never touches the developer's real data. The database is `talos_e2e`, dropped and created by the harness on every run: on the `talos-pg-test` container (port 55432) locally and on the service container in CI. Never the `talos` database, which the stage 1 integration suite truncates, and never a developer database. The vault, workspace and `.env` are fresh temporary directories.
- Commit messages: prefix `[Feat]:`, `[Fix]:`, `[Docs]:` or `[Chore]:`, then a short sentence. **No `Co-Authored-By` trailer and no Claude attribution line.**
- Frontend commands run in `frontend/`. Python commands run at the repo root.

## Review Focus

1. **Reload while the approval dialog is open.** Expected: after the reload the same session opens, the bench shows the paused run's final state (Executor "waiting for you"), and the dialog comes back from `GET /api/runs/{id}` → `pending`, not from replaying the old `interrupt` event. "Run code" resumes the run and it finishes. Pinned by `e2e/live/06-reload.spec.ts` and `src/app/live.test.ts` (the `waiting` boot row) plus `player.test.ts › caught-up interrupt opens no dialog`.
2. **A finished run's stream.** Expected: the `EventSource` is closed on `run.finished`. Otherwise the browser reconnects on its own when the server closes the stream, gets the backlog again, and loops. Pinned by `sse.test.ts › opens at ?after=N, delivers in order, closes on run.finished and never reconnects`.
3. **A dropped connection mid-run.** Expected: the stream reconnects with `?after=<last seq>`, and events at or below the last applied `seq` are ignored, so nothing renders twice. Pinned by `sse.test.ts › reconnects with after=lastSeq and drops duplicates`.
4. **Esc or Stop during a pause.** Expected: `POST /api/runs/{id}/stop`, never `/resume`. Pinned by `e2e/live/05-stop.spec.ts` (it records every request) and part A's `workbench.test.ts` cancel path, run against `LiveTransport` in `src/app/live.test.ts`.
5. **The key value.** Expected: it leaves the browser once, in the `/resume` body, and is never stored in any store or log. Pinned by `src/transport/live.test.ts` (save key) and `e2e/live/09-keys.spec.ts` step 6.
6. **Visual parity is judged against the reference, rendered on the same machine in the same run.** Expected: no committed PNG baselines. The `ref-*` projects write the baselines from `index.html`, then the `demo-*` projects compare against them at 0.1%. Pinned by the `e2e:visual` script and the CI job.

## Rulings on ambiguities (read before starting)

1. **Seams.** Everything goes through part A's seams: `Transport` (`LiveTransport`), `DataSource` (`LiveDataSource`), `Player`, `Workbench`, `createServices("live")`. Components change only through optional props that default to part A's behaviour (Task 4), so demo rendering and every part A parity test stay byte-identical.
2. **Reconnect.** `EventSource` is closed on `run.finished`. Otherwise the browser reconnects when the server ends the stream and replays it forever. A dropped connection is re-opened by hand with `?after=<last seq>`: a new `EventSource` can't send `Last-Event-ID`, and stage 2 reads the header before `?after`. Events at or below the last seq are dropped.
3. **Reattach after a reload.** Backlog events (stamped at or before the reattach time) apply instantly, with no dwell and no dialog. Later events are paced. For a `waiting` run, the dialog comes from `GET /api/runs/{id}.pending` once the backlog has been quiet for 150 ms, never from the replayed `interrupt`. The client clock is used for the cutoff, because the server is local (overview §1: single user, 127.0.0.1).
4. **Past runs** load as stubs from `RunSummary`, enough for the Sessions cards and the Earlier list. A stub is replayed from its event log (`replay: true`, final state, no pacing) the first time it's viewed. Replays and caught-up events never change the vault store or the badge; the vault is reloaded from the API after every `run.finished`.
5. **Server-owned copy stays server-owned.** In fake-graph mode the server *is* the demo, so `Not called in this demo` and the other demo strings in captions, results and answers are correct there. The frontend's §8.2 duties are only the key-dialog footer, the vault "Source lives at…" line, seeded sessions and Demo controls.
6. **`call.error.when`.** Stage 2 sends the codes `"run"` and `"declined"`, and the reference shows a time or `You chose Don't run`. `normalise()` maps them (`fmtTime(e.ts)` and the new `COPY.call.whenDeclined`). This is at the transport boundary, not in the player.
7. **Sessions.** Stage 2 lists only sessions with runs, and `POST /api/sessions` reuses the newest empty one. So boot opens the newest session with runs, or creates/reuses an empty one when there is none; "New session" on an empty session changes nothing but the title decode. This replaces the demo's "discard the empty session" with the server's equivalent (spec 04 §5).
8. **Settings copy.** Key descriptions are the reference's strings from part A's `COPY.settings.keyDesc`, not the server's `description`: the server's "Saved by Human check" isn't a reference string, while the reference's is `Saved by Human check this session.`. That reference string is used for every extra key, even keys saved in an earlier session (word-for-word rule; open owner decision). Facts and the model come from `GET /api/settings`; `llm_timeout_s` is rounded to whole seconds.
9. **Numbers inside frontend copy stay literal.** That's the approval dialog's "stops after 10 seconds", the Tests panel's 10-second note, and the health meter's 2. They match stage 2's defaults. Changing `TALOS_SUBPROCESS_TIMEOUT` or the prune threshold won't update them, and this is listed for the owner (Task 12).
10. **Errors.** A `409 run_active` on send re-attaches to the active run when it's in the current session. Other API errors unlock the composer and log to the console. There's no reference copy for errors, so none is invented.
11. **Visual baselines** are rendered from the reference in the same run, on the same machine, and never committed (`ref-*` projects write them, `demo-*` compare at `maxDiffPixelRatio: 0.001`). Time is frozen with Playwright's clock (`install` + `pauseAt`, then `runFor` in 10 ms steps), which drives every `setTimeout` and `requestAnimationFrame` in both pages. This was verified in a scratch project against the reference, including a mid-run planning shot and the approval dialog.
12. **Reference a11y defect.** At 390 px the GitHub pill has no accessible name (axe `link-name`, serious, in the reference itself). It's kept for parity, excluded in exactly one place, and listed for the owner. Moderate findings (landmarks) are below the spec's bar.
13. **E2E isolation.** There's one throwaway `talos_e2e` database (the harness refuses any other name), a fresh `frontend/.e2e-tmp/`, no API keys in the server's environment, port 8765, and never a reused server. Specs run serially in name order and set up their own preconditions through the API.
14. **Stage 03 CI.** Stage 03 adds `integration` and `docker` and no placeholder, so Task 11 appends the whole `frontend` job.
15. **Playwright is already installed by part A** (`@playwright/test@1.63.0`, ruling 13 there). Part B adds only `@axe-core/playwright@4.13.0`.

## File map

All frontend paths are under `frontend/`.

| File | Task | Responsibility |
|---|---|---|
| `src/transport/types.ts` | 1 | `failed: boolean`; `ApiSessionSummary`, `ApiSessionDetail`, `ApiRun`, `ApiVaultList`, `ApiVaultDetail` |
| `src/lib/sanitize.ts` | 1 | allowlist sanitiser for server HTML |
| `src/transport/api.ts` | 1 | typed `fetch` client, `ApiError` |
| `src/transport/sse.ts` | 1 | `parseSse`, `openRunStream` (reconnect, de-dup, close on finish) |
| `src/transport/live.ts` | 2 | `LiveTransport`, `normalise` |
| `src/data/live.ts` | 2 | `LiveDataSource`, API → store mappers |
| `src/lib/copy.ts`, `src/store/types.ts` | 2 | `COPY.call.whenDeclined`; `SettingsState.live` |
| `src/transport/player.ts` | 3 | `catchUpUntil`; replay/catch-up leave the vault store alone |
| `src/app/workbench.ts`, `src/services.ts`, `src/main.tsx` | 3 | live boot, reattach, hydrate, refreshes, 409 |
| `src/components/settings/SettingsView.tsx`, `workbench/Idle.tsx`, `vault/VaultView.tsx`, `src/App.tsx` | 4 | optional live props |
| `e2e/serve_backend.py`, `tests/test_e2e_serve_backend.py` (repo root), `.gitignore`, `.dockerignore` | 5 | isolated fake-graph server for e2e |
| `package.json`, `tsconfig.json`, `tsconfig.e2e.json`, `eslint.config.js`, `playwright.visual.config.ts`, `playwright.live.config.ts`, `e2e/support/*`, `e2e/live/fixtures.ts` | 6 | Playwright setup |
| `e2e/visual/*.spec.ts` | 7 | reference vs `/?demo` screenshots |
| `e2e/live/01…03` | 8 | Caesar flows, sessions, vault |
| `e2e/live/04…06`, `09-keys.spec.ts` | 9 | approvals, settings, stop, reload, keys |
| `e2e/live/07-a11y.spec.ts`, `08-keyboard.spec.ts` | 10 | axe and keyboard-only |
| `.github/workflows/ci.yml` (repo root) | 11 | `frontend` job |
| `README.md`, `PROGRESS.md` (repo root) | 12 | docs |

---

### Task 1: API client, SSE parsing and the server-HTML sanitiser

**Files:**
- Create: `frontend/src/lib/sanitize.ts`, `frontend/src/transport/api.ts`, `frontend/src/transport/sse.ts`
- Modify: `frontend/src/transport/types.ts` (one fix and four new API shapes)
- Test: `frontend/src/lib/sanitize.test.ts`, `frontend/src/transport/api.test.ts`, `frontend/src/transport/sse.test.ts`

**Interfaces:**
- Consumes: part A's `RunEvent`, `EventType`, `ResumeDecision`, `ApiSession`, `ApiMessage`, `ApiRunSummary`, `ApiVaultEntry`, `ApiSettings` (`transport/types.ts`), `esc` (`lib/format.ts`).
- Produces: `sanitize(html: string): string`; `ApiError { status, code, message, runId?, sessionId? }`; `createApi(fetchImpl?: typeof fetch): Api` with `listSessions`, `createSession`, `getSession`, `send`, `getRun`, `runEvents`, `resume`, `stop`, `vault`, `tool`, `removeTool`, `settings`, `setAskBeforeExec`; `parseSse(text: string): RunEvent[]`; `openRunStream(o: { runId: string; after: number; onEvent(e: RunEvent): void; ES?: EventSourceCtor; retryMs?: number }): { close(): void }`; `EVENT_TYPES: EventType[]`.

- [ ] **Step 1: Fix and extend the API shapes in `transport/types.ts`**

Stage 2's `RunSummaryOut.failed` is a boolean (plan 02, Task 3 schemas). Part A typed it `string[]`. Change it to `failed: boolean`. Stage 2 also sends `VaultEntry.created_at` as `string | null` for manifest entries without a date. Keep part A's `string` in the contract type and map `null` to `""` in the data source (Task 2).

Append:

```ts
/* Stage 2 response shapes that part A didn't need (plan 02 Task 3, schemas.py). */
export interface ApiSessionSummary {
  id: string;
  name: string;
  created_at: string;
  run_count: number;
  forged: string[];
  used: string[];
  runs: { n: number; query: string; mark: "forged" | "reused" | "failed" | null }[];
}
export interface ApiSessionDetail {
  session: ApiSession;
  messages: ApiMessage[];
  runs: ApiRunSummary[];
}
export interface ApiRun extends ApiRunSummary {
  pending:
    | { kind: "confirm_exec"; payload: { tool: "python_exec" | "shell_exec"; preview: string } }
    | { kind: "missing_api_key"; payload: { env_var: string; tool_name: string; service: string } }
    | null;
}
export interface ApiVaultList {
  count: number;
  web_count: number;
  failed_count: number;
  tools: ApiVaultEntry[];
}
export interface ApiVaultDetail extends ApiVaultEntry {
  source: string | null;
  lines: number;
}
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/sanitize.test.ts`:

```ts
import { sanitize } from "./sanitize";

test("keeps the contract's allowlist: mono and gold spans, in-app links", () => {
  const html = 'Attempt <span class="gold">2 of 3.</span> <span class="mono">caesar_cipher</span> <a href="#vault">the Vault</a> <a href="#settings">Settings</a>';
  expect(sanitize(html)).toBe(html);
});

test("drops every other element to its text and escapes it", () => {
  expect(sanitize('<script>alert(1)</script><b>bold</b> <img src=x onerror="x()">')).toBe("alert(1)bold ");
  expect(sanitize('<a href="https://evil.example">x</a>')).toBe("x");
  expect(sanitize('<span class="mono" onclick="x()">y</span>')).toBe("y");
  expect(sanitize('<span class="other">z</span>')).toBe("z");
});

test("keeps entities escaped", () => {
  expect(sanitize("&lt;b&gt; &amp; &quot;q&quot;")).toBe("&lt;b&gt; &amp; &quot;q&quot;");
});
```

`frontend/src/transport/sse.test.ts`:

```ts
import { openRunStream, parseSse } from "./sse";
import type { RunEvent } from "./types";

const env = (seq: number, type: string, data: object = {}) => ({ run_id: "r", seq, ts: "2026-09-30T12:00:00.000Z", type, data });
const frame = (e: ReturnType<typeof env>) => `id: ${e.seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`;

test("parseSse reads envelopes and skips comments", () => {
  const text = `: keep-alive\n\n${frame(env(1, "run.started", { session_id: "s", query: "q", n: 1 }))}${frame(env(2, "log.cmd", { text: "q" }))}`;
  expect(parseSse(text).map((e) => [e.seq, e.type])).toEqual([[1, "run.started"], [2, "log.cmd"]]);
});

class FakeES {
  static all: FakeES[] = [];
  listeners = new Map<string, (m: MessageEvent<string>) => void>();
  onerror: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeES.all.push(this);
  }
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void) {
    this.listeners.set(type, fn);
  }
  close() {
    this.closed = true;
  }
  emit(e: ReturnType<typeof env>) {
    this.listeners.get(e.type)?.({ data: JSON.stringify(e) } as MessageEvent<string>);
  }
}
beforeEach(() => {
  FakeES.all = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

test("opens at ?after=N, delivers in order, closes on run.finished and never reconnects", () => {
  const got: RunEvent[] = [];
  openRunStream({ runId: "r", after: 0, onEvent: (e) => got.push(e), ES: FakeES as never });
  const es = FakeES.all[0]!;
  expect(es.url).toBe("/api/runs/r/events?after=0");
  es.emit(env(1, "run.started", { session_id: "s", query: "q", n: 1 }));
  es.emit(env(2, "run.finished", { status: "done", summary: "", summary_gold: false, forged: [], used: [] }));
  expect(got.map((e) => e.seq)).toEqual([1, 2]);
  expect(es.closed).toBe(true);
  es.onerror?.();
  vi.advanceTimersByTime(5000);
  expect(FakeES.all).toHaveLength(1);
});

test("reconnects with after=lastSeq and drops duplicates", () => {
  const got: number[] = [];
  openRunStream({ runId: "r", after: 0, onEvent: (e) => got.push(e.seq), ES: FakeES as never, retryMs: 1000 });
  const a = FakeES.all[0]!;
  a.emit(env(1, "run.started", { session_id: "s", query: "q", n: 1 }));
  a.emit(env(2, "log.cmd", { text: "q" }));
  a.onerror?.();
  expect(a.closed).toBe(true);
  vi.advanceTimersByTime(1000);
  const b = FakeES.all[1]!;
  expect(b.url).toBe("/api/runs/r/events?after=2");
  b.emit(env(2, "log.cmd", { text: "q" }));
  b.emit(env(3, "caption", { html: "x" }));
  expect(got).toEqual([1, 2, 3]);
});

test("close() stops everything, including a pending reconnect", () => {
  const s = openRunStream({ runId: "r", after: 5, onEvent: () => {}, ES: FakeES as never, retryMs: 1000 });
  FakeES.all[0]!.onerror?.();
  s.close();
  vi.advanceTimersByTime(5000);
  expect(FakeES.all).toHaveLength(1);
});
```

`frontend/src/transport/api.test.ts`:

```ts
import { ApiError, createApi } from "./api";

const reply = (status: number, body?: unknown) =>
  Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

test("sends JSON to /api and returns the body", async () => {
  const f = vi.fn(() => reply(202, { run: { id: "r", n: 1 }, message: { id: "m" } }));
  const api = createApi(f as unknown as typeof fetch);
  const out = await api.send("s1", "hello");
  expect(out.run.id).toBe("r");
  expect(f).toHaveBeenCalledWith("/api/sessions/s1/messages", expect.objectContaining({ method: "POST", body: JSON.stringify({ text: "hello" }) }));
});

test("204 resolves to undefined; names are URL-encoded", async () => {
  const f = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
  await expect(createApi(f as unknown as typeof fetch).removeTool("a b")).resolves.toBeUndefined();
  expect(f).toHaveBeenCalledWith("/api/vault/a%20b", expect.objectContaining({ method: "DELETE" }));
});

test("errors carry stage 2's code, message and run_active ids", async () => {
  const body = { error: { code: "run_active", message: "A run is already going. Stop it or wait for it to finish.", run_id: "r9", session_id: "s9" } };
  const api = createApi((() => reply(409, body)) as unknown as typeof fetch);
  const err = await api.send("s1", "x").catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ status: 409, code: "run_active", runId: "r9", sessionId: "s9" });
});

test("resume sends the decision and nothing else", async () => {
  const f = vi.fn(() => reply(202, { ok: true }));
  await createApi(f as unknown as typeof fetch).resume("r", { decision: "save", value: "k" });
  expect(f).toHaveBeenCalledWith("/api/runs/r/resume", expect.objectContaining({ body: '{"decision":"save","value":"k"}' }));
});
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/lib/sanitize.test.ts src/transport/api.test.ts src/transport/sse.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 4: Implement**

`frontend/src/lib/sanitize.ts`:

```ts
import { esc } from "./format";

/* Server HTML may hold only <span class="mono|gold"> and links to #vault / #settings (overview §4.3,
   spec 04 §2.1). The server escapes everything else; this is the browser's own guard. */
const SPAN_CLASSES = new Set(["mono", "gold"]);
const HREFS = new Set(["#vault", "#settings"]);

function walk(node: Node): string {
  let out = "";
  node.childNodes.forEach((c) => {
    if (c.nodeType === Node.TEXT_NODE) {
      out += esc(c.textContent ?? "");
      return;
    }
    if (c.nodeType !== Node.ELEMENT_NODE) return;
    const el = c as Element;
    const inner = walk(el);
    const tag = el.tagName.toLowerCase();
    const cls = el.getAttribute("class") ?? "";
    const href = el.getAttribute("href") ?? "";
    if (tag === "span" && el.attributes.length === 1 && SPAN_CLASSES.has(cls)) out += `<span class="${cls}">${inner}</span>`;
    else if (tag === "a" && el.attributes.length === 1 && HREFS.has(href)) out += `<a href="${href}">${inner}</a>`;
    else if (tag !== "script" && tag !== "style") out += inner;
    else out += esc(el.textContent ?? "");
  });
  return out;
}

export function sanitize(html: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  return walk(t.content);
}
```

(`<script>` content is kept as escaped text, so the first test's expectation is `alert(1)bold `. Keep the test and the code in agreement.)

`frontend/src/transport/api.ts`:

```ts
import type {
  ApiMessage, ApiRun, ApiRunSummary, ApiSession, ApiSessionDetail, ApiSessionSummary, ApiSettings,
  ApiVaultDetail, ApiVaultList, ResumeDecision, RunEvent,
} from "./types";
import { parseSse } from "./sse";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly runId?: string,
    readonly sessionId?: string,
  ) {
    super(message);
  }
}

export interface Api {
  listSessions(): Promise<ApiSessionSummary[]>;
  createSession(): Promise<ApiSession>;
  getSession(id: string): Promise<ApiSessionDetail>;
  send(sessionId: string, text: string): Promise<{ run: ApiRunSummary; message: ApiMessage }>;
  getRun(id: string): Promise<ApiRun>;
  /** A finished run's whole event log (the server sends the backlog and closes). */
  runEvents(id: string): Promise<RunEvent[]>;
  resume(id: string, d: ResumeDecision): Promise<void>;
  stop(id: string): Promise<void>;
  vault(): Promise<ApiVaultList>;
  tool(name: string): Promise<ApiVaultDetail>;
  removeTool(name: string): Promise<void>;
  settings(): Promise<ApiSettings>;
  setAskBeforeExec(on: boolean): Promise<ApiSettings>;
}

export function createApi(fetchImpl: typeof fetch = (...a) => fetch(...a)): Api {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetchImpl(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 204) return undefined as T;
    const data: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const e = (data as { error?: { code?: string; message?: string; run_id?: string; session_id?: string } } | null)?.error;
      throw new ApiError(res.status, e?.code ?? `http_${res.status}`, e?.message ?? res.statusText, e?.run_id, e?.session_id);
    }
    return data as T;
  }
  const enc = encodeURIComponent;
  return {
    listSessions: () => call("GET", "/sessions"),
    createSession: () => call("POST", "/sessions"),
    getSession: (id) => call("GET", `/sessions/${enc(id)}`),
    send: (id, text) => call("POST", `/sessions/${enc(id)}/messages`, { text }),
    getRun: (id) => call("GET", `/runs/${enc(id)}`),
    runEvents: async (id) => {
      const res = await fetchImpl(`/api/runs/${enc(id)}/events?after=0`);
      if (!res.ok) throw new ApiError(res.status, `http_${res.status}`, res.statusText);
      return parseSse(await res.text());
    },
    resume: async (id, d) => void (await call("POST", `/runs/${enc(id)}/resume`, d)),
    stop: async (id) => void (await call("POST", `/runs/${enc(id)}/stop`)),
    vault: () => call("GET", "/vault"),
    tool: (name) => call("GET", `/vault/${enc(name)}`),
    removeTool: (name) => call("DELETE", `/vault/${enc(name)}`),
    settings: () => call("GET", "/settings"),
    setAskBeforeExec: (on) => call("PATCH", "/settings", { ask_before_exec: on }),
  };
}
```

`runEvents` is only called for runs that are not `running` or `waiting` (the stream stays open through a pause and would never end).

`frontend/src/transport/sse.ts`:

```ts
import type { EventType, RunEvent } from "./types";

/** Every contract event type: EventSource only delivers named events to listeners for their name. */
export const EVENT_TYPES: EventType[] = [
  "run.started", "log.cmd", "plan.ready", "strip.set", "subtask.started", "node.started", "node.finished", "link.flow",
  "caption", "log.line", "log.pop", "log.status", "talos.status", "forge.code", "forge.tests", "forge.attempt",
  "forge.smoke", "vault.saved", "vault.failure", "call.args", "call.result", "call.error", "interrupt",
  "interrupt.resolved", "answer.delta", "answer.done", "run.finished", "error",
];

/** Parses a whole SSE body (a finished run's backlog). Comments (": keep-alive") are skipped. */
export function parseSse(text: string): RunEvent[] {
  const out: RunEvent[] = [];
  for (const block of text.replace(/\r\n/g, "\n").split("\n\n")) {
    const data = block
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).replace(/^ /, ""))
      .join("\n");
    if (data) out.push(JSON.parse(data) as RunEvent);
  }
  return out;
}

export type EventSourceCtor = new (url: string) => {
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void): void;
  close(): void;
  onerror: ((this: unknown, ev: Event) => unknown) | null;
};

/**
 * One EventSource per run. On an error it closes and reconnects itself with ?after=<last seq>
 * (a new EventSource can't set Last-Event-ID, and stage 2 reads the header before ?after).
 * Events at or below the last delivered seq are dropped. It closes for good on run.finished,
 * because the browser would otherwise reconnect when the server ends the stream and replay it.
 */
export function openRunStream(o: {
  runId: string;
  after: number;
  onEvent(e: RunEvent): void;
  ES?: EventSourceCtor;
  retryMs?: number;
}): { close(): void } {
  const ES = o.ES ?? (EventSource as unknown as EventSourceCtor);
  let last = o.after;
  let closed = false;
  let es: InstanceType<EventSourceCtor> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const close = () => {
    closed = true;
    if (timer) clearTimeout(timer);
    es?.close();
  };
  const onMessage = (m: MessageEvent<string>) => {
    const e = JSON.parse(m.data) as RunEvent;
    if (closed || e.seq <= last) return;
    last = e.seq;
    o.onEvent(e);
    if (e.type === "run.finished") close();
  };
  const connect = () => {
    if (closed) return;
    es = new ES(`/api/runs/${encodeURIComponent(o.runId)}/events?after=${last}`);
    for (const t of EVENT_TYPES) es.addEventListener(t, onMessage);
    es.onerror = () => {
      es?.close();
      if (!closed) timer = setTimeout(connect, o.retryMs ?? 1000);
    };
  };
  connect();
  return { close };
}
```

- [ ] **Step 5: Run the tests, lint, typecheck**

Run: `npx vitest run src/lib/sanitize.test.ts src/transport/api.test.ts src/transport/sse.test.ts && npm run lint && npm run typecheck`
Expected: PASS. Then run the whole `npm test`: part A's suite is unchanged (the `failed` type change compiles because nothing in part A reads it).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/sanitize.ts frontend/src/lib/sanitize.test.ts frontend/src/transport/api.ts frontend/src/transport/api.test.ts frontend/src/transport/sse.ts frontend/src/transport/sse.test.ts frontend/src/transport/types.ts
git commit -m "[Feat]: Add the API client, SSE stream with reconnect and the server-HTML sanitiser"
```

---

### Task 2: LiveTransport and the live data source

**Files:**
- Create: `frontend/src/transport/live.ts`, `frontend/src/data/live.ts`
- Modify: `frontend/src/lib/copy.ts` (one string), `frontend/src/store/types.ts` (`SettingsState.live`)
- Test: `frontend/src/transport/live.test.ts`, `frontend/src/data/live.test.ts`

**Interfaces:**
- Consumes: Task 1; part A's `Transport`, `StartedRun`, `DataSource`, `fromVaultEntry`, `newRun`, `COPY`, `fmtTime`.
- Produces:
  - `class LiveTransport implements Transport { constructor(api: Api, ES?: EventSourceCtor) }`, plus `normalise(e: RunEvent): RunEvent`.
  - `class LiveDataSource implements DataSource { constructor(api: Api) }` plus `setCurrentStarted(iso)`, `loadSessions(summaries): Promise<LoadedSession[]>`, `runEvents(id)`, `getRun(id)`, `createSession()`.
  - `LiveSettings = { keys: ApiSettings["keys"]; forgeRetries: number; testTimeoutS: number; llmTimeoutS: number; pruneAfter: number }`. `SettingsState` gains `live?: LiveSettings` (absent in demo mode).
  - `LoadedSession = { rec: SessionRec; runs: Run[]; active: ApiRunSummary | null }`.
  - Mappers (exported for tests): `sourceLines`, `toSettings`, `toMessages`, `stubRun`.

Mapping rules (each checked by a test):

| API | Store | Rule |
|---|---|---|
| `VaultEntry` | `VaultTool` | part A's `fromVaultEntry`, with `created_at ?? ""`; `fresh` = `created_at` at or after the current session's `created_at` (spec 04 §5) |
| `VaultDetail.source` | source lines | drop one trailing newline, then split on `\n`. So a file's lines match the reference's `getSource()` (a `<script>` body with no trailing newline) and the "N lines" counts agree |
| `Settings` | `SettingsState` | `askExec = ask_before_exec`; `env` = `{ [name]: "set" }` for each key with `set` (never a value: the API never sends one); `model`; `live` = the keys and facts |
| `Message` (user) | `YouMessage` | text = the HTML unescaped to text (the server stores `html.escape(text)`; the component escapes it again) |
| `Message` (assistant) | `TalosMessage` | `html` sanitised, `wrap: false` (like the reference's `sessionHtml`), note sanitised, chips as sent, `runLink: true`. A stopped run's message (empty `html`, the stop note in `note`) becomes `html: null`, `stopNote: note` |
| messages of a `running`/`waiting` run | none | dropped: the reattached player re-adds You and Talos from `run.started` (Task 3) |
| `RunSummary` | stub `Run` | `newRun(...)` with `status`, `summary`, `summaryGold`, `forged: forged.length > 0`, `toolUsed: forged[0] ?? used[0]`, `failed`, and `strip` `"chat"` (no nodes). Enough for the Sessions cards and the Earlier list. The full run is replayed on demand (Task 3) |

- [ ] **Step 1: Add the one copy string**

In `COPY.call`, add `whenDeclined: "You chose Don't run"` (reference line 1811, `run.call.when`). Part A's copy test asserts it appears in the reference. Stage 2 sends `call.error.when` as the code `"declined"` or `"run"` (plan 02, fake graph and translator), and the live transport turns those into the reference's text.

- [ ] **Step 2: Write the failing tests**

`frontend/src/transport/live.test.ts` covers:

- `startRun` posts the text, and returns `{ runId, n, sessionName: null }` when `run.n > 1`. When `run.n === 1`, it reads the session back (`getSession`) and returns its new name (stage 2 renames on the first run).
- `normalise`: `caption.html`, `answer.done.html` and `answer.done.note` go through `sanitize`. `call.error.when` `"declined"` becomes `COPY.call.whenDeclined`, and `"run"` becomes `fmtTime(e.ts)`. Any other `when` passes through. Every other event is returned unchanged (same object).
- `subscribe(runId, sink, after)` opens `/api/runs/{id}/events?after={after}` (use Task 1's `FakeES`) and calls `sink` with normalised events. The returned function closes the stream.
- `resume` and `stop` call the API. **Save key sends the value once and keeps no copy:** after `resume(id, { decision: "save", value: "k-123" })`, the only place `"k-123"` appears is the one fetch body. Assert this with `JSON.stringify` of the transport instance.

`frontend/src/data/live.test.ts` covers every row of the mapping table with small literal API objects. For example:

```ts
test("sourceLines drops one trailing newline", () => {
  expect(sourceLines("a\nb\n")).toEqual(["a", "b"]);
  expect(sourceLines("a\nb")).toEqual(["a", "b"]);
  expect(sourceLines("a\n\n")).toEqual(["a", ""]);
});

test("toSettings never carries a key value and keeps the facts", () => {
  const s = toSettings({
    model: "deepseek/deepseek-v4.1-flash", ask_before_exec: true, forge_retries: 3, test_timeout_s: 10, llm_timeout_s: 120, prune_after: 2,
    keys: [{ name: "OPENROUTER_API_KEY", set: true, required: true, description: "Required. Every model call goes through OpenRouter." }],
  });
  expect(s).toEqual({
    askExec: true, env: { OPENROUTER_API_KEY: "set" }, model: "deepseek/deepseek-v4.1-flash",
    live: { keys: [expect.objectContaining({ name: "OPENROUTER_API_KEY", set: true })], forgeRetries: 3, testTimeoutS: 10, llmTimeoutS: 120, pruneAfter: 2 },
  });
});
```

Also: `vault()` marks `fresh` by the current session's `created_at` (before → false, equal or after → true). `loadSessions` returns the runs as stubs, sorted by `n`, and `active` set to the run that is `running` or `waiting` (if any). The messages of that active run are dropped.

- [ ] **Step 3: Run them and watch them fail**

Run: `npx vitest run src/transport/live.test.ts src/data/live.test.ts` → FAIL.

- [ ] **Step 4: Implement `transport/live.ts`**

```ts
import { COPY } from "../lib/copy";
import { fmtTime } from "../lib/format";
import { sanitize } from "../lib/sanitize";
import type { Api } from "./api";
import { openRunStream, type EventSourceCtor } from "./sse";
import type { EventSink, ResumeDecision, RunEvent, StartedRun, Transport } from "./types";

/** Server facts → what the player expects: sanitised HTML, and the reference's `when` text. */
export function normalise(e: RunEvent): RunEvent {
  switch (e.type) {
    case "caption":
      return { ...e, data: { html: sanitize(e.data.html) } };
    case "answer.done":
      return { ...e, data: { ...e.data, html: sanitize(e.data.html), note: e.data.note == null ? null : sanitize(e.data.note) } };
    case "call.error": {
      const w = e.data.when;
      const when = w === "declined" ? COPY.call.whenDeclined : w === "run" ? fmtTime(e.ts) : w;
      return { ...e, data: { ...e.data, when } };
    }
    default:
      return e;
  }
}

/** Live runs over stage 2: POST to start, one EventSource per run, /resume and /stop. */
export class LiveTransport implements Transport {
  constructor(
    private readonly api: Api,
    private readonly ES?: EventSourceCtor,
  ) {}

  async startRun(sessionId: string, text: string): Promise<StartedRun> {
    const { run } = await this.api.send(sessionId, text);
    const sessionName = run.n === 1 ? (await this.api.getSession(sessionId)).session.name : null;
    return { runId: run.id, n: run.n, sessionName };
  }

  subscribe(runId: string, sink: EventSink, after = 0): () => void {
    const s = openRunStream({ runId, after, ES: this.ES, onEvent: (e) => void sink(normalise(e)) });
    return () => s.close();
  }

  resume(runId: string, decision: ResumeDecision): Promise<void> {
    return this.api.resume(runId, decision);
  }

  stop(runId: string): Promise<void> {
    return this.api.stop(runId);
  }
}
```

- [ ] **Step 5: Implement `data/live.ts`**

Write `LiveDataSource` with the mapping table above. Notes for the parts that aren't one-liners:

- `vault()`: `(await api.vault()).tools.map((e) => fromVaultEntry({ ...e, created_at: e.created_at ?? "" }, isFresh(e.created_at)))`, where `isFresh(c) = !!c && !!this.currentStarted && Date.parse(c) >= Date.parse(this.currentStarted)`.
- `toolSource(name)`: `api.tool(name)` → `source == null ? null : sourceLines(source)`. A 404 (the tool was removed meanwhile) → `null`.
- `settings()` → `toSettings(await api.settings())`. `setAskBeforeExec(on)` → `api.setAskBeforeExec(on)`.
- `sessions()`: the part A interface method. It returns `{ sessions: [], runs: [], lastRunNumber: 0 }` in live mode, because live boot uses `loadSessions` instead (Task 3). Document that in a comment.
- `newSession()`: `api.createSession()` → `{ id, name, started: created_at }`, and it sets `currentStarted`. The `count` argument is ignored: the server numbers sessions and reuses the newest empty one (plan 02 decision).
- `loadSessions(list)`: `Promise.all(list.map((s) => api.getSession(s.id)))`, then per session `rec = { id, name, started: session.created_at, live: false, runIds, messages }` and `runs = detail.runs.map(stubRun)`.
- `toMessages(detail)`: walk `messages` in order. Map `run_id` → `n` via `detail.runs`. Skip messages whose run is `running`/`waiting`. You keys are `you-${m.id}` and Talos keys `talos-${m.id}`, so they never collide with the player's `you-${n}`/`talos-${n}` keys.
- `runEvents(id)` → `api.runEvents(id)`, then each through `normalise`. `getRun(id)` → `api.getRun(id)`. `removeTool(name)` → `api.removeTool(name)`.

`store/types.ts`: add `export interface LiveSettings { keys: { name: string; set: boolean; required: boolean; description: string }[]; forgeRetries: number; testTimeoutS: number; llmTimeoutS: number; pruneAfter: number }`, and `live?: LiveSettings` on `SettingsState`, with a comment: "Live mode only: Settings and the idle setup line read these; demo mode keeps the reference's fixed rows".

- [ ] **Step 6: Run the tests, lint, typecheck, the whole suite**

Run: `npx vitest run src/transport/live.test.ts src/data/live.test.ts && npm test && npm run lint && npm run typecheck`
Expected: PASS, and part A's tests are unchanged.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/transport/live.ts frontend/src/transport/live.test.ts frontend/src/data/live.ts frontend/src/data/live.test.ts frontend/src/lib/copy.ts frontend/src/store/types.ts
git commit -m "[Feat]: Add LiveTransport and the live data source with the API-to-store mappers"
```

---

### Task 3: Live boot, reattach, replay, and the controller's live paths

**Files:**
- Modify: `frontend/src/transport/player.ts`, `frontend/src/app/workbench.ts`, `frontend/src/services.ts`, `frontend/src/main.tsx`
- Test: `frontend/src/transport/player.test.ts` (add cases), `frontend/src/app/live.test.ts` (new)

**Interfaces:**
- Consumes: Tasks 1–2; part A's `Player`, `Workbench`, `createServices`, `createStores`.
- Produces: `PlayerOptions.catchUpUntil?: string`; `Workbench.boot(): Promise<void>`; `createServices("live")` → `{ stores, services }` with `services.data: LiveDataSource`, `services.transport: LiveTransport`, `services.demo: null`.

Live behaviour, each pinned by a test in `app/live.test.ts` (fake `Api` object built with `vi.fn`, `FakeES` from Task 1, fake timers):

| Situation | Behaviour |
|---|---|
| Boot, no sessions with runs | `POST /api/sessions` (it reuses an empty one), then idle bench, title = its name |
| Boot, sessions exist | `GET /api/sessions`; the first (newest) is current. Its messages render (Task 2 rules), its last finished run is replayed and shown on the bench (as `backToNow` shows the last run), and the others become past sessions for the Sessions page |
| Boot, the current session's last run is `running` | reattach: a paced `Player` with `catchUpUntil` = now, subscribed from `seq` 0. Backlog events apply instantly (no dwell, no reveal), later ones paced; `busy` on; Stop works |
| Boot, the last run is `waiting` | reattach as above; the player never opens a dialog for a caught-up `interrupt`; the controller opens it from `GET /api/runs/{id}` → `pending` once the backlog has gone quiet for 150 ms |
| Send | part A's `submit` path with `LiveTransport`, `momentDwell: true`; after `run.finished` the vault store is reloaded from `GET /api/vault` (the API is the source of truth for counts and freshness) |
| Send answered `409 run_active` | `busy` off again; if the active run is in the current session, reattach to it; otherwise nothing (no new copy) |
| `viewRun(n)` / `openSession(id)` / `backToNow()` on a run that is still a stub | fetch its events, replay them with `replay: true` into the same run id, then view it |
| Enter Vault, Sessions or Settings | refresh that store from the API (vault, the session list, settings) before the view re-renders |
| New session | `POST /api/sessions`; if the server returned the current (empty) session, nothing changes but the title decode |
| Dialog answers | unchanged from part A: approve/decline/save/skip → `/resume`; Esc (cancel) → `stop()` → `/stop` |

- [ ] **Step 1: Player changes (tests first)**

Add to `player.test.ts`:

1. **Catch-up.** With `catchUpUntil: "2026-09-30T12:00:05.000Z"`, a `forge.code` event with `ts` before it reveals all lines at once (no timers pending), and one with a later `ts` reveals at 24 ms per tick.
2. **Caught-up interrupt opens no dialog.** An `interrupt` with an early `ts` leaves `ui.dialog` null and the run `waiting`. A later one opens the dialog.
3. **Replay and catch-up don't touch the vault or the badge.** Replaying `vault.saved`, `vault.failure` and `call.result` changes neither `stores.vault` nor `ui.badge`/`ui.selected`, but the run still gets its banner, health panel and result.

Implement:

```ts
// PlayerOptions
  /** Reattach (spec 04 §6): events stamped at or before this ISO time apply without pacing or dialogs. */
  catchUpUntil?: string;

// Player
  private catching = false;
  private get fast(): boolean {
    return this.aborted || !!this.opts.replay || this.catching;
  }
  /** Replays and caught-up events describe the past: the vault store is reloaded from the API instead. */
  private get quiet(): boolean {
    return !!this.opts.replay || this.catching;
  }
  // first line of apply(e):
    this.catching = !!this.opts.catchUpUntil && Date.parse(e.ts) <= Date.parse(this.opts.catchUpUntil);
```

- `interrupt`: `if (this.opts.replay || this.catching) return;` after setting `waiting`.
- `vault.saved`: when `quiet`, only the banner.
- `failure()`: when `quiet`, skip the `stores.vault.update`. The health panel and the removed banner still apply.
- `callResult()`: when `quiet`, skip `recordUse`, but still compute `record` from the current tool (the Uses shown are today's count, the only one the API has).
- The `momentDwell` sleeps already go through `sleep()`, which returns at once when `fast`.

Demo mode is unaffected: `DemoTransport` never sets `catchUpUntil` or `replay`. Part A's player tests and flow parity must stay green unchanged.

- [ ] **Step 2: Workbench changes (tests first)**

Write `app/live.test.ts` with one test per row of the table above, then change `workbench.ts`:

```ts
  private hydrated = new Set<string>();
  private get live(): LiveDataSource | null {
    return this.services.mode === "live" ? (this.services.data as LiveDataSource) : null;
  }

  /** Live only: show the current session's last run, or re-attach to it if it is still going. */
  async boot(): Promise<void> {
    const live = this.live;
    if (!live) return;
    const cur = curSession(this.stores.session.get());
    const lastId = cur.runIds.at(-1);
    if (!lastId) return;
    const last = this.stores.runs.get().byId[lastId];
    if (last && (last.status === "running" || last.status === "waiting")) return this.reattach(lastId);
    await this.hydrate(lastId);
    this.ui({ viewingRunId: lastId, benchKey: this.stores.ui.get().benchKey + 1 });
  }

  private async hydrate(id: string): Promise<void> {
    const live = this.live;
    if (!live || this.hydrated.has(id)) return;
    const stub = this.stores.runs.get().byId[id];
    if (!stub || stub.status === "running" || stub.status === "waiting") return;
    const player = new Player(this.stores, { runId: id, sessionId: stub.sessionId, momentDwell: false, replay: true, source: (t) => live.toolSource(t) });
    for (const e of await live.runEvents(id)) await player.push(e);
    this.hydrated.add(id);
  }

  private async reattach(runId: string): Promise<void> {
    const live = this.live!;
    const info = await live.getRun(runId);
    const sid = this.stores.session.get().curId;
    const player = new Player(this.stores, {
      runId, sessionId: sid, momentDwell: true, source: (t) => live.toolSource(t), catchUpUntil: new Date().toISOString(),
    });
    this.players.set(runId, player);
    this.hydrated.add(runId);
    this.ui({ busy: true, currentRunId: runId, viewingRunId: runId, benchKey: this.stores.ui.get().benchKey + 1 });
    let quietTimer: ReturnType<typeof setTimeout> | null = null;
    const openPending = () => {
      const p = info.pending;
      const run = this.stores.runs.get().byId[runId];
      if (!p || run?.status !== "waiting" || this.stores.ui.get().dialog) return;
      this.ui({
        dialog: p.kind === "confirm_exec"
          ? { kind: "approval", runId, tool: p.payload.tool, code: p.payload.preview }
          : { kind: "key", runId, toolName: p.payload.tool_name, envVar: p.payload.env_var, service: p.payload.service },
      });
    };
    this.services.transport.subscribe(runId, async (e) => {
      await this.liveSink(player)(e);
      if (info.status === "waiting") {
        if (quietTimer) clearTimeout(quietTimer);
        quietTimer = setTimeout(openPending, 150);
      }
    });
  }

  /** Wraps a live player's sink: after run.finished, reload the vault from the API. */
  private liveSink(player: Player) {
    return async (e: RunEvent) => {
      await player.push(e);
      if (e.type === "run.finished" && this.live) await this.refreshVault();
    };
  }
```

`openPending` is keyed off the backlog going quiet, not off the replayed `interrupt`. A waiting run's backlog always ends in its unresolved `interrupt`, and nothing more arrives until the user answers. So 150 ms of silence after the burst means "caught up", and a backlog that holds an earlier, already-resolved interrupt never flashes a dialog.

Other changes:
- `submit`: wrap `startRun` in `try/catch`. On `ApiError` with `code === "run_active"`, set `busy: false`, then `if (err.sessionId === curId && err.runId) await this.reattach(err.runId)`. On any other error, set `busy: false` and `console.error` (there is no reference copy for errors, so don't invent any). In live mode subscribe with `this.liveSink(player)` instead of `player.push`.
- `viewRun`, `openSession`, `backToNow`: `await this.hydrate(id)` for the run about to be viewed. `viewRun` and `openSession` become `async`; the components already call them fire-and-forget.
- `showView(v)`: live only, before the existing logic: `"vault"` → `await this.refreshVault()` (and `loadSource` of the first visible row when nothing is selected); `"sessions"` → `await this.refreshSessions()`; `"settings"` → `this.stores.settings.set(await live.settings())`. Keep the existing ordering of `viewEnter`/`stagger`. Only the data refresh is added in front.
- `refreshVault()`: `this.stores.vault.update((v) => ({ ...v, tools }))` with `tools = await live.vault()`. Keep `sources`, except drop the entries for tools that are gone.
- `refreshSessions()`: `GET /api/sessions` → `loadSessions` for sessions not yet in the store (by id) → add them as past sessions (`live: false`) and their stub runs. Sessions already in the store keep their messages and runs.
- `newSession()`: live → `await live.newSession()`. If `rec.id === curId`, only bump `titleAnimate`; otherwise part A's `openNewSession` path. Set `live.setCurrentStarted(rec.started)` so "New this session" follows the new session.
- `selectTool(name)` in live: `await this.loadSource(name)` before the existing body, so the detail cross-fades once, with its source already in place. Never with the demo-only "Source lives at…" line (Task 4).
- `reset()` is demo-only already (the button isn't rendered in live mode). Add `if (this.services.mode !== "demo") return;` as a guard.

- [ ] **Step 3: `createServices("live")` and `main.tsx`**

In `services.ts`, replace ruling 12's live branch:

```ts
export async function createServices(mode: Mode): Promise<{ stores: Stores; services: Services }> {
  if (mode === "live") return createLiveServices();
  // … part A's demo body unchanged …
}

async function createLiveServices(): Promise<{ stores: Stores; services: Services }> {
  const api = createApi();
  const data = new LiveDataSource(api);
  const [settings, list] = await Promise.all([data.settings(), api.listSessions()]);
  const head = list[0];
  const current = head ? { id: head.id, name: head.name, started: head.created_at } : await data.newSession();
  data.setCurrentStarted(current.started);
  const [tools, loaded] = await Promise.all([data.vault(), data.loadSessions(list)]);
  const cur = loaded.find((l) => l.rec.id === current.id);
  const past = loaded.filter((l) => l !== cur);
  const stores = createStores({
    tools, settings, sessions: past.map((l) => l.rec), runs: loaded.flatMap((l) => l.runs), current, count: 0,
  });
  if (cur) stores.session.update((s) => ({ ...s, sessions: s.sessions.map((x) => (x.id === cur.rec.id ? { ...x, runIds: cur.rec.runIds, messages: cur.rec.messages } : x)) }));
  stores.ui.set({ selected: null });
  return { stores, services: { mode: "live", data, transport: new LiveTransport(api), demo: null, lastRunNumber: 0 } };
}
```

`selected: null`: the reference's initial `caesar_cipher` selection only makes sense with the demo's vault. In live mode the Vault falls back to the first row, exactly as `renderVault` does when the selected tool isn't found (line 1968).

`main.tsx`: after creating the `Workbench`, call `void workbench.boot()` (a no-op in demo mode). Keep the booting class and its timing exactly as part A wrote them.

- [ ] **Step 4: Run everything**

Run: `npx vitest run src/transport/player.test.ts src/app/live.test.ts && npm test && npm run lint && npm run typecheck && npm run build`
Expected: PASS. Part A's `workbench.test.ts`, `App.test.tsx` and flow parity are unchanged and green.

- [ ] **Step 5: Try it against the fake graph**

```bash
# terminal 1 (repo root): uv run python frontend/e2e/serve_backend.py   (Task 5), or make fake with a local DB
# terminal 2: cd frontend && npm run build && open http://127.0.0.1:8765/
```

(If Task 5 isn't done yet: `DATABASE_URL=postgresql+psycopg://talos:talos@localhost:55432/talos_e2e TALOS_FAKE_GRAPH=1 uv run talos-web` after creating that database, and `npm run dev` with its `/api` proxy on 8000.)

Click the Caesar suggestion. It should animate like `/?demo`. Reload in the middle of it: it picks up where it is. Ask the Python question, reload with the dialog open: the dialog comes back.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/transport/player.ts frontend/src/transport/player.test.ts frontend/src/app/workbench.ts frontend/src/app/live.test.ts frontend/src/services.ts frontend/src/main.tsx
git commit -m "[Feat]: Boot live mode from the API, re-attach to running and paused runs, replay past runs"
```

---

### Task 4: Live-mode differences (spec 04 §8), and nothing else

**Files:**
- Modify: `frontend/src/components/settings/SettingsView.tsx`, `frontend/src/components/workbench/Idle.tsx`, `frontend/src/components/vault/VaultView.tsx`, `frontend/src/App.tsx`
- Test: `frontend/src/app/liveCopy.test.tsx` (new)

The whole list of what live mode shows differently, and where it comes from:

| §8 item | Live behaviour | Where |
|---|---|---|
| 8.1 Demo controls | not rendered | part A already (`mode === "demo"` in `Header`); tested here |
| 8.2 key dialog footer | `COPY.key.foot` only, without `COPY.key.footDemo` | part A already (`ModalRoot demo={wb.mode === "demo"}`); tested here |
| 8.2 weather result, `print()` result, unknown-query flow | whatever the server sends (captions, results, answers) | nothing to do: server facts |
| 8.2 "Source lives at … This demo only bundles …" | never shown: no `noSource` paragraph in live mode | `VaultView` prop `demo` |
| 8.2 seeded sessions | real history | Task 3 (`createLiveServices` never calls `seedSessions`) |
| data: header model, Settings keys and facts, idle setup line counts | from `GET /api/settings` | `SettingsView` prop `live`, `Idle` prop `keys` |

- [ ] **Step 1: Write the failing test** `frontend/src/app/liveCopy.test.tsx`

Render `App` with stores built from a fake live world (reuse Task 3's test helpers), with `mode: "live"`, and assert:

1. No `#demo-toggle`, no `#demo-pop`, and no `Reset the demo` anywhere. `.top-right .model` shows the settings' model.
2. With `ui.dialog` a key request, `.d-foot` text is exactly `If you skip, the tool is still saved to the vault, but it fails when it runs until the key is set.`.
3. The Vault detail for a tool whose source is `null` has no `.code-read` figure and no text containing `This demo only bundles`. With a source, the figure and `Read full file` are there, and the caption is `{n} lines, written by the Forger` with `n` from `sourceLines`.
4. Settings with `live.keys` `[OPENROUTER set, TAVILY not set, JINA not set, LANGSMITH not set, OPENWEATHERMAP_API_KEY set]` renders five rows in that order. The descriptions are the reference's strings (`COPY.settings.keyDesc[name]`, and `COPY.settings.keyDesc.savedByHuman` for keys outside the four). The states are `Set` or `Not set` (with the `muted` class when not set). The facts read `3`, `10 seconds`, `120 seconds` and `2 failures in a row`, from `live`.
5. The idle setup line reads `2 of 5 keys set in .env. Ask before running code is on. Settings` for that settings object (counted from `live.keys`).
6. The whole rendered HTML in live mode contains none of: `Demo controls`, `This demo`, `demo keeps`, `Scripted runs`.

Also add one test that renders the same components in demo mode with part A's props and compares them to part A's parity fixtures (import the existing cases). This proves the new optional props change nothing when they're absent.

- [ ] **Step 2: Run it and watch it fail**

Run: `npx vitest run src/app/liveCopy.test.tsx` → FAIL on items 3–5.

- [ ] **Step 3: Implement with optional props (demo rendering byte-identical)**

- `SettingsView`: add `live?: LiveSettings`. When present, the key rows are `live.keys.map((k) => [k.name, k.set, COPY.settings.keyDesc[k.name] ?? COPY.settings.keyDesc.savedByHuman])`, instead of the reference's fixed five rows. The facts are `String(live.forgeRetries)`, `${live.testTimeoutS} seconds`, `${live.llmTimeoutS} seconds` and `fill(COPY.settings.pruneValue, { n: live.pruneAfter })`. Everything else, markup included, is unchanged.
- `Idle`: add `keys?: { set: number; total: number }`. When present, the `{keys}` fill is `${set} of ${total}`; otherwise part A's `weatherKeySet` choice.
- `VaultView`: add `demo: boolean`. The `COPY.vault.noSource` paragraph renders only when `demo` is true.
- `App.tsx` containers: `SettingsC` passes `live={settings.live}`; `BenchC` passes `keys` when `settings.live` is set (`set` = keys with `set`, `total` = all keys); `VaultC` passes `demo={wb.mode === "demo"}`.

`llm_timeout_s` is a float in stage 2 (`120.0`). Render it with `String(Math.round(n))` so `120 seconds` matches the reference.

- [ ] **Step 4: Run everything**

Run: `npm test && npm run lint && npm run typecheck && npm run build`
Expected: PASS, including every part A parity test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/SettingsView.tsx frontend/src/components/workbench/Idle.tsx frontend/src/components/vault/VaultView.tsx frontend/src/App.tsx frontend/src/app/liveCopy.test.tsx
git commit -m "[Feat]: Show live settings, keys and vault source, with only the spec 04 §8 differences"
```

---

### Task 5: Backend harness for the live e2e suite

**Files:**
- Create: `frontend/e2e/serve_backend.py`
- Create: `tests/test_e2e_serve_backend.py`
- Modify: `.gitignore`, `.dockerignore`

The harness gives every live e2e run a clean world: a fresh `talos_e2e` database, an empty temporary vault, workspace and `.env`, no API keys from the developer's shell, and the fake graph. Then it `exec`s the real server, so Playwright's `webServer` owns the process.

Isolation, exactly:

| Thing | Where it points | Why |
|---|---|---|
| `DATABASE_URL` | `E2E_DATABASE_URL`, default `postgresql+psycopg://talos:talos@localhost:55432/talos_e2e` | `talos_e2e` is dropped (`WITH (FORCE)`) and created on each start, through the server's `postgres` maintenance database. The `talos` database that the stage 1 integration suite truncates is never touched. |
| `TALOS_VAULT_DIR` | `frontend/.e2e-tmp/vault` (with an empty `tools/`) | The fake graph copies this folder into its own temp folder, minus `caesar_cipher` and `get_current_temperature`, and forges into the copy (plan 02, fake-graph decision). So the Vault starts empty on every run, and the repo's `talos/vault` is never read or touched. |
| `TALOS_WORKSPACE_DIR` | `frontend/.e2e-tmp/workspace` | |
| `TALOS_DOTENV_PATH` | `frontend/.e2e-tmp/.env` (created empty) | Set before `talos.config.settings` is imported, so the repo `.env` is never loaded, and Settings lists no saved keys. The fake graph never writes `.env` (it remembers a saved key as "set" in memory only), and the keys spec asserts the file stays empty. |
| API keys | every `*_API_KEY`, `LANGSMITH_*` and `TALOS_AUTO_APPROVE_EXEC` are removed from the child env | So Settings shows only what the tests set, and the key dialog always appears. |
| Server | `TALOS_FAKE_GRAPH=1`, `TALOS_WEB_HOST=127.0.0.1`, `TALOS_WEB_PORT=8765` | Port 8765 avoids a developer's own 8000. |

`frontend/.e2e-tmp/` is a fixed path (not `mkdtemp`) because Playwright evaluates its config in every worker process, and the specs need to find the `.env` file.

Because the fake graph keeps saved keys in memory for the server's lifetime, the specs that need the key dialog run before `09-keys.spec.ts`, which is the only one that saves a key. Every other spec uses **Skip**. It is wiped at the **start** of each run, not the end, so a failed run leaves its vault and `.env` for debugging.

- [ ] **Step 1: Write the failing test**

`tests/test_e2e_serve_backend.py` loads the script by path (it is not a package module) and tests the pure parts:

```python
"""Unit tests for the live e2e backend harness (no database, no server)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "frontend" / "e2e" / "serve_backend.py"


def _load():
    spec = importlib.util.spec_from_file_location("serve_backend", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_child_env_strips_keys_and_points_at_tmp(tmp_path: Path) -> None:
    mod = _load()
    base = {
        "PATH": "/bin",
        "OPENROUTER_API_KEY": "sk-real",
        "OPENWEATHERMAP_API_KEY": "real",
        "LANGSMITH_TRACING": "true",
        "TALOS_AUTO_APPROVE_EXEC": "true",
        "DATABASE_URL": "postgresql+psycopg://me:me@localhost:5432/mine",
    }
    env = mod.child_env(base, tmp_path, "postgresql+psycopg://talos:talos@localhost:55432/talos_e2e")
    assert "OPENROUTER_API_KEY" not in env
    assert "OPENWEATHERMAP_API_KEY" not in env
    assert "LANGSMITH_TRACING" not in env
    assert "TALOS_AUTO_APPROVE_EXEC" not in env
    assert env["DATABASE_URL"].endswith("/talos_e2e")
    assert env["TALOS_FAKE_GRAPH"] == "1"
    assert env["TALOS_VAULT_DIR"] == str(tmp_path / "vault")
    assert env["TALOS_WORKSPACE_DIR"] == str(tmp_path / "workspace")
    assert env["TALOS_DOTENV_PATH"] == str(tmp_path / ".env")
    assert env["TALOS_WEB_HOST"] == "127.0.0.1"
    assert env["TALOS_WEB_PORT"] == "8765"
    assert env["PATH"] == "/bin"


def test_admin_url_targets_the_maintenance_database() -> None:
    mod = _load()
    name, admin = mod.split_db_url("postgresql+psycopg://talos:talos@localhost:55432/talos_e2e")
    assert name == "talos_e2e"
    assert admin == "postgresql://talos:talos@localhost:55432/postgres"


def test_refuses_a_database_that_is_not_an_e2e_one() -> None:
    mod = _load()
    import pytest

    with pytest.raises(SystemExit):
        mod.split_db_url("postgresql+psycopg://talos:talos@localhost:55432/talos")


def test_prepare_tmp_wipes_and_recreates(tmp_path: Path) -> None:
    mod = _load()
    root = tmp_path / ".e2e-tmp"
    (root / "vault" / "tools").mkdir(parents=True)
    (root / "vault" / "tools" / "old.py").write_text("x = 1\n")
    mod.prepare_tmp(root)
    assert (root / "vault" / "tools").is_dir()
    assert not (root / "vault" / "tools" / "old.py").exists()
    assert (root / "workspace").is_dir()
    assert (root / ".env").read_text() == ""
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_e2e_serve_backend.py -q`
Expected: FAIL (`FileNotFoundError` for the script).

- [ ] **Step 3: Write the harness**

`frontend/e2e/serve_backend.py`:

```python
"""Start talos-web for the live Playwright suite, isolated from real data.

Run from the repo root: ``uv run python frontend/e2e/serve_backend.py``.
Playwright's webServer starts it; see frontend/playwright.live.config.ts.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger("talos.e2e")

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / "frontend" / ".e2e-tmp"
DEFAULT_DB = "postgresql+psycopg://talos:talos@localhost:55432/talos_e2e"
PORT = "8765"
_DROP_PREFIXES = ("LANGSMITH_",)
_DROP_NAMES = {"TALOS_AUTO_APPROVE_EXEC", "DATABASE_URL"}


def split_db_url(url: str) -> tuple[str, str]:
    """Return (database name, libpq URL of the server's `postgres` database).

    Refuses any database whose name doesn't end in ``_e2e``, because the harness drops it.
    """
    parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    name = parts.path.lstrip("/")
    if not name.endswith("_e2e"):
        raise SystemExit(f"E2E_DATABASE_URL must name a *_e2e database, got {name!r}")
    return name, parts._replace(path="/postgres").geturl()


def recreate_database(url: str) -> None:
    """Drop and create the e2e database."""
    import psycopg
    from psycopg import sql

    name, admin = split_db_url(url)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    logger.info("recreated database %s", name)


def prepare_tmp(root: Path) -> None:
    """Wipe and recreate the vault, workspace and .env under ``root``."""
    shutil.rmtree(root, ignore_errors=True)
    (root / "vault" / "tools").mkdir(parents=True)
    (root / "workspace").mkdir()
    (root / ".env").write_text("", encoding="utf-8")


def child_env(base: dict[str, str], root: Path, db_url: str) -> dict[str, str]:
    """Build the server's environment: no real keys, tmp paths, fake graph."""
    env = {
        k: v
        for k, v in base.items()
        if not k.endswith("_API_KEY") and not k.startswith(_DROP_PREFIXES) and k not in _DROP_NAMES
    }
    env.update(
        DATABASE_URL=db_url,
        TALOS_FAKE_GRAPH="1",
        TALOS_VAULT_DIR=str(root / "vault"),
        TALOS_WORKSPACE_DIR=str(root / "workspace"),
        TALOS_DOTENV_PATH=str(root / ".env"),
        TALOS_WEB_HOST="127.0.0.1",
        TALOS_WEB_PORT=PORT,
    )
    return env


def main() -> None:
    """Prepare the isolated world, then replace this process with the server."""
    logging.basicConfig(level=logging.INFO)
    db_url = os.environ.get("E2E_DATABASE_URL") or DEFAULT_DB
    recreate_database(db_url)
    prepare_tmp(TMP)
    env = child_env(dict(os.environ), TMP, db_url)
    os.execve(sys.executable, [sys.executable, "-m", "talos.web"], env)


if __name__ == "__main__":
    main()
```

Notes:
- `python -m talos.web` is stage 2's entry point (the same code as `talos-web`). Using `sys.executable` keeps it inside uv's venv.
- The server serves `frontend/dist`, resolved from the project root (stage 2 §4 static files; stage 03 relies on the same path). So the live suite runs against the production build on one origin and needs no Vite proxy. `npm run build` must run first.

- [ ] **Step 4: Ignore the generated folders**

Stage 03 (`node_modules/`) and part A Task 1 (`frontend/node_modules/`, `frontend/dist/`) already added their lines to `.gitignore`. Append, under part A's `# Frontend (frontend/)` block:

```
frontend/.e2e-tmp/
frontend/test-results/
frontend/playwright-report/
frontend/e2e/visual/__screenshots__/
```

(Stage 03's `.dockerignore` already excludes `frontend/.e2e-tmp`, `frontend/test-results` and `frontend/playwright-report`. Add `frontend/e2e/visual/__screenshots__` there too.)

- [ ] **Step 5: Run the tests, then the harness by hand**

Run: `uv run pytest tests/test_e2e_serve_backend.py -q` → 4 passed.

Then, with part A's build in place (`cd frontend && npm run build`) and the test Postgres up (`docker start talos-pg-test`):

```bash
uv run python frontend/e2e/serve_backend.py &
until curl -sf http://127.0.0.1:8765/api/health; do sleep 1; done; echo
curl -s http://127.0.0.1:8765/api/settings | python3 -m json.tool | grep -c '"set": true'   # 0
curl -s http://127.0.0.1:8765/ | grep -c '<div id="root">'                                  # 1
kill %1
```

Expected: health shows `"fake_graph": true` and `"db": true`, no key is set, and `/` serves the built `index.html`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add frontend/e2e/serve_backend.py tests/test_e2e_serve_backend.py .gitignore .dockerignore
git commit -m "[Chore]: Add the isolated backend harness for the live e2e suite"
```

---

### Task 6: Playwright setup, shared helpers and scripts

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/eslint.config.js`
- Create: `frontend/tsconfig.e2e.json`
- Create: `frontend/playwright.visual.config.ts`, `frontend/playwright.live.config.ts`
- Create: `frontend/e2e/support/clock.ts`, `frontend/e2e/support/freeze.ts`, `frontend/e2e/support/keyboard.ts`, `frontend/e2e/support/queries.ts`
- Create: `frontend/e2e/live/fixtures.ts`, `frontend/e2e/live/00-boot.spec.ts`, `frontend/e2e/visual/00-smoke.spec.ts`

- [ ] **Step 1: Add axe (Playwright is already there)**

Part A pinned `@playwright/test@1.63.0` and `@types/node` and installed Chromium (part A ruling 13). Don't add them again.

```bash
cd frontend
npm install -D --save-exact @axe-core/playwright@4.13.0
npx playwright install chromium   # no-op if part A already did it on this machine
```

Only Chromium. Parity is judged in one engine, the one the owner reviews in.

- [ ] **Step 2: Scripts**

In `package.json` `scripts`, **replace** part A's placeholder `e2e` script and add two more:

```json
"e2e:visual": "playwright test -c playwright.visual.config.ts --project=ref-desktop --project=ref-mobile --update-snapshots=all && playwright test -c playwright.visual.config.ts --project=demo-desktop --project=demo-mobile",
"e2e:live": "playwright test -c playwright.live.config.ts",
"e2e": "npm run build && npm run e2e:visual && npm run e2e:live"
```

`e2e:visual` runs twice on purpose:

- The `ref-*` pass drives the reference `index.html` through every script and **writes** the baselines.
- The `demo-*` pass drives `/?demo` through the same scripts and **compares** against them.

The baselines are never committed. Font rasterisation differs between macOS and the Linux CI runner, and the reference rendered on the same machine in the same run is the only fair baseline. A `ref-*` test still fails if its script can't reach a state, so the scripts are checked against the reference too.

- [ ] **Step 3: Typecheck and lint the e2e code**

Part A's Vitest `include` is `src/**/*.test.{ts,tsx}`, so Vitest never picks up `e2e/`. Nothing to change there.

`frontend/tsconfig.e2e.json` (same shape as part A's `tsconfig.node.json`):

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.e2e.tsbuildinfo",
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["node"]
  },
  "include": ["e2e", "playwright.visual.config.ts", "playwright.live.config.ts"]
}
```

Add `{ "path": "./tsconfig.e2e.json" }` to the `references` in `frontend/tsconfig.json`. Part A's `typecheck` (`tsc -b --noEmit`) and `build` (`tsc -b && vite build`) then cover the e2e code with no script change. This was verified in a scratch project with TypeScript 5.9.3: a type error in `e2e/` fails `tsc -b --noEmit`.

In `frontend/eslint.config.js`, add a block after the TypeScript one. `e2e/` and the Playwright configs run in Node:

```js
  {
    files: ["e2e/**/*.ts", "playwright.*.config.ts"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
```

Also add `".e2e-tmp"`, `"test-results"`, `"playwright-report"` and `"e2e/visual/__screenshots__"` to the config's `ignores`.

- [ ] **Step 4: Shared helpers**

`frontend/e2e/support/clock.ts`. Both the reference and the React app use `setTimeout` and `requestAnimationFrame` for every wait. Playwright's clock owns both, so pausing it makes every intermediate state reachable on both pages by the same condition:

```ts
import type { Page } from "@playwright/test";
import { FREEZE_CSS } from "./freeze";

/** 30 Sep 2026, 14:20 UTC: "Today", after the seeded sessions on 28 Sep. */
export const T0 = Date.parse("2026-09-30T14:20:00Z");

/** Open the page with the clock paused, let boot finish, freeze animations, wait for fonts. */
export async function bootFrozen(page: Page, settleMs = 2000): Promise<void> {
  await page.clock.install({ time: T0 });
  await page.clock.pauseAt(T0 + 10);
  await page.goto("");
  await page.addStyleTag({ content: FREEZE_CSS });
  await page.clock.runFor(settleMs);
  await page.evaluate(() => document.fonts.ready);
}

/** Advance the paused clock in 10 ms steps until `selector` matches (or throw). */
export async function advanceUntil(page: Page, selector: string, maxMs = 60_000): Promise<void> {
  for (let t = 0; t <= maxMs; t += 10) {
    if ((await page.locator(selector).count()) > 0) return;
    await page.clock.runFor(10);
  }
  throw new Error(`never reached: ${selector}`);
}

/** Type into the composer and send, the way a person does. */
export async function ask(page: Page, text: string): Promise<void> {
  await page.locator("#ask").fill(text);
  await page.locator("#ask").press("Enter");
}

/** Advance until the newest Talos message has its "View this run" link (the run finished). */
export async function finishRun(page: Page, runsSoFar: number): Promise<void> {
  await advanceUntil(page, `.msg.talos .run-link >> nth=${runsSoFar}`);
}
```

`frontend/e2e/support/freeze.ts`:

```ts
/** Jump every animation and transition to its end state (spec 04 §9, with prefers-reduced-motion). */
export const FREEZE_CSS = `*,*::before,*::after{animation-delay:-1ms!important;animation-duration:1ms!important;animation-iteration-count:1!important;animation-fill-mode:both!important;transition-duration:0s!important;transition-delay:0s!important}`;
```

`frontend/e2e/support/queries.ts` (the reference's four suggestions, verbatim, plus the word-shift failure query):

```ts
export const Q = {
  forge: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.',
  reuse: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  fail: 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"',
  python: "Run this Python code and give me the output: print(sum(range(1, 101)))",
  weather: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
} as const;
```

`frontend/e2e/support/keyboard.ts`:

```ts
import { expect, type Page } from "@playwright/test";

/** Press Tab (or Shift+Tab) until `selector` has focus. Fails after `max` presses. */
export async function tabTo(page: Page, selector: string, opts: { back?: boolean; max?: number } = {}): Promise<void> {
  const key = opts.back ? "Shift+Tab" : "Tab";
  for (let i = 0; i < (opts.max ?? 80); i++) {
    if (await page.locator(selector).evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press(key);
  }
  await expect(page.locator(selector)).toBeFocused();
}
```

- [ ] **Step 5: The visual config**

`frontend/playwright.visual.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

const sizes = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } } as const;
const base = {
  ...devices["Desktop Chrome"],
  deviceScaleFactor: 1,
  reducedMotion: "reduce" as const,
  timezoneId: "UTC",
  locale: "en-GB",
};
const REF = "http://127.0.0.1:4599/index.html";
const DEMO = "http://127.0.0.1:4173/?demo";

export default defineConfig({
  testDir: "e2e/visual",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/visual" }]],
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.001, animations: "disabled", caret: "hide", scale: "css" },
  },
  projects: [
    ...(["desktop", "mobile"] as const).map((s) => ({
      name: `ref-${s}`,
      use: { ...base, viewport: sizes[s], baseURL: REF },
    })),
    ...(["desktop", "mobile"] as const).map((s) => ({
      name: `demo-${s}`,
      use: { ...base, viewport: sizes[s], baseURL: DEMO },
    })),
  ],
  webServer: [
    {
      command: "python3 -m http.server 4599 --bind 127.0.0.1 --directory ../docs/superpowers/specs/reference/workbench-demo",
      url: "http://127.0.0.1:4599/index.html",
      reuseExistingServer: !process.env.CI,
      stdout: "ignore",
    },
    {
      command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173/",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
```

Screenshot names carry the size (`03-idle-desktop.png`), not the project, so `ref-desktop` and `demo-desktop` share a file. `maxDiffPixelRatio: 0.001` is the spec's 0.1%. Screenshots are `fullPage: true` (passed per call), because at 390 px the bench stacks below the conversation.

- [ ] **Step 6: The live config**

`frontend/playwright.live.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e/live",
  fullyParallel: false,
  workers: 1, // one active run at a time across the app (stage 2 §4); state carries between files
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/live" }]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:8765",
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce", // the player caps every dwell at 40 ms (spec 04 §6), so runs finish fast
    permissions: ["clipboard-read", "clipboard-write"],
    trace: "retain-on-failure",
  },
  projects: [
    { name: "live-desktop", testIgnore: /mobile/ },
    { name: "live-mobile", testMatch: /07-a11y\.spec\.ts/, use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: "uv run python frontend/e2e/serve_backend.py",
    cwd: "..",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: false, // always a fresh database, vault and .env
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    stdout: "pipe",
  },
});
```

`reuseExistingServer` is always `false`: the harness's clean world is the point. The suite needs `npm run build` first; `npm run e2e` does that.

- [ ] **Step 7: Live fixtures**

`frontend/e2e/live/fixtures.ts`. Every live test gets an `app` helper that talks to the page and, for set-up and clean-up only, to the API:

```ts
import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// frontend/ is an ES module package, so there is no __dirname. npm scripts run in frontend/ (part A's convention).
export const DOTENV = resolve(process.cwd(), ".e2e-tmp/.env");

type RunInfo = { id: string; n: number; status: string };

export class LiveApp {
  runs: RunInfo[] = [];
  constructor(readonly page: Page, readonly api: APIRequestContext) {}

  /** Load the app and wait until boot has picked or created a session. */
  async open(): Promise<void> {
    await this.page.goto("/");
    await expect(this.page.locator("body")).not.toHaveClass(/booting/);
    await expect(this.page.locator("#session-title")).not.toHaveText("");
  }

  /** Send a question through the composer and remember its run. */
  async ask(text: string): Promise<RunInfo> {
    const posted = this.page.waitForResponse((r) => /\/api\/sessions\/[^/]+\/messages$/.test(r.url()) && r.request().method() === "POST");
    await this.page.locator("#ask").fill(text);
    await this.page.locator("#ask").press("Enter");
    const body = (await (await posted).json()) as { run: RunInfo };
    this.runs.push(body.run);
    return body.run;
  }

  /** Wait until the run is finished on the server and its "View this run" link is on the page. */
  async finished(run: RunInfo): Promise<string> {
    await expect.poll(async () => (await (await this.api.get(`/api/runs/${run.id}`)).json()).status, { timeout: 60_000 })
      .toMatch(/^(done|failed|stopped|declined)$/);
    await expect(this.page.locator(`.run-link[data-run="${run.n}"]`)).toBeVisible();
    return (await (await this.api.get(`/api/runs/${run.id}`)).json()).status as string;
  }

  async vaultNames(): Promise<string[]> {
    const v = (await (await this.api.get("/api/vault")).json()) as { tools: { name: string }[] };
    return v.tools.map((t) => t.name);
  }

  /** Remove a tool if present (set-up only). */
  async dropTool(name: string): Promise<void> {
    const r = await this.api.delete(`/api/vault/${name}`);
    expect([204, 404]).toContain(r.status());
  }

  async setAskBeforeExec(on: boolean): Promise<void> {
    await this.api.patch("/api/settings", { data: { ask_before_exec: on } });
  }

  dotenv(): string {
    return readFileSync(DOTENV, "utf-8");
  }

  /** Stop any run this test left going, so the next test isn't blocked by 409 run_active. */
  async cleanup(): Promise<void> {
    for (const run of this.runs) {
      const s = (await (await this.api.get(`/api/runs/${run.id}`)).json()).status as string;
      if (s === "running" || s === "waiting") await this.api.post(`/api/runs/${run.id}/stop`);
    }
    await this.setAskBeforeExec(true);
  }
}

export const test = base.extend<{ app: LiveApp }>({
  app: async ({ page, request }, use) => {
    const app = new LiveApp(page, request);
    await app.open();
    await use(app);
    await app.cleanup();
  },
});
export { expect };
```

- [ ] **Step 8: A smoke spec to prove the wiring, then commit**

`frontend/e2e/live/00-boot.spec.ts`:

```ts
import { test, expect } from "./fixtures";

test("live mode boots into a session with no Demo controls", async ({ app, page }) => {
  await expect(page.locator("#demo-toggle")).toHaveCount(0);
  await expect(page.locator(".top-right .model")).not.toHaveText("");
  await expect(page.locator("#view-workbench")).toBeVisible();
});
```

`frontend/e2e/visual/00-smoke.spec.ts`:

```ts
import { test, expect } from "@playwright/test";
import { bootFrozen } from "../support/clock";

const size = (name: string) => name.split("-")[1];

test("03 idle bench", async ({ page }, info) => {
  await bootFrozen(page);
  await expect(page).toHaveScreenshot(`03-idle-${size(info.project.name)}.png`, { fullPage: true });
});
```

Run:

```bash
npm run build
npm run e2e:visual   # 2 written by ref-*, 2 compared by demo-*
npm run e2e:live     # 1 passed
npm run lint && npm run typecheck && npm test
```

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/tsconfig.e2e.json frontend/eslint.config.js frontend/playwright.visual.config.ts frontend/playwright.live.config.ts frontend/e2e
git commit -m "[Chore]: Add axe, the visual and live Playwright configs and shared e2e helpers"
```

---

### Task 7: Visual parity suite (demo mode vs the reference)

**Files:**
- Create: `frontend/e2e/visual/shell.spec.ts`, `forge.spec.ts`, `runs.spec.ts`, `dialogs.spec.ts`, `vault.spec.ts`, `pages.spec.ts`
- Delete: `frontend/e2e/visual/00-smoke.spec.ts` (its shot moves into `shell.spec.ts`)

One screenshot per §4 inventory item reachable by script, at both sizes, every test starting from `bootFrozen`. The same script runs on the reference and on `/?demo`, which is possible because part A's DOM is the reference's DOM: same selectors, same `data-*` hooks. Only use selectors that exist in the reference file. Take every screenshot as `await expect(page).toHaveScreenshot(name(n, info), { fullPage: true })` with `const name = (n: string, info: TestInfo) => \`${n}-${info.project.name.split("-")[1]}.png\``.

The queries come from `e2e/support/queries.ts` (Task 6).

The shot list. "until" means `advanceUntil(page, selector)`; "run" means `ask(page, Q.x)` or a suggestion click; each run ends with `finishRun` before the next one starts.

| # (§4) | Name | Script |
|---|---|---|
| 1, 3 | `03-idle` | `bootFrozen` |
| 2 | `02-boot` | `bootFrozen(page, 300)`: mid-boot, `body.booting` still set |
| 4 | `04-empty-convo` | idle; element shot of `.convo` |
| 5, 24 | `05-planning` | click `.try[data-suggest="0"]`; until `.node.active[data-node="planner"]` and `.term-body .cmd:not(:has(.caret))` |
| 6 | `06-forging` | continue; until `.node.active[data-node="forger"]` and `.code-row[data-ln="30"]` |
| 7 | `07-testing-fail` | continue; until `.tests li.failed` |
| 8 | `08-retry` | continue; until `.code-row.changed` |
| 9 | `09-smoke-running`, `09-smoke-done` | continue; until `.smoke-body .gold`; then until `.smoke-body` has no `.gold` |
| 10 | `10-human-skip` | continue; until `.node.skip[data-node="human"]` |
| 11 | `11-saved-banner` | continue; until `.banner:not(.removed)` (badge on) |
| 12 | `12-executing` | continue; until `.args dt:nth-of-type(2)` |
| 13 | `13-answer` | continue; `finishRun(page, 0)` |
| 14 | `14-reuse`, `14-reuse-log` | run `Q.reuse` to the end; then click `[data-tab="log"]` |
| 15 | `15-tool-failure` | run `Q.fail` to the end |
| 16 | `16-pruned` | run `Q.fail` again to the end (`.banner.removed`) |
| 17 | `17-approval` | new boot; click `.try[data-suggest="2"]`; until `.dialog` |
| 18 | `18-declined` | click `[data-d="no"]`; `finishRun(page, 0)` |
| 19 | `19-key-dialog`, `19-key-empty-error` | new boot; click `.try[data-suggest="3"]`; until `#dlg-key`; shot; press Enter in `#dlg-key`; until `#dlg-err:not(:empty)`; shot |
| 20 | `20-key-skipped-failing` | click `[data-d="skip"]`; `finishRun(page, 0)` |
| 21 | `21-stopped` | new boot; click `.try[data-suggest="0"]`; until `.node.active[data-node="forger"]`; click `[data-action="stop"]`; `advanceUntil` `.msg.talos .note` |
| 22 | `22-view-earlier-run`, `22-earlier-list` | after the forge and reuse runs: click the first `.run-link`; shot; click `[data-tab="log"]`, then `.earlier button >> nth=0`; shot |
| 23 | `23-old-session` | new boot; nav `Sessions`; click `[data-open-session="seed-fib"]`; shot |
| 25 | `25-vault-table` | forge run to the end (for `New this session`); nav `Vault`; `runFor(1000)` |
| 26 | `26-search`, `26-filter-web`, `26-filter-failed`, `26-empty` | fill `#v-search` with `cipher`; clear; click `[data-filter="web"]`; `[data-filter="failed"]`; `[data-filter="all"]` and fill `zzzz` |
| 27 | `27-detail`, `27-remove-confirm` | click `[data-tool-btn="nth_fibonacci"]`; shot; click `[data-remove-tool]`; shot |
| 28 | `28-reader` | click `[data-tool-btn="caesar_cipher"]`; click `[data-read-src]`; until `.dialog.reader` |
| 29 | `29-sessions` | after one forge run: nav `Sessions` |
| 30 | `30-settings`, `30-settings-off` | nav `Settings`; shot; click `#ask-switch`; shot |

After each click, run `page.clock.runFor(50)` before the screenshot, so click-started timers (a tab's `panel-in`, the indicator) settle the same way on both pages. Hover states match because both pages get the same pointer moves.

Group them as: `shell.spec.ts` (2, 3, 4), `forge.spec.ts` (5–13, one test with a shot at each stage), `runs.spec.ts` (14, 15, 16, 21, 22), `dialogs.spec.ts` (17–20), `vault.spec.ts` (25–28), `pages.spec.ts` (23, 29, 30).

- [ ] **Step 1: Write `shell.spec.ts` and `forge.spec.ts`; run `npm run e2e:visual`**

Expected: the `ref-*` pass reaches every state and writes the PNGs. Any `demo-*` failure is a part A parity bug. Open `playwright-report/visual`, look at the diff image, fix the component (never the reference, never the threshold), and re-run. Commit the specs with their fixes: `[Fix]: <what differed>` for each fix, then `[Feat]: Add visual parity shots for the shell and the forge run`.

- [ ] **Step 2: Same for `runs.spec.ts` and `dialogs.spec.ts`**

Commit: `[Feat]: Add visual parity shots for reuse, failure, stop and both dialogs`.

- [ ] **Step 3: Same for `vault.spec.ts` and `pages.spec.ts`; delete `00-smoke.spec.ts`**

Run the whole visual suite twice in a row. Expected: green both times (proves determinism).

Commit: `[Feat]: Add visual parity shots for the vault, sessions and settings`.

---

### Task 8: Live e2e: the Caesar flows, sessions and the vault

**Files:**
- Create: `frontend/e2e/live/01-caesar.spec.ts`, `02-sessions.spec.ts`, `03-vault.spec.ts`

Files run in name order in one worker, and the server's state carries from file to file. Each file sets up what it needs through the API (`dropTool`, `setAskBeforeExec`), never by relying on an earlier file. The expected strings below are the fake graph's, which are the demo's (stage 2 §9, overview §4.5). They were checked against plan 02's fake-graph tests (`tests/web/test_fake_graph.py`). If an assertion here disagrees with the running fake graph, the fake graph's event log (`GET /api/runs/{id}/events?after=0`) decides, and the difference goes to the controller. Don't loosen an assertion to make it pass.

Two fake-graph facts shape the specs. The vault starts empty (plan 02: a temp copy of `TALOS_VAULT_DIR` minus the two demo tools). A tool that raises finishes the run with status `done`, `failed: true` and a `Failed, …` summary; only an unexpected exception gives status `failed`.

- [ ] **Step 1: `01-caesar.spec.ts`**

```ts
import { test, expect } from "./fixtures";
import { Q } from "../support/queries";

test.describe.serial("Caesar: forge, reuse, failure and prune", () => {
  test("forge with one retry", async ({ app, page }) => {
    await app.dropTool("caesar_cipher");
    const run = await app.ask(Q.forge);
    await expect(page.locator('.node.active[data-node="planner"]')).toBeVisible();
    await app.finished(run);
    for (const [k, s] of Object.entries({ planner: "done", forger: "forge", tester: "forge", human: "skip", learn: "done", executor: "done", answer: "answer" }))
      await expect(page.locator(`[data-node="${k}"]`)).toHaveClass(new RegExp(`\\b${s}\\b`));
    await expect(page.locator(".banner:not(.removed)")).toContainText("caesar_cipher is in the vault");
    await expect(page.locator("#vault-badge")).toBeVisible();
    const talos = page.locator(".msg.talos").last();
    await expect(talos).toContainText('"TALOS AGENT" encrypted with a shift of 7 is AHSVZ HNLUA.');
    await expect(talos.locator(".chip.forged")).toHaveText("Forged caesar_cipher");
    await page.locator('[data-tab="attempts"]').click();
    await expect(page.locator(".attempts li")).toHaveCount(2);
    await expect(page.locator(".attempts li").nth(1)).toContainText("Passed every test");
    expect(await app.vaultNames()).toContain("caesar_cipher");
  });

  test("reuse from the vault", async ({ app, page }) => {
    const run = await app.ask(Q.reuse);
    await app.finished(run);
    await expect(page.locator('[data-node="vault"]')).toHaveClass(/\bdone\b/);
    await expect(page.locator('[data-node="skip"]')).toHaveClass(/\bskip\b/);
    const talos = page.locator(".msg.talos").last();
    await expect(talos).toContainText("It decrypts to TALOS AGENT.");
    await expect(talos.locator(".chip.reused")).toHaveText("Reused caesar_cipher from the vault");
    await page.locator('[data-tab="log"]').click();
    await expect(page.locator("#term")).toHaveClass(/\bwarm\b/);
    await expect(page.locator("#term-status")).toHaveText("0 tools forged");
  });

  test("a word shift fails once, then the second failure prunes the tool", async ({ app, page }) => {
    let run = await app.ask(Q.fail);
    await app.finished(run);
    await expect(page.locator('[data-node="executor"]')).toHaveClass(/\bfail\b/);
    await expect(page.locator(".fig.alert .result")).toHaveText("TypeError: shift must be an int, got str");
    await expect(page.locator(".args .bad")).toHaveText('"seven"');
    await expect(page.getByRole("button", { name: "Ask again with shift 7" })).toBeVisible();
    await expect(page.locator(".msg.talos").last().locator(".chip.failed")).toHaveText("caesar_cipher raised a TypeError");

    run = await app.ask(Q.fail);
    await app.finished(run);
    await expect(page.locator(".banner.removed")).toContainText("caesar_cipher was removed from the vault");
    expect(await app.vaultNames()).not.toContain("caesar_cipher");
  });
});
```

The fixture gives each `test` a fresh page. `describe.serial` keeps the order and the server keeps the vault between them; the conversation is reloaded from the API each time, which also exercises boot into a session with runs. Check the exact selectors for the "Ask again" and "Open in vault" actions against part A's `CallPanel` and use the reference's markup.

- [ ] **Step 2: `02-sessions.spec.ts`**

Cover, in this order:

1. **Boot opens the newest session.** `GET /api/sessions` (via `app.api`)[0].name equals `#session-title`.
2. **An empty session is reused.** After a run, click `#new-session`: the title decodes to the new session's name, and the conversation shows `.empty-convo`. Click `#new-session` again: `POST /api/sessions` answers with the same session id (stage 2 reuses the newest empty session), the title is unchanged, and `GET /api/sessions` still doesn't list it. Reload: boot opens the newest session **with runs**, because the empty one isn't listed (ruling 7).
3. **The Sessions page.** Nav `Sessions`. A `section.day` with `h2` `Today`. The current session's card has `.live` `Now` and a `Continue` button. The previous session's card has `Open`, its run count (`1 run` / `2 runs`), and up to three queries. Empty sessions other than the current one aren't listed.
4. **Open an old session.** Click its `Open`. `.viewing-note` matches `/^.+, .+\. Read only\.$/`. `#back-session` is visible and `#new-session` hidden. `#ask` and `#send` are disabled. `#composer-hint` reads `Viewing an old session. Go back to ${current} to ask something.`. The bench shows the old session's last run in its final state (a `.node.answer`).
5. **Back to now.** Click `#back-session`. The composer is enabled, the hint reads `Enter to send, Shift+Enter for a new line`, and the title is the current session's.
6. **Reload keeps the conversation.** `page.reload()`. The same title, the same `.msg` count, and one `.run-link` per finished run. Click the first `.run-link`: the bench shows that run (its `#b-sig` and final strip), and `aria-current="true"` moves to that link.

- [ ] **Step 3: `03-vault.spec.ts`**

Set-up: `dropTool("caesar_cipher")`, then run `Q.forge` to the end (so there is at least one forged tool with source).

1. **Counts.** Nav `Vault`. `#c-all`, `#c-web` and `#c-failed` equal `count`, `web_count` and `failed_count` from `GET /api/vault`. `#v-lede` reads `${count} tools, every one written and tested by Talos. Stored as .py files and a manifest.json.`. The `caesar_cipher` row has `.newtag` `New this session`.
2. **Search.** Fill `#v-search` with `cipher`: the `caesar_cipher` row is shown, and `#v-count` reads `Showing N of M`. Fill `zzzz`: `.v-empty` reads `No tools match. Try another word, or clear the filter.`.
3. **Filters.** `[data-filter="web"]` has `aria-pressed="true"` and the row count equals `web_count`. The same for `failed`.
4. **Detail.** Click the `caesar_cipher` row button. `.v-detail h2` is `caesar_cipher`. `.sigbox` is `caesar_cipher(text: str, shift: int, mode: str) -> str`. The source preview `figure.code-read` is present. The page never contains `This demo only bundles`.
5. **Reader.** Click `Read full file`. `.dialog.reader h2` is `talos/vault/tools/caesar_cipher.py`, and the `p` reads `${lines} lines. Forged, tested and saved by Talos.`, with `lines` from `GET /api/vault/caesar_cipher`. Click `Copy`: it reads `Copied`, and the clipboard (`navigator.clipboard.readText()`) equals the API's `source` without its final newline. Then `Escape` closes it and focus returns to `Read full file`. Reopen, click the scrim (`#scrim` at position `{x: 5, y: 5}`) to close. Reopen and `Close` closes.
6. **Remove.** Click `Remove from vault`: it reads `Remove caesar_cipher?` and no request is sent. Click again: a `DELETE /api/vault/caesar_cipher` returns 204, the row is gone, and `vaultNames()` doesn't contain it.
7. **Use in a question.** Pick any tool, click `Use in a question`: the view is Workbench and `#ask` has the reference's preset text (`Use ${name} on ` for tools without a preset).

- [ ] **Step 4: Run and commit**

Run: `npm run build && npm run e2e:live` → all pass.

```bash
git add frontend/e2e/live
git commit -m "[Feat]: Add live e2e specs for the Caesar flows, sessions and the vault"
```

---

### Task 9: Live e2e: approvals, settings, keys, stop and reload

**Files:**
- Create: `frontend/e2e/live/04-approval.spec.ts`, `05-stop.spec.ts`, `06-reload.spec.ts`, `09-keys.spec.ts`

- [ ] **Step 1: `04-approval.spec.ts`**

1. **Approve.** `setAskBeforeExec(true)`. Ask `Q.python`. `.dialog` shows `h2` `Run this code on your machine?` and `.eyebrow` `python_exec needs your approval`, `pre` contains `print(sum(range(1, 101)))`, and `[data-d="no"]` (`Don't run`) is focused. The strip shows `Executor, waiting for you`. Click `Run code`. A `POST /api/runs/{id}/resume` has the body `{"decision":"approve"}`. The run finishes `done`, the Call panel's result is `5050`, and the answer contains `5050`.
2. **Decline.** Ask again, click `Don't run`. The body is `{"decision":"decline"}`. The executor label is `Executor, declined`, the run status is `declined`, and the earlier-runs list shows `Declined, nothing ran`.
3. **The dialog's Settings link.** Ask again, click the `Ask before running code` link in the dialog. The run is declined (the reference closes with `no`), and the Settings view is shown.
4. **The switch.** On Settings, click `#ask-switch`. A `PATCH /api/settings` has the body `{"ask_before_exec":false}`, and `aria-checked` is `"false"`. Back on the Workbench, the setup line (if idle) reads `… Ask before running code is off.`. Ask `Q.python`: no `.dialog` appears, the caption reads `Ran without asking, because "Ask before running code" is off in Settings.`, and the result is `5050`. Turn it back on and check that the dialog appears again.

- [ ] **Step 2: `05-stop.spec.ts`**

1. **Stop during a run.** `dropTool("caesar_cipher")`. Ask `Q.forge`, wait for `.node.active[data-node="forger"]`, click `Stop run`. A `POST /api/runs/{id}/stop` is sent. The status becomes `stopped`. A `.node.stopped` is present, the caption reads `You stopped this run. Nothing was saved to the vault.`, the Talos message ends with `.note` `Stopped. Ask again whenever you're ready.`, and the Run log has `stopped by you`. `vaultNames()` doesn't contain `caesar_cipher`. The composer is enabled again, with `Send`.
2. **Stop during a pause (Esc).** Ask `Q.python`, wait for `.dialog`, press `Escape`. A `/stop` request is sent and **no** `/resume` request (record requests with `page.on("request")`). The dialog is gone, focus is back on the composer, and the status is `stopped`.
3. **Busy composer.** While a run is going: `#send` reads `Working`, `#ask` is disabled, and the hint reads `Stop the run to ask something else`.

- [ ] **Step 3: `06-reload.spec.ts`**

1. **Approval survives a reload.** Ask `Q.python`, wait for `.dialog`, then `page.reload()`. After boot, the same session is open, the bench shows the paused run (Executor `Executor, waiting for you`), and the `.dialog` is back with the same `pre` text. Exactly one dialog. Click `Run code`: the run finishes `done` with `5050`.
2. **Key dialog survives a reload.** `dropTool("get_current_temperature")`. Ask `Q.weather`, wait for `#dlg-key`, reload, and `#dlg-key` is back and focused. Click `Skip`: the run finishes.
3. **Reload mid-run.** `dropTool("caesar_cipher")`. Ask `Q.forge`, wait for the forger to be active, reload. The run keeps going on the server, the page re-attaches, and it ends in the same final state as `01-caesar`'s forge test. Only one `.msg.talos` belongs to this run (no duplicated messages or log lines: the `.term-body .ln` count equals the count after a `View this run` replay of the same run).

- [ ] **Step 4: `09-keys.spec.ts`** (the last live file: it saves a key, which the fake graph remembers until the server stops)

1. **The dialog.** `dropTool("get_current_temperature")`. Ask `Q.weather`. `.dialog h2` reads `This tool needs an OpenWeatherMap key`, and the label is `OPENWEATHERMAP_API_KEY`. `.d-foot` reads exactly `If you skip, the tool is still saved to the vault, but it fails when it runs until the key is set.` (§8.2: the demo's last sentence is removed).
2. **Empty submit.** Press `Enter` in `#dlg-key`: `#dlg-err` reads `Paste the key first, or choose Skip.`, the input keeps focus, and no `/resume` is sent.
3. **Skip.** Click `Skip`. The body is `{"decision":"skip"}`. The run finishes, the Human check label is `Human check, skipped`, the executor failed, and `.fig.alert .result` reads `RuntimeError: OPENWEATHERMAP_API_KEY is not set`.
4. **Save.** `dropTool("get_current_temperature")`. Ask again, type `e2e-test-key`, click `Save key`. The body is `{"decision":"save","value":"e2e-test-key"}`. The caption reads `Saved OPENWEATHERMAP_API_KEY to .env. Talos won't ask again.`, and the run summary in the Earlier list is `1 tool forged, key saved`.
5. **It doesn't ask again.** Ask `Q.weather` again: no `.dialog` appears, and the strip is the vault variant.
6. **The value goes nowhere.** `e2e-test-key` appears nowhere in `document.body.innerHTML`, nowhere in the run's event log (`GET /api/runs/{id}/events?after=0` via `app.api`), and not in `app.dotenv()`, which is still empty (the fake graph never writes `.env`).

- [ ] **Step 5: Run and commit**

Run: `npm run build && npm run e2e:live` → all pass, twice in a row.

```bash
git add frontend/e2e/live
git commit -m "[Feat]: Add live e2e specs for approvals, settings, keys, stop and reload"
```

---

### Task 10: Accessibility and keyboard-only

**Files:**
- Create: `frontend/e2e/live/07-a11y.spec.ts`, `frontend/e2e/live/08-keyboard.spec.ts`

**Known reference defect.** At 390 px the reference's GitHub pill hides its label (`.gh-label`), so the link has no accessible name. axe reports `link-name` (serious) on `a[target="_blank"]` in the reference itself (measured on 30 Sep 2026 in all four views). Fixing it means changing the demo's DOM, which only the owner can approve. So the mobile axe run excludes exactly that one element, with a comment pointing here, and Task 12's PROGRESS entry lists it as an open owner decision. The other rules the reference trips are moderate (`landmark-one-main`, `landmark-main-is-top-level`). The spec's bar is no serious violations, so the assertion is on `serious` and `critical` only.

- [ ] **Step 1: `07-a11y.spec.ts`** (runs in both `live-desktop` and `live-mobile`)

```ts
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
import { Q } from "../support/queries";

async function noSerious(page: import("@playwright/test").Page, isMobile: boolean) {
  let axe = new AxeBuilder({ page });
  // Reference defect, kept for parity: see plan 04b Task 10.
  if (isMobile) axe = axe.exclude('.top-right a.pill[target="_blank"]');
  const { violations } = await axe.analyze();
  const bad = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
}
```

Tests, each calling `noSerious(page, testInfo.project.name === "live-mobile")`:

- Each view: Workbench idle, Workbench after a finished forge run (Code, Tests, Attempts, Call and Run log tabs each selected in turn), Vault with a tool selected, Sessions, Settings, an old session opened.
- Each dialog: approval (ask `Q.python`), key (`Q.weather` after `dropTool`), reader (Vault → `Read full file`).

- [ ] **Step 2: `08-keyboard.spec.ts`** (desktop only, no mouse calls at all: only `page.keyboard` and `tabTo`)

1. **Caesar by keyboard.** `dropTool("caesar_cipher")`. `tabTo(page, '.try[data-suggest="0"]')`, press `Enter`. Wait for the run to finish. `tabTo` the new `.run-link`, press `Enter`: its `aria-current` is `"true"`. `tabTo('[data-tab="code"]')`, press `Enter`: `aria-selected="true"`. `tabTo('.code-body')`: it is focusable (`tabindex="0"`). `tabTo('#ask')`, type `Q.reuse`, press `Enter`: the reuse run completes.
2. **Approval dialog by keyboard.** `tabTo('#ask')`, type `Q.python`, press `Enter`. `Don't run` is focused. `Tab` → `Run code`. `Tab` → the Settings link. `Tab` → back to `Don't run` (trapped). `Shift+Tab` → the Settings link. `Shift+Tab` twice → `Run code`, press `Enter`. The run finishes with `5050`, and focus returns to the composer.
3. **Key dialog by keyboard.** `dropTool("get_current_temperature")`. Type `Q.weather` into `#ask`, press `Enter`. `#dlg-key` is focused. Press `Enter`: the error shows and focus stays in the input. `Tab` → `Skip`, press `Enter`: the run goes on and ends with the tool failing without its key. (Don't save here: the fake graph would remember the key and `09-keys` would never see the dialog.)
4. **Esc cancels.** `Q.python`, then `Escape` in the dialog: the run is stopped.
5. **Reader by keyboard.** Nav with `tabTo('a[data-view="vault"]')` + `Enter`, `tabTo('[data-read-src]')` + `Enter`: `Close` is focused. `Escape` closes it and focus returns to `Read full file`.

- [ ] **Step 3: Run and commit**

Run: `npm run build && npm run e2e:live` → all pass.

```bash
git add frontend/e2e/live
git commit -m "[Feat]: Add axe checks on every view and dialog and keyboard-only runs"
```

---

### Task 11: CI frontend job

**Files:**
- Modify: `.github/workflows/ci.yml`

Stage 03 adds no placeholder job. It appends `integration` and `docker` and leaves the `frontend` job to this task (stage 03 plan, rulings and Task 9). So append `frontend` after `docker`, with two-space indentation under `jobs:`, in the same style as stage 03's `integration` job. Change no other job. Stage 03's `docker` job builds the image with the real frontend, via the Dockerfile's `frontend` stage (`npm ci`, `npm run build`). Playwright is a dev dependency and isn't used in that stage.

- [ ] **Step 1: Add (or fill) the `frontend` job**

```yaml
  frontend:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: talos
          POSTGRES_PASSWORD: talos
          POSTGRES_DB: talos
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U talos"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      E2E_DATABASE_URL: postgresql+psycopg://talos:talos@localhost:5432/talos_e2e
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --extra dev
        working-directory: .
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
      - run: npm run build
      - run: npx playwright install --with-deps chromium
      - run: npm run e2e:visual
      - run: npm run e2e:live
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: |
            frontend/playwright-report
            frontend/test-results
          retention-days: 7
```

- The harness drops and creates `talos_e2e` through the service's `postgres` database, and the server runs its own migrations on start (stage 2 §3). The job needs no `alembic` step.
- `CI=true` is set by Actions, so `reuseExistingServer` is off for the visual servers too.
- `python3` for the reference server is the runner's system Python. The backend uses uv's.

- [ ] **Step 2: Validate the YAML locally**

Run: `python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(sorted(d['jobs']))"` (use `uv run --with pyyaml` if PyYAML is missing).
Expected: `['docker', 'frontend', 'integration', 'lint', 'test']`, and `git diff .github/workflows/ci.yml` shows only added lines.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "[Chore]: Run the frontend lint, build, visual parity and live e2e suites in CI"
```

---

### Task 12: Docs and full verification

**Files:**
- Modify: `README.md` (the "Web app" section from stage 3, or a new "Frontend" subsection under it)
- Modify: `PROGRESS.md` (new section `## Web app stage 04 — Frontend ✅` before `## Session log`, plus a session-log line)

- [ ] **Step 1: README, frontend and dev section**

Add, in the README's existing voice (short sentences, commands in code blocks):

- **Live and demo mode.** `http://127.0.0.1:8000` is live. `/?demo` (or a build with `VITE_DEMO=1`) is the scripted demo with no backend, including Demo controls.
- **Develop the frontend.** `make db` (or the `talos-pg-test` container), `make fake` (`TALOS_FAKE_GRAPH=1 uv run talos-web`), then `make fe` (`cd frontend && npm run dev`). Vite proxies `/api` to `127.0.0.1:8000`. No model key is needed with the fake graph.
- **Frontend checks.** `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- **Playwright.** `npx playwright install chromium` once. `npm run e2e:visual` compares `/?demo` with the reference file at 1440×900 and 390×844; the baselines are rendered from the reference in the same run and never committed. `npm run e2e:live` starts an isolated fake-graph server on port 8765 with the `talos_e2e` database on `E2E_DATABASE_URL` (default `postgresql+psycopg://talos:talos@localhost:55432/talos_e2e`), and a throwaway vault, workspace and `.env` in `frontend/.e2e-tmp/`. **Warning:** the harness drops and recreates that database; it refuses any name not ending in `_e2e`.

- [ ] **Step 2: PROGRESS.md**

A stage 04 section in the same shape as the stage 01 one: what shipped (part A and part B), the test counts (Vitest, visual shots per size, live specs, pytest), and the open owner decisions:

1. The reference's GitHub pill has no accessible name at 390 px (axe `link-name`, serious). It is kept for parity and excluded in one place.
2. Settings key descriptions for keys saved by Human check use the reference's `Saved by Human check this session.` even for keys saved in earlier sessions (word-for-word rule).
3. Numbers inside frontend copy (the approval dialog's 10 seconds, the Tests panel's 10-second note, the health meter's 2) stay literal and don't follow `.env` changes.
4. Part A's ruling 1 (`forge.code.tests`) and this plan's `call.error.when` mapping, for stage 2 to confirm.
5. The owner's side-by-side sign-off on live mode (spec 04 §10).

Also a session-log line for today.

- [ ] **Step 3: Full verification (evidence before claims)**

Run each and read the output:

```bash
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
npm run e2e:visual
npm run e2e:live
cd ..
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git status --short   # only the intended files; nothing under frontend/.e2e-tmp, test-results, playwright-report or __screenshots__
```

Expected: every command exits 0. Record the counts (Vitest tests, visual shots compared, live tests, pytest passed/skipped) in PROGRESS.md.

- [ ] **Step 4: Commit**

```bash
git add README.md PROGRESS.md
git commit -m "[Docs]: Document the live frontend, the e2e suites and stage 04 progress"
```
