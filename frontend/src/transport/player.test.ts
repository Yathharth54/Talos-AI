import { freshVault } from "../store/vaultOps";
import { VAULT_ROWS } from "../demo/data";
import { createStores, type Stores } from "../store/stores";
import { setReducedMotion } from "../test/media";
import type { EventData, EventType, RunEvent } from "./types";
import { dwell, momentAfter, Player, revealPlan, typingPlan, whenText } from "./player";

let seq = 0;
const ev = <T extends EventType>(type: T, data: EventData[T]): RunEvent => ({ run_id: "r", seq: ++seq, ts: "", type, data }) as RunEvent;
const stores = (): Stores =>
  createStores({ tools: freshVault(VAULT_ROWS), settings: { askExec: true, env: {}, model: "m" }, sessions: [], runs: [], current: { id: "s1", name: "Session 1", started: "2026-09-30T12:00" }, count: 1 });
const run = (s: Stores) => s.runs.get().byId.r!;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
});
afterEach(() => vi.useRealTimers());

test("pacing math, normal and reduced motion", () => {
  expect(dwell(900, 1, false)).toBe(900);
  expect(dwell(900, 2, false)).toBe(450);
  expect(dwell(900, 0.5, false)).toBe(1800);
  expect(dwell(900, 1, true)).toBe(40);
  expect(dwell(22, 1, true)).toBe(22);
  expect(typingPlan(96)).toEqual({ step: 3, ticks: 32 });
  expect(typingPlan(10)).toEqual({ step: 1, ticks: 10 });
  expect(revealPlan(63)).toEqual({ perTick: 1, ticks: 63 });
  expect(revealPlan(200)).toEqual({ perTick: 4, ticks: 50 });
});

test("the §6 minimum dwells for live runs", () => {
  expect(momentAfter(ev("log.line", { label: "vault", text: "no match", tone: "plain" }))).toBe(400);
  expect(momentAfter(ev("forge.code", { tool: "t", attempt: 2, file: "t.py", lines: [], changed: 1, note: null }))).toBe(1300);
  expect(momentAfter(ev("forge.attempt", { attempt: 1, ok: false, detail: "" }))).toBe(700);
  expect(momentAfter(ev("node.finished", { step: "human", status: "skip" }))).toBe(450);
  expect(momentAfter(ev("vault.saved", { tool: {} as never, sub: "" }))).toBe(900);
  expect(momentAfter(ev("call.args", { tool: "t", args: [["a", "1", false], ["b", "2", false]], caption: null }))).toBe(450);
  expect(momentAfter(ev("caption", { html: "" }))).toBe(0);
});

test("a normal-speed code reveal takes 24 ms per tick and stops where it was on abort", async () => {
  setReducedMotion(false);
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  const lines = Array.from({ length: 63 }, (_, i) => `line ${i}`);
  void p.push(ev("forge.code", { tool: "t", attempt: 1, file: "t.py", lines, changed: null, note: null, tests: 5 }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).code!.shown).toBe(1);
  await vi.advanceTimersByTimeAsync(24 * 9);
  expect(run(s).code!.shown).toBe(10);
  expect(run(s).tabs.map((t) => [t.id, t.count])).toEqual([["code", undefined], ["tests", 5], ["attempts", 1]]);
  p.abort();
  await vi.advanceTimersByTimeAsync(1000);
  expect(run(s).code!.shown).toBe(10);
});

test("reduced motion caps every step at 40 ms and shows the whole answer at once", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  const done = p.push(ev("forge.tests", { tool: "t", attempt: 1, results: [{ name: "a", passed: true, why: null }, { name: "b", passed: false, why: "AssertionError" }] }));
  void p.push(ev("answer.done", { html: "It decrypts to <b>x</b>.", note: null, chips: [] }));
  // 40 ms running, 40 ms gap, then the second test runs from 80 ms to 120 ms.
  await vi.advanceTimersByTimeAsync(100);
  expect(run(s).tests!.list.map((t) => t.state)).toEqual(["passed", "running"]);
  await vi.advanceTimersByTimeAsync(60);
  await done;
  expect(run(s).tests!.list[1]).toMatchObject({ state: "failed", why: "AssertionError" });
  const talos = s.session.get().sessions[0]!.messages[1]!;
  expect(talos).toMatchObject({ kind: "talos", html: "It decrypts to <b>x</b>.", wordsOn: 5, status: null }); // "." is its own text node
  expect(s.ui.get().live).toBe("Talos: It decrypts to x.");
});

