import { clearTestMarks } from "../components/workbench/panels/TestsPanel";
import { createServices } from "../services";
import { updateRun } from "../store/stores";
import type { LogLn } from "../store/types";
import { setReducedMotion } from "../test/media";
import { FIXED_NOW } from "../test/parity";
import { Workbench } from "./workbench";

vi.mock("../components/workbench/panels/TestsPanel", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../components/workbench/panels/TestsPanel")>()),
  clearTestMarks: vi.fn(),
}));

async function boot() {
  const { stores, services } = await createServices("demo");
  return { stores, services, wb: new Workbench(stores, services) };
}
async function settle(stores: Awaited<ReturnType<typeof boot>>["stores"]) {
  for (let i = 0; i < 5000 && stores.ui.get().busy; i++) await vi.advanceTimersToNextTimerAsync();
}

const CAESAR = 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
  window.location.hash = "";
});
afterEach(() => vi.useRealTimers());

test("boot state is the reference's", async () => {
  const { stores } = await boot();
  const s = stores.session.get();
  expect(s.sessions.map((x) => x.id)).toEqual(["seed-fib", "seed-lev", "seed-b64", s.curId]);
  expect(s.sessions.at(-1)!.name).toBe("Session 1");
  expect(stores.vault.get().tools).toHaveLength(40);
  expect(stores.ui.get()).toMatchObject({ view: "workbench", busy: false, selected: "caesar_cipher", speed: 1 });
});

test("submit guards: whitespace, busy, reading an old session", async () => {
  const { stores, wb } = await boot();
  await wb.submit("   ");
  expect(stores.ui.get().busy).toBe(false);
  await wb.submit("What can you do?");
  await wb.submit("What can you do?"); // while busy
  await settle(stores);
  expect(Object.values(stores.runs.get().byId).filter((r) => !r.seeded)).toHaveLength(1);
  expect(stores.session.get().sessions.at(-1)!.name).toBe("Getting to know Talos");
  wb.openSession("seed-fib");
  await wb.submit("What can you do?");
  expect(Object.values(stores.runs.get().byId).filter((r) => !r.seeded)).toHaveLength(1);
});

test("reset drops the old run's late events", async () => {
  const { stores, wb } = await boot();
  await wb.submit(CAESAR);
  await vi.advanceTimersByTimeAsync(500);
  await wb.reset();
  await vi.advanceTimersByTimeAsync(60000);
  const s = stores.session.get();
  expect(s.sessions.map((x) => x.name)).toEqual(["Fibonacci tools", "Edit distance", "Base64 round trip", "Session 1"]);
  expect(s.sessions.at(-1)!.messages).toEqual([]);
  expect(stores.ui.get()).toMatchObject({ busy: false, viewingRunId: null, currentRunId: null, badge: false });
  expect(stores.vault.get().tools.some((t) => t.name === "caesar_cipher")).toBe(false);
  await wb.submit("What can you do?");
  await settle(stores);
  expect(Object.values(stores.runs.get().byId).find((r) => !r.seeded)!.n).toBe(6);
});

test("new session drops an empty current session; old sessions open read-only", async () => {
  const { stores, wb } = await boot();
  await wb.newSession();
  expect(stores.session.get().sessions.map((x) => x.name)).toEqual(["Fibonacci tools", "Edit distance", "Base64 round trip", "Session 2"]);
  wb.openSession("seed-lev");
  expect(stores.session.get().viewId).toBe("seed-lev");
  expect(stores.runs.get().byId[stores.ui.get().viewingRunId!]!.n).toBe(4);
  wb.backToNow();
  expect(stores.session.get().viewId).toBeNull();
  expect(stores.ui.get().viewingRunId).toBeNull();
});

test("vault actions: filter staggers, remove asks first, use prefills", async () => {
  const { stores, wb } = await boot();
  wb.showView("vault");
  expect(stores.ui.get()).toMatchObject({ view: "vault", stagger: true, badge: false });
  wb.setQuery("hex");
  expect(stores.ui.get().stagger).toBe(false);
  wb.setFilter("web");
  expect(stores.ui.get().stagger).toBe(true);
  wb.removeTool("hex_to_rgb");
  expect(stores.ui.get().confirmRemove).toBe("hex_to_rgb");
  wb.removeTool("hex_to_rgb");
  expect(stores.vault.get().tools.some((t) => t.name === "hex_to_rgb")).toBe(false);
  expect(stores.ui.get()).toMatchObject({ confirmRemove: null, selected: null });
  wb.useTool("slugify");
  expect(stores.ui.get().draft).toBe("Use slugify on ");
  wb.useTool("caesar_cipher");
  expect(stores.ui.get().draft).toBe('Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"');
});

test("Ask before running code off runs python without a dialog", async () => {
  const { stores, wb } = await boot();
  wb.toggleAskExec();
  await wb.submit("Run this Python code and give me the output: print(sum(range(1, 101)))");
  await settle(stores);
  const run = Object.values(stores.runs.get().byId).find((r) => !r.seeded)!;
  expect(run.caption).toBe("Done. Primitives go straight to the Executor, so nothing was forged.");
  expect(run.call!.result).toBe("5050");
});

