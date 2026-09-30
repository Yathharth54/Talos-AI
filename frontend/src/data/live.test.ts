import { expect, test, vi } from "vitest";
import type { Api } from "../transport/api";
import { ApiError } from "../transport/api";
import type { ApiMessage, ApiRunSummary, ApiSessionDetail, ApiVaultEntry, RunEvent } from "../transport/types";
import type { DataSource } from "./source";
import { LiveDataSource, sourceLines, stubRun, toMessages, toSettings } from "./live";

function fakeApi(over: Partial<Api> = {}): Api {
  const fail = () => Promise.reject(new Error("not stubbed"));
  return {
    listSessions: fail, createSession: fail, getSession: fail, send: fail, getRun: fail, runEvents: fail, resume: fail, stop: fail,
    vault: fail, tool: fail, removeTool: fail, settings: fail, setAskBeforeExec: fail, ...over,
  };
}

const entry = (name: string, created_at: string | null): ApiVaultEntry => ({
  name, args: "text: str", ret: "str", signature: `${name}(text: str) -> str`, description: "d", keywords: ["k"], uses: 1, failures: 0,
  streak: 0, created_at, last_used: null, last_failure: null, last_failed_at: null, web: false, file: `tools/${name}.py`,
});

const run = (n: number, over: Partial<ApiRunSummary> = {}): ApiRunSummary => ({
  id: `run-${n}`, n, query: `q${n}`, status: "done", summary: `s${n}`, summary_gold: false, forged: [], used: [], failed: false,
  started_at: "2026-09-30T10:00:00Z", finished_at: "2026-09-30T10:01:00Z", ...over,
});

const msg = (id: string, role: ApiMessage["role"], runId: string | null, over: Partial<ApiMessage> = {}): ApiMessage => ({
  id, role, html: "", note: null, chips: [], run_id: runId, created_at: "2026-09-30T10:00:00Z", ...over,
});

test("sourceLines drops one trailing newline", () => {
  expect(sourceLines("a\nb\n")).toEqual(["a", "b"]);
  expect(sourceLines("a\nb")).toEqual(["a", "b"]);
  expect(sourceLines("a\n\n")).toEqual(["a", ""]);
});

test("toSettings never carries a key value and keeps the facts", () => {
  const s = toSettings({
    model: "deepseek/deepseek-v4.1-flash", ask_before_exec: true, forge_retries: 3, test_timeout_s: 10, llm_timeout_s: 120, prune_after: 2,
    keys: [
      { name: "OPENROUTER_API_KEY", set: true, required: true, description: "Required. Every model call goes through OpenRouter." },
      { name: "TAVILY_API_KEY", set: false, required: false, description: "Optional." },
    ],
  });
  expect(s).toEqual({
    askExec: true, env: { OPENROUTER_API_KEY: "set" }, model: "deepseek/deepseek-v4.1-flash",
    live: {
      keys: [expect.objectContaining({ name: "OPENROUTER_API_KEY", set: true }), expect.objectContaining({ name: "TAVILY_API_KEY", set: false })],
      forgeRetries: 3, testTimeoutS: 10, llmTimeoutS: 120, pruneAfter: 2,
    },
  });
});

test("vault() maps entries, null created_at → '', and marks fresh by the current session's start", async () => {
  const ds = new LiveDataSource(
    fakeApi({
      vault: async () => ({
        count: 4, web_count: 0, failed_count: 0,
        tools: [entry("old", "2026-09-30T09:00:00Z"), entry("same", "2026-09-30T10:00:00Z"), entry("new", "2026-09-30T11:00:00+00:00"), entry("none", null)],
      }),
    }),
  );
  ds.setCurrentStarted("2026-09-30T10:00:00Z");
  const tools = await ds.vault();
  expect(tools.map((t) => [t.name, t.fresh])).toEqual([["old", false], ["same", true], ["new", true], ["none", false]]);
  expect(tools[3]!.created).toBe("");
  expect(tools[0]).toMatchObject({ desc: "d", kw: ["k"], uses: 1, fails: 0, created: "2026-09-30T09:00:00Z" });
});

