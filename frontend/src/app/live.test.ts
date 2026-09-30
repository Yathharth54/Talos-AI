import { createLiveServices } from "../services";
import type { Stores } from "../store/stores";
import { setReducedMotion } from "../test/media";
import { ApiError, type Api } from "../transport/api";
import type {
  ApiMessage,
  ApiRun,
  ApiRunSummary,
  ApiSessionDetail,
  ApiSessionSummary,
  ApiSettings,
  ApiVaultEntry,
  EventData,
  EventType,
  RunEvent,
} from "../transport/types";
import { act, render } from "@testing-library/react";
import { createElement } from "react";
import type { Mock } from "vitest";
import { App } from "../App";
import { Workbench } from "./workbench";

/* Live mode's controller paths (spec 04 §5–§6, rulings 3, 4, 7, 10) against a fake stage 2 API. */

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

const NOW = "2026-09-30T12:00:00.000Z";
const EARLY = "2026-09-30T11:59:00.000Z";
const T0 = "2026-09-30T10:00:00.000Z";

let seq = 0;
const ev = <T extends EventType>(runId: string, type: T, data: EventData[T], ts = EARLY): RunEvent =>
  ({ run_id: runId, seq: ++seq, ts, type, data }) as RunEvent;

const summary = (id: string, n: number, status: ApiRunSummary["status"], query = `question ${n}`): ApiRunSummary => ({
  id, n, query, status, summary: status === "done" ? `Answered ${n}` : null, summary_gold: false, forged: [], used: [], failed: false,
  started_at: T0, finished_at: status === "done" ? T0 : null,
});
const msg = (id: string, role: ApiMessage["role"], html: string, runId: string): ApiMessage => ({
  id, role, html, note: null, chips: [], run_id: runId, created_at: T0,
});
const listed = (id: string, name: string, created_at: string): ApiSessionSummary => ({
  id, name, created_at, run_count: 1, forged: [], used: [], runs: [],
});
const detail = (id: string, name: string, runs: ApiRunSummary[]): ApiSessionDetail => ({
  session: { id, name, number: 1, created_at: T0, updated_at: T0 },
  messages: runs.flatMap((r) => [msg(`${r.id}-u`, "user", r.query, r.id), msg(`${r.id}-a`, "assistant", `Answer ${r.n}`, r.id)]),
  runs,
});
const finishedEvents = (r: ApiRunSummary): RunEvent[] => [
  ev(r.id, "run.started", { session_id: "x", query: r.query, n: r.n }),
  ev(r.id, "caption", { html: `Replayed ${r.n}` }),
  ev(r.id, "answer.done", { html: `Answer ${r.n}`, note: null, chips: [] }),
  ev(r.id, "run.finished", { status: "done", summary: `Answered ${r.n}`, summary_gold: false, forged: [], used: [] }),
];
const entry = (name: string): ApiVaultEntry => ({
  name, args: "x", ret: "str", signature: `${name}(x)`, description: "d", keywords: [], uses: 1, failures: 0, streak: 0,
  created_at: T0, last_used: null, last_failure: null, last_failed_at: null, web: false, file: `${name}.py`,
});
const settings = (model = "gpt-4o"): ApiSettings => ({
  model, ask_before_exec: true, forge_retries: 3, test_timeout_s: 10, llm_timeout_s: 60, prune_after: 2, keys: [],
});
const vaultList = (names: string[]) => ({ count: names.length, web_count: 0, failed_count: 0, tools: names.map(entry) });

interface World {
  sessions: ApiSessionDetail[];
  runs: Record<string, ApiRun>;
  events: Record<string, RunEvent[]>;
  tools: string[];
}

type FakeApi = { [K in keyof Api]: Mock<Api[K]> };

