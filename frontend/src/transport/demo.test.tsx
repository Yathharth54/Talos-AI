import { SOURCES, VAULT_ROWS } from "../demo/data";
import { Panel, earlierData } from "../components/workbench/panels/Panel";
import { Banner } from "../components/workbench/Banner";
import { Strip } from "../components/workbench/Strip";
import { Tabs } from "../components/workbench/Tabs";
import { createStores, type Stores } from "../store/stores";
import type { VaultTool } from "../store/types";
import { freshVault } from "../store/vaultOps";
import { expectParity, FIXED_NOW, snap } from "../test/parity";
import { innerOf, ssr } from "../test/ssr";
import { DemoTransport, type DemoWorld } from "./demo";
import { Player } from "./player";
import type { ResumeDecision, RunEvent } from "./types";

const Q = {
  forge: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.',
  reuse: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  wordShift: 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"',
  python: "Run this Python code and give me the output: print(sum(range(1, 101)))",
  weather: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};

function setup() {
  const stores = createStores({ tools: freshVault(VAULT_ROWS), settings: { askExec: true, env: {}, model: "m" }, sessions: [], runs: [], current: { id: "s1", name: "Session 1", started: "2026-09-30T12:00" }, count: 1 });
  const world: DemoWorld = {
    tools: () => stores.vault.get().tools,
    hasKey: (env) => !!stores.settings.get().env[env],
    saveKey: (env, value) => stores.settings.update((s) => ({ ...s, env: { ...s.env, [env]: value } })),
    askExec: () => stores.settings.get().askExec,
    speed: () => stores.ui.get().speed,
    sessionRunCount: (sid) => stores.session.get().sessions.find((s) => s.id === sid)?.runIds.length ?? 0,
  };
  const transport = new DemoTransport(world, { lastRunNumber: 5 });
  return { stores, transport };
}

/** Runs one query through DemoTransport and the Player; answers dialogs with `answer`. */
async function ask(stores: Stores, transport: DemoTransport, q: string, answer?: ResumeDecision) {
  const started = await transport.startRun("s1", q);
  const player = new Player(stores, { runId: started.runId, sessionId: "s1", momentDwell: false, source: async (n) => SOURCES[n] ?? null });
  transport.subscribe(started.runId, player.push);
  for (let i = 0; i < 5000; i++) {
    await vi.advanceTimersToNextTimerAsync();
    const d = stores.ui.get().dialog;
    if (d && "runId" in d && answer) {
      stores.ui.set({ dialog: null });
      await transport.resume(d.runId, answer);
    }
    if (!stores.ui.get().busy && stores.runs.get().byId[started.runId]?.summary !== undefined) break;
  }
  return started.runId;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
});
afterEach(() => vi.useRealTimers());

function expectRunMatches(stores: Stores, runId: string, flowName: string, snapName: string) {
  const s = snap(flowName, snapName);
  const run = stores.runs.get().byId[runId]!;
  const tools = stores.vault.get().tools as VaultTool[];
  const runs = stores.session.get().sessions[0]!.runIds.map((id) => stores.runs.get().byId[id]!);
  expectParity(innerOf(ssr(<Strip run={run} />)), s.pure!.strip);
  expectParity(ssr(<Banner banner={run.banner} />), s.pure!.banner);
  expectParity(ssr(<Tabs run={run} onSelect={() => {}} />), s.pure!.tabs);
  expectParity(
    ssr(<Panel run={run} isCurrent tool={tools.find((t) => t.name === run.toolName)} earlier={earlierData(runs, run, false)} onAsk={() => {}} onOpenTool={() => {}} onRun={() => {}} />),
    s.pure!.panel,
  );
}

test("the Caesar forge run ends exactly as the reference's", async () => {
  const { stores, transport } = setup();
  const id = await ask(stores, transport, Q.forge);
  expectRunMatches(stores, id, "caesar-forge", "end");
  expect(stores.session.get().sessions[0]!.name).toBe("Session 1"); // renaming is the controller's job (Task 15)
});

test("the Caesar reuse run ends as the reference's", async () => {
  const { stores, transport } = setup();
  await ask(stores, transport, Q.forge);
  const reuse = await ask(stores, transport, Q.reuse);
  expectRunMatches(stores, reuse, "caesar-reuse", "end");
});