test("vault() marks nothing fresh before a current session is known", async () => {
  const ds = new LiveDataSource(fakeApi({ vault: async () => ({ count: 1, web_count: 0, failed_count: 0, tools: [entry("a", "2026-09-30T09:00:00Z")] }) }));
  expect((await ds.vault())[0]!.fresh).toBe(false);
});

test("toolSource splits the source, null source → null, 404 → null", async () => {
  const tool = vi.fn(async (name: string) => {
    if (name === "gone") throw new ApiError(404, "not_found", "gone");
    return { ...entry(name, null), source: name === "a" ? "def a():\n    pass\n" : null, lines: 2 };
  });
  const ds = new LiveDataSource(fakeApi({ tool }));
  expect(await ds.toolSource("a")).toEqual(["def a():", "    pass"]);
  expect(await ds.toolSource("b")).toBeNull();
  expect(await ds.toolSource("gone")).toBeNull();
});

test("toolSource rethrows errors other than 404", async () => {
  const ds = new LiveDataSource(fakeApi({ tool: async () => { throw new ApiError(500, "http_500", "boom"); } }));
  await expect(ds.toolSource("a")).rejects.toThrow("boom");
});

test("settings, setAskBeforeExec and removeTool go through the API", async () => {
  const setAskBeforeExec = vi.fn(async () => ({}) as never);
  const removeTool = vi.fn(async () => {});
  const ds = new LiveDataSource(
    fakeApi({
      settings: async () => ({ model: "m", ask_before_exec: false, forge_retries: 3, test_timeout_s: 10, llm_timeout_s: 120, prune_after: 2, keys: [] }),
      setAskBeforeExec, removeTool,
    }),
  );
  expect(await ds.settings()).toMatchObject({ askExec: false, env: {}, model: "m" });
  await ds.setAskBeforeExec(true);
  expect(setAskBeforeExec).toHaveBeenCalledWith(true);
  await ds.removeTool("x");
  expect(removeTool).toHaveBeenCalledWith("x");
});

test("sessions() is empty in live mode (boot uses loadSessions)", async () => {
  expect(await new LiveDataSource(fakeApi()).sessions()).toEqual({ sessions: [], runs: [], lastRunNumber: 0 });
});

test("newSession creates a session on the server, ignores count, and sets the current start", async () => {
  const createSession = vi.fn(async () => ({ id: "s9", name: "Session 9", number: 9, created_at: "2026-09-30T12:00:00Z", updated_at: "" }));
  const ds = new LiveDataSource(
    fakeApi({ createSession, vault: async () => ({ count: 1, web_count: 0, failed_count: 0, tools: [entry("a", "2026-09-30T12:00:00Z")] }) }),
  );
  expect(await (ds as DataSource).newSession(3)).toEqual({ id: "s9", name: "Session 9", started: "2026-09-30T12:00:00Z" });
  expect((await ds.vault())[0]!.fresh).toBe(true);
});

test("stubRun maps a run summary to a chat-strip stub", () => {
  const r = stubRun("s1", run(4, { status: "failed", summary: "Failed", summary_gold: true, forged: ["caesar"], used: ["other"], failed: true }));
  expect(r).toMatchObject({
    id: "run-4", sessionId: "s1", n: 4, query: "q4", status: "failed", summary: "Failed", summaryGold: true, forged: true,
    toolUsed: "caesar", failed: true, strip: "chat", nodes: {},
  });
  const u = stubRun("s1", run(5, { summary: null, used: ["rev"] }));
  expect(u).toMatchObject({ summary: "", summaryGold: false, forged: false, toolUsed: "rev", failed: false });
  expect(stubRun("s1", run(6)).toolUsed).toBeUndefined();
});