function fakeApi(w: World, over: Partial<Api> = {}): FakeApi {
  const api = {
    listSessions: vi.fn(async () => w.sessions.map((d) => listed(d.session.id, d.session.name, d.session.created_at))),
    createSession: vi.fn(async () => ({ id: "s-new", name: "Session 1", number: 1, created_at: NOW, updated_at: NOW })),
    getSession: vi.fn(async (id: string) => w.sessions.find((d) => d.session.id === id)!),
    send: vi.fn(async () => ({ run: summary("r-sent", 1, "running", "hello"), message: msg("m", "user", "hello", "r-sent") })),
    getRun: vi.fn(async (id: string) => w.runs[id]!),
    runEvents: vi.fn(async (id: string) => w.events[id] ?? []),
    resume: vi.fn(async () => undefined),
    stop: vi.fn(async () => undefined),
    vault: vi.fn(async () => vaultList(w.tools)),
    tool: vi.fn(async (name: string) => ({ ...entry(name), source: `def ${name}(x):\n    return x\n` })),
    removeTool: vi.fn(async () => undefined),
    settings: vi.fn(async () => settings()),
    setAskBeforeExec: vi.fn(async () => settings()),
    ...over,
  };
  return api as unknown as FakeApi;
}

async function start(w: World, over: Partial<Api> = {}) {
  const api = fakeApi(w, over);
  const { stores, services } = await createLiveServices(api, FakeES);
  const wb = new Workbench(stores, services);
  await wb.boot();
  await flush();
  return { api, stores, services, wb };
}
const flush = () => vi.advanceTimersByTimeAsync(0);
const cur = (s: Stores) => s.session.get().sessions.find((x) => x.id === s.session.get().curId)!;
const streamOf = (runId: string) => FakeES.all.filter((e) => e.url.startsWith(`/api/runs/${runId}/events`)).at(-1);