/* Carried requirements from the task 7-14 reviews. */

test("reset forgets the tests panel's draw marks (the run ids restart)", async () => {
  const { wb } = await boot();
  vi.mocked(clearTestMarks).mockClear();
  await wb.reset();
  expect(clearTestMarks).toHaveBeenCalledTimes(1);
});

test("the composer's submit clears the box every time, even when the submit is ignored (line 2092)", async () => {
  const { stores, wb } = await boot();
  await wb.submit("What can you do?");
  wb.setDraft("another question");
  await wb.submitDraft(); // busy: ignored, but the box still clears
  expect(stores.ui.get().draft).toBe("");
  await settle(stores);
  expect(Object.values(stores.runs.get().byId).filter((r) => !r.seeded)).toHaveLength(1);
});

test("stop during an animation returns promptly: the player is aborted before the transport stops", async () => {
  setReducedMotion(false);
  const { stores, wb } = await boot();
  await wb.submit(CAESAR);
  // Run until the Forger's code is revealing (24 ms per tick at normal speed).
  const revealing = () => {
    const r = stores.runs.get().byId[stores.ui.get().currentRunId ?? ""];
    return !!r?.code && r.code.shown > 0 && r.code.shown < r.code.lines.length;
  };
  for (let i = 0; i < 5000 && !revealing(); i++) await vi.advanceTimersToNextTimerAsync();
  expect(revealing()).toBe(true);
  let stopped = false;
  void wb.stop().then(() => (stopped = true));
  await vi.advanceTimersByTimeAsync(0);
  expect(stopped).toBe(true);
  const run = stores.runs.get().byId[stores.ui.get().currentRunId!]!;
  expect(run.status).toBe("stopped");
  expect(run.code!.shown).toBeLessThan(run.code!.lines.length);
  expect(stores.ui.get().busy).toBe(false);
});

test("a run's log is drawn without fresh lines when its bench is re-created (View this run, open, back to now)", async () => {
  const { stores, wb } = await boot();
  await wb.submit("What can you do?");
  await settle(stores);
  const id = stores.ui.get().currentRunId!;
  const markFresh = () =>
    updateRun(stores, id, (r) => ({ ...r, log: r.log.map((l) => (l.kind === "cmd" ? l : { ...l, fresh: true })) }));
  const anyFresh = () => stores.runs.get().byId[id]!.log.some((l) => l.kind !== "cmd" && (l as LogLn).fresh);

  markFresh();
  wb.viewRun(6);
  expect(anyFresh()).toBe(false);

  wb.openSession("seed-fib");
  markFresh();
  wb.backToNow();
  expect(anyFresh()).toBe(false);

  const fib = stores.session.get().sessions.find((s) => s.id === "seed-fib")!;
  const last = fib.runIds.at(-1)!;
  updateRun(stores, last, (r) => ({ ...r, log: [...r.log, { kind: "ln", label: "x", text: "y", fresh: true }] }));
  wb.openSession("seed-fib");
  expect(stores.runs.get().byId[last]!.log.some((l) => l.kind !== "cmd" && (l as LogLn).fresh)).toBe(false);
});

test("every title change the reference animates bumps titleSeq, even to the same name", async () => {
  const { stores, wb } = await boot();
  const seq = () => stores.ui.get().titleSeq;
  const s0 = seq();
  wb.openSession("seed-fib");
  expect(seq()).toBe(s0 + 1);
  wb.openSession("seed-fib"); // same session again: setTitle(sess.name, true) re-decodes it
  expect(seq()).toBe(s0 + 2);
  wb.backToNow();
  expect(seq()).toBe(s0 + 3);
  await wb.reset(); // newSession(): "Session 1" again, decoded
  expect(seq()).toBe(s0 + 4);
  await wb.submit("What can you do?"); // first run renames the session
  expect(seq()).toBe(s0 + 5);
  await settle(stores);
});

test("run links are marked only where the reference calls markRunLinks() (run end, View this run, open, back)", async () => {
  const { stores, wb } = await boot();
  expect(stores.ui.get().markedRunN).toBeNull();
  await wb.submit("What can you do?");
  expect(stores.ui.get().markedRunN).toBeNull(); // submit() never marks
  await settle(stores);
  expect(stores.ui.get().markedRunN).toBe(6); // the finally (line 1481)
  void wb.submit("What can you do?");
  await vi.advanceTimersToNextTimerAsync();
  expect(stores.ui.get().markedRunN).toBe(6); // stale while run 7 goes, as in the reference
  await settle(stores);
  expect(stores.ui.get().markedRunN).toBe(7);
  wb.viewRun(6);
  expect(stores.ui.get().markedRunN).toBe(6);
  wb.openSession("seed-fib");
  expect(stores.ui.get().markedRunN).toBe(2);
  wb.backToNow();
  expect(stores.ui.get().markedRunN).toBe(7);
});
