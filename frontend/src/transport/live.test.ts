import { beforeEach, expect, test, vi } from "vitest";
import { createApi, type Api } from "./api";
import { LiveTransport, normalise } from "./live";
import type { ApiRunSummary, EventData, EventType, RunEvent } from "./types";

const env = <T extends EventType>(seq: number, type: T, data: EventData[T], ts = "2026-09-30T10:00:00Z") =>
  ({ run_id: "r1", seq, ts, type, data }) as RunEvent;

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
  emit(e: RunEvent) {
    this.listeners.get(e.type)?.({ data: JSON.stringify(e) } as MessageEvent<string>);
  }
}
beforeEach(() => {
  FakeES.all = [];
});

const runSummary = (n: number): ApiRunSummary => ({
  id: `run-${n}`, n, query: "q", status: "running", summary: null, summary_gold: false, forged: [], used: [], failed: false,
  started_at: "2026-09-30T10:00:00Z", finished_at: null,
});

function fakeApi(over: Partial<Api> = {}): Api {
  const fail = () => Promise.reject(new Error("not stubbed"));
  return {
    listSessions: fail, createSession: fail, getSession: fail, send: fail, getRun: fail, runEvents: fail, resume: fail, stop: fail,
    vault: fail, tool: fail, removeTool: fail, settings: fail, setAskBeforeExec: fail, ...over,
  };
}

test("startRun posts the text and returns no session name after the first run", async () => {
  const send = vi.fn(async () => ({ run: runSummary(2), message: {} as never }));
  const getSession = vi.fn();
  const t = new LiveTransport(fakeApi({ send, getSession }));
  expect(await t.startRun("s1", "hello")).toEqual({ runId: "run-2", n: 2, sessionName: null });
  expect(send).toHaveBeenCalledWith("s1", "hello");
  expect(getSession).not.toHaveBeenCalled();
});

test("startRun reads the new session name back on the first run", async () => {
  const send = vi.fn(async () => ({ run: runSummary(1), message: {} as never }));
  const getSession = vi.fn(async () => ({
    session: { id: "s1", name: "Caesar shift", number: 1, created_at: "", updated_at: "" }, messages: [], runs: [],
  }));
  const t = new LiveTransport(fakeApi({ send, getSession }));
  expect(await t.startRun("s1", "hello")).toEqual({ runId: "run-1", n: 1, sessionName: "Caesar shift" });
  expect(getSession).toHaveBeenCalledWith("s1");
});

test("startRun still returns the run when reading the new session name back fails: the run has started", async () => {
  const warn = vi.spyOn(console, "error").mockImplementation(() => {});
  const send = vi.fn(async () => ({ run: runSummary(1), message: {} as never }));
  const getSession = vi.fn(async () => Promise.reject(new Error("down")));
  const t = new LiveTransport(fakeApi({ send, getSession }));
  expect(await t.startRun("s1", "hello")).toEqual({ runId: "run-1", n: 1, sessionName: null });
  warn.mockRestore();
});

test("normalise sanitises caption, forge.code note and answer HTML", () => {
  const c = normalise(env(1, "caption", { html: 'A <span class="mono">x</span><img src=x onerror=alert(1)>' }));
  expect(c.data).toEqual({ html: 'A <span class="mono">x</span>' });
  const a = normalise(
    env(2, "answer.done", { html: "<b>hi</b> <script>x</script>", note: '<a href="javascript:1">n</a>', chips: [{ kind: "forged", text: "F" }] }),
  );
  expect(a.data).toEqual({ html: "hi x", note: "n", chips: [{ kind: "forged", text: "F" }] });
  const f = normalise(env(5, "forge.code", { tool: "t", attempt: 2, file: "t.py", lines: ["x"], changed: 1, note: "Line 1 <b>is</b> new", tests: 2 }));
  expect(f.data).toMatchObject({ note: "Line 1 is new", lines: ["x"], tests: 2 });
  const fn = env(6, "forge.code", { tool: "t", attempt: 1, file: "t.py", lines: [], changed: null, note: null });
  expect(normalise(fn)).toBe(fn);
  const n = normalise(env(3, "answer.done", { html: "ok", note: null, chips: [] }));
  expect(n.data).toMatchObject({ note: null });
});

test("normalise keeps call.error.when a code for the player, and returns every other event unchanged", () => {
  for (const when of ["declined", "run", "dispatch", "whatever"]) {
    const e = env(1, "call.error", { error: "boom", when });
    expect(normalise(e)).toBe(e);
  }
  const l = env(4, "log.line", { label: "Planner", text: "<b>raw</b>", tone: "plain" });
  expect(normalise(l)).toBe(l);
});

test("subscribe opens the run's stream at ?after, sinks normalised events, and the returned function closes it", () => {
  const got: RunEvent[] = [];
  const t = new LiveTransport(fakeApi(), FakeES as never);
  const off = t.subscribe("r1", async (e) => void got.push(e), 7);
  const es = FakeES.all[0]!;
  expect(es.url).toBe("/api/runs/r1/events?after=7");
  es.emit(env(8, "caption", { html: "<i>a</i>" }));
  expect(got).toHaveLength(1);
  expect(got[0]!.data).toEqual({ html: "a" });
  off();
  expect(es.closed).toBe(true);
});

test("resume and stop call the API; a saved key's value goes only into the one request body", async () => {
  const bodies: string[] = [];
  const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    bodies.push(String(init?.body ?? ""));
    return new Response(null, { status: 204 });
  });
  const t = new LiveTransport(createApi(fetchImpl as unknown as typeof fetch), FakeES as never);
  await t.resume("r1", { decision: "save", value: "k-123" });
  await t.stop("r1");
  expect(fetchImpl.mock.calls.map((c) => [String(c[0]), c[1]?.method])).toEqual([
    ["/api/runs/r1/resume", "POST"],
    ["/api/runs/r1/stop", "POST"],
  ]);
  expect(bodies.filter((b) => b.includes("k-123"))).toEqual([JSON.stringify({ decision: "save", value: "k-123" })]);
  expect(reachableStrings(t)).not.toContainEqual(expect.stringContaining("k-123"));
});

/** Every string reachable from `root` through own properties (enumerable or not), arrays, Maps and Sets. */
function reachableStrings(root: unknown): string[] {
  const out: string[] = [];
  const seen = new Set<unknown>();
  const walk = (v: unknown): void => {
    if (typeof v === "string") return void out.push(v);
    if (v === null || (typeof v !== "object" && typeof v !== "function") || seen.has(v)) return;
    seen.add(v);
    if (v instanceof Map)
      for (const [k, x] of v) {
        walk(k);
        walk(x);
      }
    else if (v instanceof Set) for (const x of v) walk(x);
    if (typeof v === "object") for (const k of Object.getOwnPropertyNames(v)) walk((v as Record<string, unknown>)[k]);
  };
  walk(root);
  return out;
}

test("the key check sees values a transport keeps in a Map or a non-enumerable field", () => {
  const leaky = { cache: new Map([["r1", { value: "k-123" }]]) };
  Object.defineProperty(leaky, "hidden", { value: "k-123", enumerable: false });
  expect(JSON.stringify({ cache: leaky.cache })).not.toContain("k-123"); // why JSON.stringify couldn't fail
  expect(reachableStrings(leaky).filter((s) => s.includes("k-123"))).toHaveLength(2);
});