test("toMessages maps you and Talos messages and drops the active run's", () => {
  const detail: ApiSessionDetail = {
    session: { id: "s1", name: "S", number: 1, created_at: "2026-09-30T10:00:00Z", updated_at: "" },
    runs: [run(1), run(2, { status: "stopped" }), run(3, { status: "waiting" })],
    messages: [
      msg("m1", "user", "run-1", { html: "a &lt;b&gt; &amp; c" }),
      msg("m2", "assistant", "run-1", {
        html: 'Done <span class="gold">x</span><img src=x>', note: "<b>n</b>", chips: [{ kind: "forged", text: "Forged x" }],
      }),
      msg("m3", "user", "run-2", { html: "stop me" }),
      msg("m4", "assistant", "run-2", { html: "", note: "Stopped. Ask again whenever you're ready." }),
      msg("m5", "user", "run-3", { html: "waiting" }),
    ],
  };
  expect(toMessages(detail)).toEqual([
    { kind: "you", key: "you-m1", text: "a <b> & c", past: false },
    {
      kind: "talos", key: "talos-m2", runN: 1, status: null, html: 'Done <span class="gold">x</span>', wrap: false, wordsOn: 0, note: "n",
      chips: [{ kind: "forged", text: "Forged x" }], suggest: false, stopNote: null, runLink: true, past: false,
    },
    { kind: "you", key: "you-m3", text: "stop me", past: false },
    {
      kind: "talos", key: "talos-m4", runN: 2, status: null, html: null, wrap: false, wordsOn: 0, note: null, chips: [], suggest: false,
      stopNote: "Stopped. Ask again whenever you're ready.", runLink: true, past: false,
    },
  ]);
});

test("loadSessions reads each session, stubs its runs sorted by n, and finds the active run", async () => {
  const details: Record<string, ApiSessionDetail> = {
    s1: {
      session: { id: "s1", name: "One", number: 1, created_at: "2026-09-30T09:00:00Z", updated_at: "" },
      runs: [run(2), run(1)],
      messages: [msg("m1", "user", "run-1", { html: "q1" })],
    },
    s2: {
      session: { id: "s2", name: "Two", number: 2, created_at: "2026-09-30T10:00:00Z", updated_at: "" },
      runs: [run(3), run(4, { status: "running" })],
      messages: [msg("m2", "user", "run-4", { html: "q4" })],
    },
  };
  const ds = new LiveDataSource(fakeApi({ getSession: async (id) => details[id]! }));
  const summary = (id: string) => ({ id, name: id, created_at: "", run_count: 0, forged: [], used: [], runs: [] });
  const [a, b] = await ds.loadSessions([summary("s1"), summary("s2")]);
  expect(a!.rec).toEqual({
    id: "s1", name: "One", started: "2026-09-30T09:00:00Z", live: false, runIds: ["run-1", "run-2"],
    messages: [{ kind: "you", key: "you-m1", text: "q1", past: false }],
  });
  expect(a!.runs.map((r) => r.n)).toEqual([1, 2]);
  expect(a!.active).toBeNull();
  expect(b!.active).toMatchObject({ id: "run-4", status: "running" });
  expect(b!.rec.messages).toEqual([]);
  expect(b!.rec.runIds).toEqual(["run-3", "run-4"]);
});

test("runEvents normalises the backlog; getRun passes through", async () => {
  const backlog = [{ run_id: "r", seq: 1, ts: "", type: "caption", data: { html: "<i>x</i>" } }] as RunEvent[];
  const getRun = vi.fn(async () => ({ ...run(1), pending: null }));
  const ds = new LiveDataSource(fakeApi({ runEvents: async () => backlog, getRun }));
  expect((await ds.runEvents("r"))[0]!.data).toEqual({ html: "x" });
  expect(await ds.getRun("run-1")).toMatchObject({ id: "run-1", pending: null });
});