test("run.started, a failure with prune, and a stop", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  s.vault.update((v) => ({ ...v, tools: [...v.tools, { ...v.tools[0]!, name: "caesar_cipher", streak: 1 }] }));
  const q = 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"';
  void p.push(ev("run.started", { session_id: "s1", query: q, n: 7 }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).strip).toBe("vault");
  expect(s.ui.get()).toMatchObject({ busy: true, currentRunId: "r", viewingRunId: "r" });
  void p.push(ev("call.args", { tool: "caesar_cipher", args: [["text", '"AHSVZ HNLUA"', false], ["shift", '"seven"', true], ["mode", '"decrypt"', false]], caption: null }));
  void p.push(ev("vault.failure", { tool: "caesar_cipher", streak: 2, pruned: true, error: "TypeError: shift must be an int, got str" }));
  await vi.advanceTimersByTimeAsync(2000);
  expect(run(s).call!.health).toMatchObject({ streak: 2, tool: "caesar_cipher", retry: { q: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"', label: "Ask again with shift 7" } });
  expect(run(s).banner).toMatchObject({ kind: "removed", name: "caesar_cipher" });
  expect(s.vault.get().tools.some((t) => t.name === "caesar_cipher")).toBe(false);
  void p.push(ev("run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] }));
  await vi.advanceTimersByTimeAsync(0);
  expect(s.session.get().sessions[0]!.messages[1]).toMatchObject({ stopNote: "Stopped. Ask again whenever you're ready.", runLink: true, status: null });
  expect(s.ui.get().busy).toBe(false);
});

test("dispose drops later events (Reset)", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  await vi.advanceTimersByTimeAsync(0);
  p.dispose();
  void p.push(ev("caption", { html: "late" }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).caption).toBeUndefined();
});

test("a stop during the answer turns every word on and never shows the note or chips", async () => {
  setReducedMotion(false);
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  void p.push(ev("answer.done", { html: "one two three four five", note: "a note", chips: [{ kind: "forged", text: "t" }] }));
  await vi.advanceTimersByTimeAsync(34 * 2);
  const talos = () => s.session.get().sessions[0]!.messages[1]!;
  expect(talos()).toMatchObject({ wordsOn: 3, note: null });
  p.abort();
  void p.push(ev("run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] }));
  await vi.advanceTimersByTimeAsync(1000);
  expect(talos()).toMatchObject({ wordsOn: 5, note: null, chips: [], stopNote: "Stopped. Ask again whenever you're ready." });
  expect(s.ui.get().live).toBe("");
});

test("the note and chips appear only after the last word", async () => {
  setReducedMotion(false);
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  const done = p.push(ev("answer.done", { html: "one two three", note: "a note", chips: [{ kind: "forged", text: "t" }] }));
  const talos = () => s.session.get().sessions[0]!.messages[1]!;
  await vi.advanceTimersByTimeAsync(34 * 2);
  expect(talos()).toMatchObject({ wordsOn: 3, note: null, chips: [] });
  await vi.advanceTimersByTimeAsync(34);
  await done;
  expect(talos()).toMatchObject({ wordsOn: 3, note: "a note", chips: [{ kind: "forged", text: "t" }] });
});

test("a stop before any answer leaves the message without words", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  p.abort();
  await p.push(ev("run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] }));
  expect(s.session.get().sessions[0]!.messages[1]).toMatchObject({ html: null, wordsOn: 0, stopNote: "Stopped. Ask again whenever you're ready." });
});

test("node.finished accepts the stopped status", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  void p.push(ev("node.started", { step: "planner" }));
  await p.push(ev("node.finished", { step: "planner", status: "stopped", label: "Planner, stopped" }));
  expect(run(s).nodes.planner).toMatchObject({ state: "stopped", label: "Planner, stopped" });
});

test("call.error's when code maps to the reference's text", async () => {
  const ts = "2026-09-30T09:15:00Z";
  expect(whenText("declined", ts)).toBe("You chose Don't run");
  for (const code of ["run", "dispatch", "arguments", "skipped"]) expect(whenText(code, ts)).toBe("30 Sep 2026, 09:15");
  expect(whenText("run", "")).toBe("30 Sep 2026, 12:00"); // no event time: now
  expect(whenText("30 Sep 2026, 11:58", ts)).toBe("30 Sep 2026, 11:58");
  expect(whenText("later", ts)).toBe("later"); // not a stage 2 code: display text
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  await p.push(ev("call.error", { error: "declined by user", when: "declined" }));
  expect(run(s).call).toMatchObject({ error: "declined by user", when: "You chose Don't run" });
});

test("a replayed call error shows the event's time, not the replay clock", async () => {
  vi.setSystemTime(new Date("2026-10-02T18:40:00Z"));
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false, replay: true });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  await p.push({ ...ev("call.error", { error: "TypeError: boom", when: "run" }), ts: "2026-09-30T11:58:00Z" } as RunEvent);
  expect(run(s).call).toMatchObject({ error: "TypeError: boom", when: "30 Sep 2026, 11:58" });
});

test("an answer that arrives after a stop shows every word but no note, chips or live text", async () => {
  setReducedMotion(false);
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  await vi.advanceTimersByTimeAsync(0);
  p.abort();
  await p.push(ev("answer.done", { html: "one two three", note: "a note", chips: [{ kind: "forged", text: "t" }], suggest: true }));
  expect(s.session.get().sessions[0]!.messages[1]).toMatchObject({ html: "one two three", wordsOn: 3, note: null, chips: [], suggest: false, status: null });
  expect(s.ui.get().live).toBe("");
});

test("a log line stops being fresh once the log redraws for a command or the Log tab", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  await p.push(ev("log.line", { label: "plan", text: "one", tone: "plain" }));
  expect(run(s).log.at(-1)).toMatchObject({ fresh: true });
  await p.push(ev("caption", { html: "c" }));
  expect(run(s).log.at(-1)).toMatchObject({ fresh: true }); // the reference doesn't redraw the log for a caption
  const typed = p.push(ev("log.cmd", { text: "ls" }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).log.at(-2)).toMatchObject({ fresh: false }); // the first typing step redraws
  await vi.advanceTimersByTimeAsync(100);
  await typed;
  expect(run(s).log.filter((l) => l.kind !== "cmd").every((l) => !l.fresh)).toBe(true);
});