test("python approve ends as the reference's", async () => {
  const { stores, transport } = setup();
  const id = await ask(stores, transport, Q.python, { decision: "approve" });
  expectRunMatches(stores, id, "python-approve", "end");
});

test("stop during a pause finishes the run as stopped", async () => {
  const { stores, transport } = setup();
  const started = await transport.startRun("s1", Q.python);
  const player = new Player(stores, { runId: started.runId, sessionId: "s1", momentDwell: false });
  transport.subscribe(started.runId, player.push);
  while (!stores.ui.get().dialog) await vi.advanceTimersToNextTimerAsync();
  player.abort();
  stores.ui.set({ dialog: null });
  await transport.stop(started.runId);
  await vi.advanceTimersByTimeAsync(0);
  const run = stores.runs.get().byId[started.runId]!;
  expect(run.status).toBe("stopped");
  expect(run.nodes.executor).toMatchObject({ state: "stopped", label: "Executor, stopped" });
  expect(run.caption).toBe("You stopped this run. Nothing was saved to the vault.");
  expect(transport.events(started.runId).at(-1)!.type).toBe("run.finished");
});

test("sessionName comes back on a session's first run only", async () => {
  const { transport } = setup();
  expect((await transport.startRun("s1", Q.weather)).sessionName).toBe("Weather in Mumbai");
});

/** Golden event logs for the five fake-graph flows (ruling 14). `npx vitest -u` rewrites them. */
test.each([
  ["caesar-forge", [Q.forge], undefined],
  ["caesar-reuse", [Q.forge, Q.reuse], undefined],
  ["caesar-word-shift", [Q.forge, Q.wordShift], undefined],
  ["python-approve", [Q.python], { decision: "approve" } as ResumeDecision],
  ["weather-key-save", [Q.weather], { decision: "save", value: "k" } as ResumeDecision],
] as const)("golden: %s", async (name, queries, answer) => {
  const { stores, transport } = setup();
  let last = "";
  for (const q of queries) last = await ask(stores, transport, q, answer);
  const events = transport.events(last).map((e: RunEvent) => ({ seq: e.seq, type: e.type, data: e.data }));
  expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1));
  expect(events[0]!.type).toBe("run.started");
  expect(events.at(-1)!.type).toBe("run.finished");
  await expect(JSON.stringify(events, null, 1) + "\n").toMatchFileSnapshot(`./__golden__/${name}.json`);
});

test("reset cancels runs silently and restarts the counter", async () => {
  const { transport } = setup();
  const started = await transport.startRun("s1", Q.forge);
  const seen: string[] = [];
  transport.subscribe(started.runId, async (e) => void seen.push(e.type));
  await vi.advanceTimersByTimeAsync(100);
  transport.reset(5);
  const count = seen.length;
  await vi.advanceTimersByTimeAsync(10000);
  expect(seen.length).toBe(count);
  expect((await transport.startRun("s1", Q.forge)).n).toBe(6);
});

test("call.error sends stage 2's codes, which the player turns into the reference's text", async () => {
  const { stores, transport } = setup();
  await ask(stores, transport, Q.forge);
  const fail = await ask(stores, transport, Q.wordShift);
  expect(transport.events(fail).find((e) => e.type === "call.error")!.data).toMatchObject({ when: "run" });
  expect(stores.runs.get().byId[fail]!.call!.when).toBe("30 Sep 2026, 12:00");
  const declined = await ask(stores, transport, Q.python, { decision: "decline" });
  expect(transport.events(declined).find((e) => e.type === "call.error")!.data).toMatchObject({ when: "declined" });
  expect(stores.runs.get().byId[declined]!.call!.when).toBe("You chose Don't run");
});

test("the weather reuse's Code tab says the reference's literal 34 lines (ruling 10)", async () => {
  const { stores, transport } = setup();
  await ask(stores, transport, Q.weather, { decision: "save", value: "k" });
  const reuse = await ask(stores, transport, Q.weather);
  expect(SOURCES.get_current_temperature!.length).not.toBe(34);
  expect(stores.runs.get().byId[reuse]!.code!.cap).toBe("34 lines");
});