beforeEach(() => {
  FakeES.all = [];
  seq = 0;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(NOW));
  window.location.hash = "";
  setReducedMotion(false);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("boot with no sessions creates (or reuses) one and shows an idle bench", async () => {
  const { api, stores, services } = await start({ sessions: [], runs: {}, events: {}, tools: ["caesar_cipher"] });
  expect(api.createSession).toHaveBeenCalledTimes(1);
  expect(services).toMatchObject({ mode: "live", demo: null });
  expect(cur(stores)).toMatchObject({ id: "s-new", name: "Session 1", live: true, runIds: [], messages: [] });
  expect(stores.session.get().sessions).toHaveLength(1);
  expect(stores.ui.get()).toMatchObject({ busy: false, viewingRunId: null, currentRunId: null, selected: null });
  expect(stores.vault.get().tools.map((t) => t.name)).toEqual(["caesar_cipher"]);
});

test("boot with sessions opens the newest, shows its messages and replays its last run; the others are past", async () => {
  const a1 = summary("a1", 1, "done");
  const a2 = summary("a2", 2, "done");
  const b1 = summary("b1", 1, "done");
  const w: World = {
    sessions: [detail("A", "Caesar shift", [a1, a2]), detail("B", "Older", [b1])],
    runs: {},
    events: { a1: finishedEvents(a1), a2: finishedEvents(a2), b1: finishedEvents(b1) },
    tools: [],
  };
  const { api, stores } = await start(w);
  expect(api.createSession).not.toHaveBeenCalled();
  expect(cur(stores)).toMatchObject({ id: "A", name: "Caesar shift", live: true, runIds: ["a1", "a2"] });
  expect(cur(stores).messages.map((m) => m.kind)).toEqual(["you", "talos", "you", "talos"]);
  expect(stores.session.get().sessions.find((x) => x.id === "B")).toMatchObject({ live: false, runIds: ["b1"] });
  expect(api.runEvents).toHaveBeenCalledTimes(1);
  expect(api.runEvents).toHaveBeenCalledWith("a2");
  expect(stores.ui.get()).toMatchObject({ viewingRunId: "a2", busy: false, markedRunN: 2 });
  expect(stores.runs.get().byId.a2).toMatchObject({ status: "done", caption: "Replayed 2", summary: "Answered 2" });
  // A replay adds no messages.
  expect(cur(stores).messages).toHaveLength(4);
  expect(stores.runs.get().byId.a1!.caption).toBeUndefined();
});

test("boot with a running last run re-attaches: backlog at once, later events paced, Stop works", async () => {
  const a1 = summary("a1", 1, "running", "Write a thing");
  const w: World = {
    sessions: [detail("A", "Thing", [a1])],
    runs: { a1: { ...a1, pending: null } },
    events: {},
    tools: [],
  };
  const { api, stores, wb } = await start(w);
  expect(api.runEvents).not.toHaveBeenCalled();
  const es = streamOf("a1")!;
  expect(es.url).toBe("/api/runs/a1/events?after=0");
  expect(stores.ui.get()).toMatchObject({ busy: true, currentRunId: "a1", viewingRunId: "a1" });
  // The running run's stored messages are dropped; run.started re-adds You and Talos.
  expect(cur(stores).messages).toHaveLength(0);

  const lines = Array.from({ length: 63 }, (_, i) => `line ${i}`);
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Write a thing", n: 1 }));
  es.emit(ev("a1", "forge.code", { tool: "t", attempt: 1, file: "t.py", lines, changed: null, note: null, tests: 2 }));
  await flush();
  expect(stores.runs.get().byId.a1!.code!.shown).toBe(63);
  expect(cur(stores).messages.map((m) => m.kind)).toEqual(["you", "talos"]);
  expect(cur(stores).runIds).toEqual(["a1"]);

  vi.setSystemTime(new Date("2026-09-30T12:00:10.000Z"));
  es.emit(
    ev("a1", "forge.tests", { tool: "t", attempt: 1, results: [{ name: "a", passed: true, why: null }, { name: "b", passed: true, why: null }] }, "2026-09-30T12:00:10.000Z"),
  );
  await flush();
  expect(stores.runs.get().byId.a1!.tests!.list.map((t) => t.state)).toEqual(["running", "waiting"]);

  await wb.stop();
  expect(api.stop).toHaveBeenCalledWith("a1");
  expect(api.resume).not.toHaveBeenCalled();
});

test("boot with a waiting last run opens the dialog from GET /runs/{id}.pending once the backlog is quiet", async () => {
  const a1 = summary("a1", 1, "waiting", "Run some python");
  const pending = { kind: "confirm_exec" as const, payload: { tool: "python_exec" as const, preview: "print('pending')" } };
  const w: World = { sessions: [detail("A", "Python", [a1])], runs: { a1: { ...a1, status: "waiting", pending } }, events: {}, tools: [] };
  const { api, stores, wb } = await start(w);
  // The dialog's source is GET /runs/{id}, read once the backlog is quiet, not at attach time.
  expect(api.getRun).not.toHaveBeenCalled();
  const es = streamOf("a1")!;
  const old = { kind: "confirm_exec" as const, payload: { tool: "python_exec" as const, preview: "print('old')" } };
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  es.emit(ev("a1", "interrupt", old));
  es.emit(ev("a1", "interrupt.resolved", { kind: "confirm_exec", decision: "approve" }));
  es.emit(ev("a1", "interrupt", old));
  await flush();
  expect(stores.ui.get().dialog).toBeNull();
  expect(stores.runs.get().byId.a1!.status).toBe("waiting");
  await vi.advanceTimersByTimeAsync(149);
  expect(stores.ui.get().dialog).toBeNull();
  await vi.advanceTimersByTimeAsync(1);
  expect(stores.ui.get().dialog).toEqual({ kind: "approval", runId: "a1", tool: "python_exec", code: "print('pending')" });
  expect(api.getRun).toHaveBeenCalledWith("a1");

  // Esc (cancel) stops the run; it never resumes it.
  wb.answerApproval("cancel");
  await flush();
  expect(api.stop).toHaveBeenCalledWith("a1");
  expect(api.resume).not.toHaveBeenCalled();
});

test("a reattached waiting run's key dialog comes from pending, and Save resumes with the value", async () => {
  const a1 = summary("a1", 1, "waiting", "Weather");
  const pending = { kind: "missing_api_key" as const, payload: { env_var: "OWM_KEY", tool_name: "weather", service: "OpenWeatherMap" } };
  const w: World = { sessions: [detail("A", "Weather", [a1])], runs: { a1: { ...a1, status: "waiting", pending } }, events: {}, tools: [] };
  const { api, stores, wb } = await start(w);
  const es = streamOf("a1")!;
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Weather", n: 1 }));
  es.emit(ev("a1", "interrupt", pending));
  await vi.advanceTimersByTimeAsync(150);
  expect(stores.ui.get().dialog).toEqual({ kind: "key", runId: "a1", toolName: "weather", envVar: "OWM_KEY", service: "OpenWeatherMap" });
  wb.answerKey({ action: "save", value: "k-123" });
  await flush();
  expect(api.resume).toHaveBeenCalledWith("a1", { decision: "save", value: "k-123" });
});

test("send runs through LiveTransport with the moment dwells and reloads the vault after run.finished", async () => {
  const w: World = { sessions: [], runs: {}, events: {}, tools: ["caesar_cipher"] };
  const { api, stores, wb } = await start(w, {
    getSession: vi.fn(async () => ({ session: { id: "s-new", name: "Hello there", number: 1, created_at: NOW, updated_at: NOW }, messages: [], runs: [] })),
  });
  expect(api.vault).toHaveBeenCalledTimes(1);
  await wb.submit("hello");
  expect(api.send).toHaveBeenCalledWith("s-new", "hello");
  expect(cur(stores).name).toBe("Hello there");
  const es = streamOf("r-sent")!;
  const later = "2026-09-30T12:00:01.000Z";
  es.emit(ev("r-sent", "run.started", { session_id: "s-new", query: "hello", n: 1 }, later));
  es.emit(ev("r-sent", "node.started", { step: "planner", label: "planning" }, later));
  es.emit(ev("r-sent", "node.finished", { step: "planner", status: "done", label: "planned" }, later));
  await flush();
  // The planner's §6 minimum (900 ms) is the player's in live mode.
  expect(stores.runs.get().byId["r-sent"]!.nodes.planner?.state).toBe("active");
  await vi.advanceTimersByTimeAsync(900);
  expect(stores.runs.get().byId["r-sent"]!.nodes.planner?.state).toBe("done");

  w.tools = ["caesar_cipher", "fresh_tool"];
  es.emit(ev("r-sent", "run.finished", { status: "done", summary: "ok", summary_gold: false, forged: ["fresh_tool"], used: [] }, later));
  await vi.advanceTimersByTimeAsync(10);
  expect(api.vault).toHaveBeenCalledTimes(2);
  expect(stores.vault.get().tools.map((t) => t.name)).toEqual(["caesar_cipher", "fresh_tool"]);
  expect(stores.ui.get().busy).toBe(false);
  expect(es.closed).toBe(true);
});

test("a 409 run_active re-attaches when the active run is in this session, and does nothing otherwise", async () => {
  const w: World = { sessions: [], runs: { other: { ...summary("other", 3, "running"), pending: null } }, events: {}, tools: [] };
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  const send = vi.fn(async () => {
    throw new ApiError(409, "run_active", "busy", "other", "s-new");
  });
  const { stores, wb } = await start(w, { send });
  await wb.submit("hello");
  await flush();
  expect(streamOf("other")).toBeDefined();
  expect(stores.ui.get()).toMatchObject({ busy: true, currentRunId: "other" });

  const b = await start(w, { send: vi.fn(async () => Promise.reject(new ApiError(409, "run_active", "busy", "else", "other-session"))) });
  await b.wb.submit("hello");
  await flush();
  expect(streamOf("else")).toBeUndefined();
  expect(b.stores.ui.get().busy).toBe(false);

  const c = await start(w, { send: vi.fn(async () => Promise.reject(new ApiError(500, "http_500", "boom"))) });
  await c.wb.submit("hello");
  await flush();
  expect(c.stores.ui.get().busy).toBe(false);
  expect(err).toHaveBeenCalled();
});

test("viewRun, openSession and backToNow replay a stub run once, then show it", async () => {
  const a1 = summary("a1", 1, "done");
  const a2 = summary("a2", 2, "done");
  const b1 = summary("b1", 1, "done");
  const w: World = {
    sessions: [detail("A", "Now", [a1, a2]), detail("B", "Older", [b1])],
    runs: {},
    events: { a1: finishedEvents(a1), a2: finishedEvents(a2), b1: finishedEvents(b1) },
    tools: [],
  };
  const { api, stores, wb } = await start(w);
  await wb.viewRun(1);
  expect(api.runEvents).toHaveBeenLastCalledWith("a1");
  expect(stores.ui.get()).toMatchObject({ viewingRunId: "a1", markedRunN: 1 });
  expect(stores.runs.get().byId.a1!.caption).toBe("Replayed 1");

  await wb.openSession("B");
  expect(api.runEvents).toHaveBeenLastCalledWith("b1");
  expect(stores.session.get().viewId).toBe("B");
  expect(stores.ui.get().viewingRunId).toBe("b1");
  expect(stores.runs.get().byId.b1!.caption).toBe("Replayed 1");

  await wb.backToNow();
  expect(stores.ui.get().viewingRunId).toBe("a2");
  await wb.viewRun(1);
  // a1, a2 and b1, each once.
  expect(api.runEvents).toHaveBeenCalledTimes(3);
});

test("entering Vault, Sessions or Settings refreshes that store from the API first", async () => {
  const a1 = summary("a1", 1, "done");
  const w: World = { sessions: [detail("A", "Now", [a1])], runs: {}, events: { a1: finishedEvents(a1) }, tools: ["alpha", "beta"] };
  const { api, stores, wb } = await start(w);
  await wb.loadSource("beta");
  w.tools = ["alpha", "gamma"];
  await wb.showView("vault");
  expect(api.vault).toHaveBeenCalledTimes(2);
  expect(stores.vault.get().tools.map((t) => t.name)).toEqual(["alpha", "gamma"]);
  expect(stores.vault.get().sources.beta).toBeUndefined();
  expect(api.tool).toHaveBeenCalledWith("alpha");
  expect(stores.vault.get().sources.alpha).toEqual(["def alpha(x):", "    return x"]);
  expect(stores.ui.get()).toMatchObject({ view: "vault", badge: false });

  const c1 = summary("c1", 1, "done");
  w.sessions = [detail("C", "Other tab", [c1]), ...w.sessions];
  await wb.showView("sessions");
  expect(api.listSessions).toHaveBeenCalledTimes(2);
  const ss = stores.session.get();
  expect(ss.sessions.find((x) => x.id === "C")).toMatchObject({ live: false, runIds: ["c1"] });
  expect(ss.sessions.filter((x) => x.id === "A")).toHaveLength(1);
  expect(ss.curId).toBe("A");
  expect(stores.runs.get().byId.c1).toMatchObject({ n: 1, sessionId: "C" });
  expect(stores.ui.get().view).toBe("sessions");

  api.settings.mockImplementation(async () => settings("claude-sonnet"));
  await wb.showView("settings");
  expect(stores.settings.get().model).toBe("claude-sonnet");
  expect(stores.ui.get().view).toBe("settings");
});

test("New session: the server's reused empty session only re-decodes the title; a new one opens", async () => {
  const w: World = { sessions: [], runs: {}, events: {}, tools: [] };
  const { api, stores, wb } = await start(w);
  const seqBefore = stores.ui.get().titleSeq;
  const before = stores.session.get();
  await wb.newSession();
  expect(api.createSession).toHaveBeenCalledTimes(2);
  expect(stores.session.get().sessions).toEqual(before.sessions);
  expect(stores.session.get().curId).toBe("s-new");
  expect(stores.ui.get()).toMatchObject({ titleAnimate: true, titleSeq: seqBefore + 1 });

  api.createSession.mockImplementation(async () => ({ id: "s-2", name: "Session 2", number: 2, created_at: NOW, updated_at: NOW }));
  await wb.newSession();
  expect(stores.session.get().curId).toBe("s-2");
  expect(cur(stores)).toMatchObject({ name: "Session 2", live: true, runIds: [] });
});

test("Reset is demo-only", async () => {
  const { api, wb } = await start({ sessions: [], runs: {}, events: {}, tools: [] });
  await wb.reset();
  expect(api.vault).toHaveBeenCalledTimes(1);
  expect(api.createSession).toHaveBeenCalledTimes(1);
});

/* Fix round 1: the re-attach dialog fallback, the navigation race and the smaller review findings. */

const confirmOld = { kind: "confirm_exec" as const, payload: { tool: "python_exec" as const, preview: "print('old')" } };
const confirmNow = { kind: "confirm_exec" as const, payload: { tool: "python_exec" as const, preview: "print('now')" } };
const waitingWorld = (stubStatus: ApiRunSummary["status"]): World => {
  const a1 = summary("a1", 1, stubStatus, "Run some python");
  return { sessions: [detail("A", "Python", [a1])], runs: { a1: { ...a1, status: "waiting", pending: confirmNow } }, events: {}, tools: [] };
};

test("a pause of 150 ms or more in a waiting run's backlog still ends with the pending dialog", async () => {
  const { stores } = await start(waitingWorld("waiting"));
  const es = streamOf("a1")!;
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  es.emit(ev("a1", "interrupt", confirmOld));
  es.emit(ev("a1", "interrupt.resolved", { kind: "confirm_exec", decision: "approve" }));
  await vi.advanceTimersByTimeAsync(400); // e.g. a slow source fetch or a reconnect
  expect(stores.ui.get().dialog).toBeNull();
  es.emit(ev("a1", "interrupt", confirmOld));
  await vi.advanceTimersByTimeAsync(150);
  expect(stores.ui.get().dialog).toEqual({ kind: "approval", runId: "a1", tool: "python_exec", code: "print('now')" });
});

test("a run reported running whose interrupt is caught up still gets its dialog from pending", async () => {
  // GET /runs/{id} said running when the page loaded; the run paused before the reattach cutoff.
  const w = waitingWorld("running");
  let paused = false;
  const getRun = vi.fn(async () => (paused ? w.runs.a1! : { ...w.runs.a1!, status: "running" as const, pending: null }));
  const { api, stores } = await start(w, { getRun });
  const es = streamOf("a1")!;
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  paused = true;
  es.emit(ev("a1", "interrupt", confirmOld)); // stamped before the cutoff
  await flush();
  expect(stores.ui.get().dialog).toBeNull();
  await vi.advanceTimersByTimeAsync(150);
  expect(api.getRun).toHaveBeenCalledWith("a1");
  expect(stores.ui.get().dialog).toMatchObject({ kind: "approval", code: "print('now')" });
});

test("a live interrupt after re-attach opens its dialog once; an answered one never reopens", async () => {
  const { api, stores, wb } = await start(waitingWorld("running"));
  const es = streamOf("a1")!;
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  await vi.advanceTimersByTimeAsync(200);
  const later = "2026-09-30T12:00:05.000Z";
  vi.setSystemTime(new Date(later));
  es.emit(ev("a1", "interrupt", confirmOld, later));
  await vi.advanceTimersByTimeAsync(400); // the player's own dialog, after its 350 ms moment
  expect(stores.ui.get().dialog).toMatchObject({ kind: "approval", code: "print('old')" });
  wb.answerApproval("yes");
  await vi.advanceTimersByTimeAsync(1000); // /resume is in flight: the run is still waiting
  expect(stores.ui.get().dialog).toBeNull();
  expect(api.resume).toHaveBeenCalledTimes(1);
  es.emit(ev("a1", "interrupt.resolved", { kind: "confirm_exec", decision: "approve" }, later));
  await vi.advanceTimersByTimeAsync(1000);
  expect(stores.ui.get().dialog).toBeNull();
});

test("a dialog opened from pending and answered is not reopened, before or after interrupt.resolved", async () => {
  const { api, stores, wb } = await start(waitingWorld("waiting"));
  const es = streamOf("a1")!;
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  es.emit(ev("a1", "interrupt", confirmOld));
  await vi.advanceTimersByTimeAsync(150);
  expect(stores.ui.get().dialog).not.toBeNull();
  wb.answerApproval("yes");
  await vi.advanceTimersByTimeAsync(1000);
  expect(stores.ui.get().dialog).toBeNull();
  es.emit(ev("a1", "interrupt.resolved", { kind: "confirm_exec", decision: "approve" }, NOW));
  await vi.advanceTimersByTimeAsync(1000);
  expect(stores.ui.get().dialog).toBeNull();
  expect(api.resume).toHaveBeenCalledTimes(1);
});

test("Stop before the backlog has gone quiet opens no dialog", async () => {
  const { api, stores, wb } = await start(waitingWorld("waiting"));
  const es = streamOf("a1")!;
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  es.emit(ev("a1", "interrupt", confirmOld));
  await vi.advanceTimersByTimeAsync(100);
  await wb.stop();
  await vi.advanceTimersByTimeAsync(500);
  expect(api.stop).toHaveBeenCalledWith("a1");
  expect(stores.ui.get().dialog).toBeNull();
});

test("a failing GET /runs/{id} doesn't stop the re-attach: the stream opens and run.started restores the messages", async () => {
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  const { stores } = await start(waitingWorld("running"), { getRun: vi.fn(async () => Promise.reject(new Error("down"))) });
  const es = streamOf("a1")!;
  expect(es).toBeDefined();
  es.emit(ev("a1", "run.started", { session_id: "A", query: "Run some python", n: 1 }));
  await vi.advanceTimersByTimeAsync(200);
  expect(cur(stores).messages.map((m) => m.kind)).toEqual(["you", "talos"]);
  expect(stores.ui.get().busy).toBe(true);
  err.mockRestore();
});

test("the last bench navigation wins over a slower replay", async () => {
  const a1 = summary("a1", 1, "done");
  const a2 = summary("a2", 2, "done");
  const b1 = summary("b1", 1, "done");
  const w: World = {
    sessions: [detail("A", "Now", [a1, a2]), detail("B", "Older", [b1])],
    runs: {},
    events: { a1: finishedEvents(a1), a2: finishedEvents(a2), b1: finishedEvents(b1) },
    tools: [],
  };
  const { api, stores, wb } = await start(w);
  await wb.openSession("B");
  await wb.backToNow();
  let release: () => void = () => {};
  api.runEvents.mockImplementationOnce(() => new Promise<RunEvent[]>((res) => (release = () => res(w.events.a1!))));
  const slow = wb.viewRun(1);
  await wb.openSession("B");
  expect(stores.ui.get().viewingRunId).toBe("b1");
  release();
  await slow;
  await flush();
  expect(stores.session.get().viewId).toBe("B");
  expect(stores.ui.get().viewingRunId).toBe("b1");
});

test("a stub listed as running that has finished since is replayed when viewed", async () => {
  const a1 = summary("a1", 1, "done");
  const c1 = summary("c1", 1, "running");
  const w: World = { sessions: [detail("A", "Now", [a1])], runs: {}, events: { a1: finishedEvents(a1) }, tools: [] };
  const { api, stores, wb } = await start(w);
  w.sessions = [detail("C", "Other tab", [c1]), ...w.sessions];
  await wb.showView("sessions");
  w.runs.c1 = { ...c1, status: "done", pending: null };
  w.events.c1 = finishedEvents(c1);
  await wb.openSession("C");
  expect(api.getRun).toHaveBeenCalledWith("c1");
  expect(api.runEvents).toHaveBeenLastCalledWith("c1");
  expect(stores.runs.get().byId.c1).toMatchObject({ status: "done", caption: "Replayed 1" });
});

test("New session logs an API error instead of rejecting", async () => {
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  const { api, stores, wb } = await start({ sessions: [], runs: {}, events: {}, tools: [] });
  api.createSession.mockImplementation(async () => Promise.reject(new ApiError(500, "http_500", "boom")));
  await expect(wb.newSession()).resolves.toBeUndefined();
  expect(err).toHaveBeenCalled();
  expect(stores.session.get().curId).toBe("s-new");
});

test("the App with real live services hides the Demo controls (spec 04 §8.1)", async () => {
  vi.useRealTimers();
  const { stores, services } = await createLiveServices(fakeApi({ sessions: [], runs: {}, events: {}, tools: [] }), FakeES);
  const r = render(createElement(App, { stores, workbench: new Workbench(stores, services) }));
  await act(async () => {});
  expect(document.querySelector("#demo-toggle")).toBeNull();
  expect(document.querySelector("#demo-pop")).toBeNull();
  r.unmount();
});

/* Final wave C1: stage 2's run numbers are per session, so a run's Talos message is found by session and n. */

const talosHtml = (s: Stores, id: string) =>
  s.session.get().sessions.find((x) => x.id === id)!.messages.flatMap((m) => (m.kind === "talos" ? [m.html] : []));

test("replaying another session's run with the same n leaves this session's answer alone", async () => {
  const a1 = summary("a1", 1, "done");
  const b1 = summary("b1", 1, "done");
  const bEvents = finishedEvents(b1).map((e) =>
    e.type === "answer.done" ? ({ ...e, data: { html: "ANSWER FROM B", note: "b note", chips: [{ kind: "reused", text: "b chip" }] } } as RunEvent) : e,
  );
  const w: World = {
    sessions: [detail("A", "Now", [a1]), detail("B", "Older", [b1])],
    runs: {},
    events: { a1: finishedEvents(a1), b1: bEvents },
    tools: [],
  };
  const { stores, wb } = await start(w);
  expect(talosHtml(stores, "A")).toEqual(["Answer 1"]);
  await wb.openSession("B");
  expect(talosHtml(stores, "A")).toEqual(["Answer 1"]);
  expect(talosHtml(stores, "B")).toEqual(["Answer 1"]);
  await wb.backToNow();
  const a = stores.session.get().sessions.find((x) => x.id === "A")!.messages.find((m) => m.kind === "talos");
  expect(a).toMatchObject({ html: "Answer 1", note: null, chips: [] });
});

test("a live run in a new session doesn't rewrite a past session's run with the same n", async () => {
  const a1 = summary("a1", 1, "done");
  const w: World = { sessions: [detail("A", "Past", [a1])], runs: {}, events: { a1: finishedEvents(a1) }, tools: [] };
  const { stores, wb } = await start(w);
  w.sessions.push(detail("s-new", "Hello", []));
  await wb.newSession();
  expect(stores.session.get().curId).toBe("s-new");
  await wb.submit("hello");
  const es = streamOf("r-sent")!;
  const later = "2026-09-30T12:00:01.000Z";
  es.emit(ev("r-sent", "run.started", { session_id: "s-new", query: "hello", n: 1 }, later));
  es.emit(ev("r-sent", "talos.status", { text: "Thinking hard" }, later));
  es.emit(ev("r-sent", "answer.done", { html: "NEW SESSION ANSWER", note: null, chips: [] }, later));
  await vi.advanceTimersByTimeAsync(5000);
  expect(talosHtml(stores, "A")).toEqual(["Answer 1"]);
  expect(talosHtml(stores, "s-new")).toEqual(["NEW SESSION ANSWER"]);
  await wb.stop();
  es.emit(ev("r-sent", "run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] }, later));
  await vi.advanceTimersByTimeAsync(100);
  const past = stores.session.get().sessions.find((x) => x.id === "A")!.messages.find((m) => m.kind === "talos");
  expect(past).toMatchObject({ html: "Answer 1", stopNote: null, status: null });
});
