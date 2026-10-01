import { CAESAR, SOURCES, WEATHER, type ToolMeta } from "../demo/data";
import { esc, nowIso, pyStr } from "../lib/format";
import { still } from "../lib/motion";
import { caesar, classify, NUM_WORDS, parseCaesar, provisionalVariant, PRUNE_AT, runPython, sessionName, type CaesarParams } from "../lib/routing";
import { STRIPS } from "../store/runOps";
import type { VaultTool } from "../store/types";
import { dwell } from "./player";
import type { EventData, EventSink, EventType, ResumeDecision, RunEvent, Sig, StartedRun, StepKey, Transport, Variant, VaultEntry } from "./types";

export interface DemoWorld {
  tools(): VaultTool[];
  hasKey(env: string): boolean;
  saveKey(env: string, value: string): void;
  askExec(): boolean;
  speed(): number;
  sessionRunCount(sessionId: string): number;
}

class Stopped extends Error {}

interface Outcome {
  status: "done" | "failed" | "declined";
  summary: string;
  gold: boolean;
  forged: string[];
  used: string[];
}

interface DemoRun {
  id: string;
  n: number;
  sessionId: string;
  query: string;
  sink: EventSink | null;
  seq: number;
  events: RunEvent[];
  cancelled: boolean;
  silent: boolean;
  stopping: boolean;
  done: boolean;
  timers: ReturnType<typeof setTimeout>[];
  rejectWait: (() => void) | null;
  waiting: { resolve: (d: ResumeDecision) => void; reject: (e: unknown) => void } | null;
  variant: Variant;
  labels: Map<StepKey, string>;
  active: Set<StepKey>;
  status: { text: string; gold: boolean; tone: "" | "warm" | "alert" };
  outcome: Outcome;
  flow: Promise<void> | null;
}

const sigOf = (m: ToolMeta): Sig => ({ name: m.name, args: m.args, ret: m.ret });
const entryOf = (m: ToolMeta): VaultEntry => ({
  name: m.name, args: m.args, ret: m.ret, signature: `${m.name}(${m.args}) -> ${m.ret}`, description: m.desc, keywords: m.kw,
  uses: 0, failures: 0, streak: 0, created_at: nowIso(), last_used: null, last_failure: null, last_failed_at: null, web: !!m.web,
  file: `talos/vault/tools/${m.name}.py`,
});

interface ForgeSpec {
  meta: ToolMeta;
  attempts: { lines: string[]; changed?: number; note?: string }[];
  tests: string[];
  failIdx: number;
  failWhy: string;
  smoke: { call: string; result: string } | null;
}

/** The reference's scripted flows, emitting contract events (spec 04 §8.3). */
export class DemoTransport implements Transport {
  private runs = new Map<string, DemoRun>();
  private counter: number;

  constructor(
    private readonly world: DemoWorld,
    opts: { lastRunNumber: number },
  ) {
    this.counter = opts.lastRunNumber;
  }

  async startRun(sessionId: string, text: string): Promise<StartedRun> {
    const n = ++this.counter;
    const id = `demo-${n}`;
    const variant = provisionalVariant(text, this.world.tools().map((t) => t.name));
    this.runs.set(id, {
      id, n, sessionId, query: text, sink: null, seq: 0, events: [], cancelled: false, silent: false, stopping: false, done: false,
      timers: [], rejectWait: null, waiting: null, variant, labels: new Map(STRIPS[variant].map(([k, l]) => [k, l])), active: new Set(),
      status: { text: "", gold: false, tone: "" }, outcome: { status: "done", summary: "", gold: false, forged: [], used: [] }, flow: null,
    });
    const first = this.world.sessionRunCount(sessionId) === 0;
    return { runId: id, n, sessionName: first ? sessionName(classify(text), text) : null };
  }

  subscribe(runId: string, sink: EventSink): () => void {
    const r = this.runs.get(runId);
    if (!r) return () => {};
    r.sink = sink;
    if (!r.flow) r.flow = this.play(r);
    return () => {
      r.sink = null;
    };
  }

  async resume(runId: string, decision: ResumeDecision): Promise<void> {
    const r = this.runs.get(runId);
    const w = r?.waiting;
    if (!r || !w) return;
    r.waiting = null;
    w.resolve(decision);
  }

  /** stopRun() (line 1485). */
  async stop(runId: string): Promise<void> {
    const r = this.runs.get(runId);
    if (!r || r.done || r.cancelled) return;
    this.cancel(r);
    await r.flow?.catch(() => {});
    r.stopping = true;
    for (const [step] of STRIPS[r.variant]) {
      if (!r.active.has(step)) continue;
      const label = `${(r.labels.get(step) ?? "").replace(/, .*$/, "")}, stopped`;
      await this.emit(r, "node.finished", { step, status: "stopped", label });
    }
    await this.line(r, "stop", "stopped by you", "w");
    await this.logStatus(r, "Stopped");
    await this.cap(r, "You stopped this run. Nothing was saved to the vault.");
    await this.emit(r, "run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] });
    r.done = true;
  }

  /** resetDemo() (line 2280): every run ends without another event. */
  reset(lastRunNumber: number): void {
    for (const r of this.runs.values()) {
      r.silent = true;
      this.cancel(r);
    }
    this.runs.clear();
    this.counter = lastRunNumber;
  }

  events(runId: string): RunEvent[] {
    return this.runs.get(runId)?.events ?? [];
  }

  /* ---------- plumbing ---------- */

  private cancel(r: DemoRun): void {
    r.cancelled = true;
    r.timers.forEach(clearTimeout);
    r.rejectWait?.();
    r.waiting?.reject(new Stopped());
    r.waiting = null;
  }

  private async emit<T extends EventType>(r: DemoRun, type: T, data: EventData[T]): Promise<void> {
    if (r.silent || (r.cancelled && !r.stopping)) throw new Stopped();
    r.seq += 1;
    if (type === "node.started" || type === "node.finished") {
      const d = data as EventData["node.started"] & { label?: string };
      if (d.label) r.labels.set(d.step, d.label);
      if (type === "node.started") r.active.add(d.step);
      else r.active.delete(d.step);
    }
    if (type === "strip.set") {
      const v = (data as EventData["strip.set"]).variant;
      if (v !== r.variant) {
        r.variant = v;
        for (const [k, l] of STRIPS[v]) if (!r.labels.has(k)) r.labels.set(k, l);
      }
    }
    const e = { run_id: r.id, seq: r.seq, ts: new Date().toISOString(), type, data } as RunEvent;
    r.events.push(e);
    await r.sink?.(e);
    if (r.silent || (r.cancelled && !r.stopping)) throw new Stopped();
  }

  /** wait() (line 926) for the moments the player doesn't own. */
  private wait(r: DemoRun, ms: number): Promise<void> {
    return new Promise((resolve, reject) => {
      if (r.cancelled) return reject(new Stopped());
      const t = setTimeout(() => {
        r.rejectWait = null;
        if (r.cancelled) reject(new Stopped());
        else resolve();
      }, dwell(ms, this.world.speed(), still()));
      r.timers.push(t);
      r.rejectWait = () => {
        clearTimeout(t);
        reject(new Stopped());
      };
    });
  }

  private async interrupt(r: DemoRun, data: EventData["interrupt"]): Promise<ResumeDecision> {
    await this.emit(r, "interrupt", data);
    const d = await new Promise<ResumeDecision>((resolve, reject) => {
      r.waiting = { resolve, reject };
    });
    if (r.cancelled) throw new Stopped();
    return d;
  }

  private node = (r: DemoRun, step: StepKey, state: string, label?: string) =>
    state === "active"
      ? this.emit(r, "node.started", label ? { step, label } : { step })
      : this.emit(r, "node.finished", { step, status: state as EventData["node.finished"]["status"], ...(label ? { label } : {}) });
  private flowTo = (r: DemoRun, from: StepKey, to: StepKey) => this.emit(r, "link.flow", { from, to });
  private cap = (r: DemoRun, html: string) => this.emit(r, "caption", { html });
  private say = (r: DemoRun, text: string) => this.emit(r, "talos.status", { text });
  private line = (r: DemoRun, label: string, text: string, tone: "plain" | "g" | "w" | "sub" = "plain", caret = false) =>
    this.emit(r, "log.line", caret ? { label, text, tone, caret } : { label, text, tone });
  private logStatus(r: DemoRun, text: string, gold = false) {
    r.status = { ...r.status, text, gold };
    return this.emit(r, "log.status", { ...r.status });
  }
  private logTone(r: DemoRun, tone: "" | "warm" | "alert") {
    r.status = { ...r.status, tone };
    return this.emit(r, "log.status", { ...r.status });
  }
  private strip = (r: DemoRun, variant: Variant, label: string, sig: Sig | null, title?: string) =>
    this.emit(r, "strip.set", { variant, subtask: { index: 1, total: 1, label }, sig, ...(title ? { title } : {}) });
  private findTool = (name: string) => this.world.tools().find((t) => t.name === name);

  /* ---------- flows ---------- */

  private async play(r: DemoRun): Promise<void> {
    try {
      await this.emit(r, "run.started", { session_id: r.sessionId, query: r.query, n: r.n });
      await this.emit(r, "log.cmd", { text: r.query });
      const kind = classify(r.query);
      if (kind === "caesar") await this.flowCaesar(r, parseCaesar(r.query));
      else if (kind === "python") await this.flowPython(r, r.query);
      else if (kind === "weather") await this.flowWeather(r, r.query);
      else if (kind === "vaultlist") await this.flowVaultList(r);
      else if (kind === "chat") await this.flowChat(r);
      else await this.flowUnknown(r);
    } catch (err) {
      if (err instanceof Stopped) return;
      console.error(err);
      r.outcome = { ...r.outcome, status: "failed" };
    }
    const o = r.outcome;
    await this.emit(r, "run.finished", { status: o.status, summary: o.summary, summary_gold: o.gold, forged: o.forged, used: o.used }).catch(() => {});
    r.done = true;
  }

  /** planner() (line 1517). */
  private async planner(r: DemoRun, caption: string, logText: string, needs: "primitive" | "vault" | "forge" | null, tool: string | null) {
    await this.node(r, "planner", "active");
    await this.cap(r, "The Planner is splitting your request into sub-tasks and checking the vault.");
    await this.say(r, "Planning");
    await this.wait(r, 900);
    await this.node(r, "planner", "done");
    await this.emit(r, "plan.ready", { subtasks: needs ? [{ id: 1, action: r.query, needs, tool_hint: tool, depends_on: [] }] : [], verdict: "" });
    await this.line(r, "plan", logText);
    await this.cap(r, caption);
  }

  /** forgeTool() (line 1527). Returns the number of attempts. */
  private async forgeTool(r: DemoRun, spec: ForgeSpec): Promise<number> {
    const meta = spec.meta;
    await this.strip(r, "forge", "Sub-task 1 of 1, needs a new tool", sigOf(meta));
    await this.line(r, "vault", "no match");
    await this.wait(r, 400);
    await this.flowTo(r, "planner", "forger");
    await this.say(r, `Writing ${meta.name}`);
    for (let a = 0; a < spec.attempts.length; a++) {
      const att = spec.attempts[a]!;
      const n = a + 1;
      await this.node(r, "forger", "active");
      if (a > 0) await this.node(r, "tester", "forge");
      await this.cap(
        r,
        a === 0
          ? `The Forger is writing <span class="mono">${esc(meta.name)}</span> and its tests in one structured call.`
          : `<span class="gold">Attempt ${n} of 3.</span> The failing test and its traceback went back to the Forger.`,
      );
      await this.line(r, "forge", a === 0 ? `${meta.name}()` : `attempt ${n}`, "g");
      await this.emit(r, "forge.code", { tool: meta.name, attempt: n, file: `${meta.name}.py`, lines: att.lines, changed: att.changed ?? null, note: att.note ?? null, tests: spec.tests.length });
      if (a > 0) await this.wait(r, 1300);
      await this.node(r, "forger", "forge");
      await this.flowTo(r, "forger", "tester");
      await this.node(r, "tester", "active");
      await this.cap(r, `<span class="gold">Attempt ${n} of 3.</span> Running ${spec.tests.length} tests in a subprocess, 10-second limit.`);
      await this.line(r, "test", "running", "g", true);
      const fail = a === 0 && spec.failIdx >= 0 && spec.attempts.length > 1;
      await this.emit(r, "forge.tests", {
        tool: meta.name,
        attempt: n,
        results: spec.tests.map((name, i) => ({ name, passed: !(fail && i === spec.failIdx), why: fail && i === spec.failIdx ? spec.failWhy : null })),
      });
      await this.emit(r, "log.pop", {});
      if (fail) {
        const failing = spec.tests[spec.failIdx]!;
        await this.line(r, "test", `${spec.tests.length - 1} of ${spec.tests.length} passed, retrying`, "g");
        await this.line(r, "", failing, "sub");
        await this.emit(r, "forge.attempt", { attempt: n, ok: false, detail: `${failing}\n${spec.failWhy}` });
        await this.say(r, "The first attempt failed a test. Trying again");
        await this.wait(r, 700);
      } else {
        await this.line(r, "test", `${spec.tests.length} of ${spec.tests.length} passed`, "g");
        await this.emit(r, "forge.attempt", { attempt: n, ok: true, detail: `${spec.tests.length} of ${spec.tests.length} tests passed` });
      }
    }
    if (spec.smoke) {
      await this.cap(r, "Smoke test: the tool runs once on a real input before it can be saved.");
      await this.emit(r, "forge.smoke", { call: spec.smoke.call, result: spec.smoke.result, passed: true });
      await this.line(r, "smoke", spec.smoke.result);
      await this.wait(r, 400);
    }
    await this.node(r, "tester", "forge");
    await this.flowTo(r, "tester", "human");
    return spec.attempts.length;
  }

  /** humanCheck() (line 1595). Returns whether a key is available. */
  private async humanCheck(r: DemoRun, meta: ToolMeta): Promise<boolean> {
    if (!meta.env) {
      await this.node(r, "human", "skip");
      await this.cap(r, "No API key needed, so Human check passed straight through.");
      await this.wait(r, 450);
      await this.flowTo(r, "human", "learn");
      return true;
    }
    if (this.world.hasKey(meta.env)) {
      await this.node(r, "human", "skip");
      await this.cap(r, `<span class="mono">${esc(meta.env)}</span> is already set, so Human check passed straight through.`);
      await this.line(r, "check", "key already set");
      await this.wait(r, 450);
      await this.flowTo(r, "human", "learn");
      return true;
    }
    await this.node(r, "human", "active");
    await this.cap(r, `Human check paused the graph. <span class="mono">${esc(meta.name)}</span> needs <span class="mono">${esc(meta.env)}</span>.`);
    await this.line(r, "check", "waiting for a key", "g", true);
    await this.logStatus(r, "Waiting for you", true);
    await this.say(r, "The tool is written and tested. It needs an API key before it can run");
    await this.wait(r, 350);
    const res = await this.interrupt(r, { kind: "missing_api_key", payload: { env_var: meta.env, tool_name: meta.name, service: "OpenWeatherMap" } });
    const save = res.decision === "save";
    await this.emit(r, "interrupt.resolved", { kind: "missing_api_key", decision: save ? "save" : "skip" });
    await this.emit(r, "log.pop", {});
    if (save && res.decision === "save") {
      this.world.saveKey(meta.env, res.value);
      await this.line(r, "check", "key saved to .env");
      await this.node(r, "human", "done");
      await this.cap(r, `Saved <span class="mono">${esc(meta.env)}</span> to .env. Talos won't ask again.`);
    } else {
      await this.line(r, "check", "skipped by you");
      await this.node(r, "human", "done", "Human check, skipped");
      await this.cap(r, "You skipped the key. The tool is still saved, but it will fail until the key is set.");
    }
    await this.logStatus(r, "Forging", true);
    await this.wait(r, 500);
    await this.flowTo(r, "human", "learn");
    return save;
  }

  /** learn() (line 1639). */
  private async learn(r: DemoRun, meta: ToolMeta, sub: string) {
    await this.node(r, "learn", "active");
    await this.cap(r, "Learn is writing the .py file and its manifest entry.");
    await this.wait(r, 600);
    await this.node(r, "learn", "done");
    await this.line(r, "learn", "saved to the vault");
    await this.emit(r, "vault.saved", { tool: entryOf(meta), sub });
    await this.flowTo(r, "learn", "executor");
    await this.wait(r, 900);
  }

  /** flowCaesar() (line 1654). */
  private async flowCaesar(r: DemoRun, p: CaesarParams) {
    if (!this.findTool(CAESAR.name)) {
      await this.planner(r, "1 sub-task. Nothing in the vault matches, so it needs a new tool.", "1 sub-task, needs a new tool", "forge", CAESAR.name);
      await this.logStatus(r, "Forging", true);
      const src = SOURCES.caesar_cipher!;
      const bad = src.slice();
      bad[47] = "    effective_shift = shift";
      const attempts = await this.forgeTool(r, {
        meta: CAESAR,
        attempts: [{ lines: bad }, { lines: src, changed: 48, note: "Line 48 is new in attempt 2. Decrypt now shifts backwards instead of forwards." }],
        tests: ["test_encrypt_shifts_forward", "test_decrypt_reverses_encrypt", "test_preserves_case_and_spaces", "test_wraps_past_z", "test_rejects_unknown_mode"],
        failIdx: 1,
        failWhy: "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'",
        smoke: { call: 'caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")', result: "'AHSVZ HNLUA'" },
      });
      await this.humanCheck(r, CAESAR);
      await this.learn(r, CAESAR, "Next time a request needs a Caesar cipher, Talos skips forging and goes straight to Execute.");
      r.outcome.forged = [CAESAR.name];
      await this.executeCaesar(r, p, true, attempts);
      return;
    }
    await this.planner(
      r,
      `The Planner matched <span class="mono">caesar_cipher</span> on the keywords caesar, cipher and ${p.mode}. Nothing will be written or tested this time.`,
      "1 sub-task, in the vault",
      "vault",
      CAESAR.name,
    );
    await this.strip(r, "vault", "Sub-task 1 of 1, found in the vault", sigOf(CAESAR));
    await this.flowTo(r, "planner", "vault");
    await this.node(r, "vault", "done");
    await this.line(r, "vault", CAESAR.name);
    await this.logTone(r, "warm");
    await this.logStatus(r, "0 tools forged");
    await this.say(r, "Found caesar_cipher in the vault");
    await this.wait(r, 500);
    await this.flowTo(r, "vault", "skip");
    await this.wait(r, 350);
    await this.flowTo(r, "skip", "executor");
    await this.executeCaesar(r, p, false, 0);
  }

  /** executeCaesar() (line 1698). */
  private async executeCaesar(r: DemoRun, p: CaesarParams, afterForge: boolean, attempts: number) {
    r.outcome.used = [CAESAR.name];
    await this.node(r, "executor", "active");
    await this.cap(r, "The Executor is reading your message and filling in the arguments.");
    await this.say(r, "Running caesar_cipher");
    const shiftVal = p.shiftWord ? JSON.stringify(p.shiftWord) : String(p.shift);
    await this.emit(r, "call.args", {
      tool: CAESAR.name,
      args: [["text", JSON.stringify(p.text), false], ["shift", shiftVal, !!p.shiftWord], ["mode", JSON.stringify(p.mode), false]],
      caption: null,
    });
    await this.wait(r, 450);
    if (p.shiftWord) {
      const tool = this.findTool(CAESAR.name)!;
      const err = "TypeError: shift must be an int, got str";
      const streak = tool.streak + 1;
      const pruned = streak >= PRUNE_AT;
      await this.emit(r, "call.error", { error: err, when: "run" });
      await this.node(r, "executor", "fail", "Executor failed");
      await this.line(r, "execute", "failed, TypeError", "w");
      await this.logTone(r, "alert");
      await this.logStatus(r, "1 step failed");
      await this.line(r, "vault", pruned ? `removed after ${PRUNE_AT} failures in a row` : `${streak} failure in a row`);
      await this.emit(r, "vault.failure", { tool: CAESAR.name, streak, pruned, error: err });
      await this.flowTo(r, "executor", "answer");
      await this.node(r, "answer", "answer");
      await this.cap(r, "The run still finished. Talos explained the failure instead of guessing a result.");
      r.outcome = { ...r.outcome, summary: pruned ? "Failed, removed from the vault" : "Failed, 1 failure in a row", gold: false };
      const digit = NUM_WORDS[p.shiftWord];
      await this.emit(r, "answer.done", {
        html: `I couldn't ${p.mode} that. <span class="mono">caesar_cipher</span> needs the shift as a number, and it was given the word "${esc(p.shiftWord)}".`,
        note: digit != null ? `Ask again with "shift ${digit}" and it should work.` : "Ask again with the shift as a number.",
        chips: [{ kind: "failed", text: "caesar_cipher raised a TypeError" }],
      });
      return;
    }
    const out = caesar(p.text, p.shift, p.mode);
    await this.emit(r, "call.result", { repr: pyStr(out), type: "str", small: false });
    await this.node(r, "executor", "done");
    await this.line(r, "execute", "done", "w");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    if (afterForge) {
      await this.logStatus(r, "1 tool forged", true);
      await this.cap(r, `Done in ${attempts} attempts. No API key was needed, so Human check passed straight through.`);
      r.outcome = { ...r.outcome, summary: `1 tool forged, ${attempts} attempts`, gold: true };
    } else {
      await this.cap(r, "Done from the vault. The forge sub-graph never ran.");
      r.outcome = { ...r.outcome, summary: "0 tools forged", gold: false };
    }
    const html =
      p.mode === "encrypt"
        ? `"${esc(p.text)}" encrypted with a shift of ${p.shift} is <span class="mono">${esc(out)}</span>.`
        : `It decrypts to <span class="mono">${esc(out)}</span>.`;
    const note = afterForge
      ? p.mode === "encrypt"
        ? 'The same tool decrypts too. Ask with "decrypt" and the same shift.'
        : 'The same tool encrypts too. Ask with "encrypt" and the same shift.'
      : null;
    await this.emit(r, "answer.done", {
      html,
      note,
      chips: [{ kind: afterForge ? "forged" : "reused", text: afterForge ? "Forged caesar_cipher" : "Reused caesar_cipher from the vault" }],
    });
  }

  /** flowPython() (line 1779). */
  private async flowPython(r: DemoRun, q: string) {
    const m = q.match(/`([^`]+)`/) || q.match(/:\s*(.+)$/);
    const code = (m?.[1] ?? "print(sum(range(1, 101)))").trim();
    await this.planner(r, "1 sub-task, a built-in primitive. Nothing needs forging.", "1 sub-task, primitive", "primitive", "python_exec");
    await this.strip(r, "primitive", "Sub-task 1 of 1, built-in primitive", { name: "python_exec", args: "code: str, timeout: int | None = None", ret: "dict" });
    await this.flowTo(r, "planner", "primitive");
    await this.node(r, "primitive", "done");
    await this.flowTo(r, "primitive", "executor");
    await this.emit(r, "call.args", { tool: "python_exec", args: [["code", JSON.stringify(code), false]], caption: "Written by the Executor" });
    let approved = true;
    if (this.world.askExec()) {
      await this.node(r, "executor", "active", "Executor, waiting for you");
      await this.cap(r, 'The Executor paused. <span class="mono">python_exec</span> runs code on your machine, so it asks first.');
      await this.line(r, "execute", "paused for approval", "g", true);
      await this.logStatus(r, "Waiting for you", true);
      await this.say(r, "Waiting for you to approve the code");
      await this.wait(r, 350);
      const res = await this.interrupt(r, { kind: "confirm_exec", payload: { tool: "python_exec", preview: code } });
      approved = res.decision === "approve";
      await this.emit(r, "interrupt.resolved", { kind: "confirm_exec", decision: approved ? "approve" : "decline" });
      await this.emit(r, "log.pop", {});
    } else {
      await this.node(r, "executor", "active");
      await this.cap(r, 'Ran without asking, because "Ask before running code" is off in Settings.');
    }
    if (!approved) {
      await this.node(r, "executor", "fail", "Executor, declined");
      await this.line(r, "execute", "declined by you", "w");
      await this.logStatus(r, "Not run");
      await this.emit(r, "call.error", { error: "declined by user", when: "declined" });
      await this.flowTo(r, "executor", "answer");
      await this.node(r, "answer", "answer");
      await this.cap(r, "Nothing ran. The sub-task is recorded as declined.");
      r.outcome = { ...r.outcome, status: "declined", summary: "Declined, nothing ran" };
      await this.emit(r, "answer.done", { html: "I didn't run the code, so I don't have its output.", note: "Approve it next time, or turn off the prompt in Settings.", chips: [] });
      return;
    }
    await this.line(r, "execute", "running", "g", true);
    await this.wait(r, 700);
    await this.emit(r, "log.pop", {});
    const out = runPython(code);
    await this.emit(r, "call.result", out == null ? { repr: "The demo only runs simple print() calls.", type: "", small: true } : { repr: out, type: "stdout", small: false });
    await this.node(r, "executor", "done", "Executor");
    await this.line(r, "execute", "done", "w");
    await this.logStatus(r, "0 tools forged");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    await this.cap(r, "Done. Primitives go straight to the Executor, so nothing was forged.");
    r.outcome = { ...r.outcome, summary: "Built-in, approved" };
    await this.emit(r, "answer.done", {
      html: out == null ? 'This demo can only run simple <span class="mono">print()</span> calls, so there\'s no output to show.' : `The code prints <span class="mono">${esc(out)}</span>.`,
      note: null,
      chips: [],
    });
  }

  /** flowWeather() (line 1840). */
  private async flowWeather(r: DemoRun, q: string) {
    const cityM = q.match(/\bin ([A-Z][A-Za-z .'-]+?)(?:[.?!]|$)/);
    const city = cityM ? (cityM[1] ?? "").trim() : "Mumbai";
    const env = WEATHER.env!;
    let hasKey = this.world.hasKey(env);
    let forged = false;
    if (!this.findTool(WEATHER.name)) {
      await this.planner(r, "1 sub-task. Nothing in the vault fetches weather, so it needs a new tool.", "1 sub-task, needs a new tool", "forge", WEATHER.name);
      await this.logStatus(r, "Forging", true);
      await this.forgeTool(r, {
        meta: WEATHER,
        attempts: [{ lines: SOURCES.get_current_temperature! }],
        tests: ["test_reads_temperature_from_response", "test_raises_when_key_missing", "test_raises_on_unknown_city"],
        failIdx: -1,
        failWhy: "",
        smoke: null,
      });
      hasKey = await this.humanCheck(r, WEATHER);
      await this.learn(r, WEATHER, "Next time you ask about the weather, Talos reuses it. It reads the key from .env.");
      forged = true;
      r.outcome.forged = [WEATHER.name];
    } else {
      await this.planner(r, `The Planner matched <span class="mono">${WEATHER.name}</span> in the vault.`, "1 sub-task, in the vault", "vault", WEATHER.name);
      await this.strip(r, "vault", "Sub-task 1 of 1, found in the vault", sigOf(WEATHER));
      await this.flowTo(r, "planner", "vault");
      await this.node(r, "vault", "done");
      await this.line(r, "vault", WEATHER.name);
      await this.logTone(r, "warm");
      await this.logStatus(r, "0 tools forged");
      await this.wait(r, 400);
      await this.flowTo(r, "vault", "skip");
      await this.wait(r, 300);
      await this.flowTo(r, "skip", "executor");
    }
    r.outcome.used = [WEATHER.name];
    await this.node(r, "executor", "active");
    await this.cap(r, "The Executor is filling in the arguments.");
    // Ruling 10: the reference hard-codes "34 lines" for the reused weather tool (line 1869), though the file has 36.
    await this.emit(r, "call.args", { tool: WEATHER.name, args: [["city", JSON.stringify(city), false]], caption: null, ...(forged ? {} : { code_cap: "34 lines" }) });
    await this.wait(r, 500);
    if (!hasKey) {
      const tool = this.findTool(WEATHER.name)!;
      const err = "RuntimeError: OPENWEATHERMAP_API_KEY is not set";
      const streak = tool.streak + 1;
      const pruned = streak >= PRUNE_AT;
      await this.emit(r, "call.error", { error: err, when: "run" });
      await this.emit(r, "vault.failure", { tool: WEATHER.name, streak, pruned, error: err });
      await this.node(r, "executor", "fail", "Executor failed");
      await this.line(r, "execute", "failed, RuntimeError", "w");
      await this.logTone(r, "alert");
      await this.logStatus(r, "1 step failed");
      await this.flowTo(r, "executor", "answer");
      await this.node(r, "answer", "answer");
      await this.cap(r, "The tool ran without its key and raised an error.");
      r.outcome = { ...r.outcome, summary: forged ? "1 tool forged, failed without a key" : "Failed without a key", gold: forged };
      await this.emit(r, "answer.done", {
        html: `I couldn't get the temperature. <span class="mono">${WEATHER.name}</span> needs <span class="mono">${env}</span>, and it isn't set.`,
        note: "Ask again and paste the key when Human check asks for it.",
        chips: [{ kind: "failed", text: `${WEATHER.name} raised a RuntimeError` }],
      });
      return;
    }
    await this.emit(r, "call.result", { repr: "Not called in this demo", type: "", small: true });
    await this.node(r, "executor", "done");
    await this.line(r, "execute", "done (demo stops before the API)", "w");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    if (forged) {
      await this.logStatus(r, "1 tool forged", true);
      r.outcome = { ...r.outcome, summary: "1 tool forged, key saved", gold: true };
    } else r.outcome = { ...r.outcome, summary: "0 tools forged", gold: false };
    await this.cap(r, "Done. In Talos the Executor would call OpenWeatherMap here with your key.");
    await this.emit(r, "answer.done", {
      html: "The tool is ready and your key is saved. This demo can't reach the internet, so it stops before calling OpenWeatherMap.",
      note: `In Talos, you'd get the current temperature in ${esc(city)} here.`,
      chips: [{ kind: forged ? "forged" : "reused", text: forged ? `Forged ${WEATHER.name}` : `Reused ${WEATHER.name} from the vault` }],
    });
  }

  /** flowVaultList() (line 1909). */
  private async flowVaultList(r: DemoRun) {
    await this.planner(r, '1 sub-task, a built-in primitive: <span class="mono">vault_list</span>.', "1 sub-task, primitive", "primitive", "vault_list");
    await this.strip(r, "primitive", "Sub-task 1 of 1, built-in primitive", { name: "vault_list", args: "", ret: "list[dict]" });
    await this.flowTo(r, "planner", "primitive");
    await this.node(r, "primitive", "done");
    await this.flowTo(r, "primitive", "executor");
    await this.node(r, "executor", "active");
    await this.emit(r, "call.args", { tool: "vault_list", args: [], caption: "Takes no arguments" });
    await this.wait(r, 700);
    const tools = this.world.tools();
    const n = tools.length;
    const top = tools.slice().sort((a, b) => b.uses - a.uses).slice(0, 2);
    await this.emit(r, "call.result", { repr: `${n} tools`, type: "list[dict]", small: false });
    await this.node(r, "executor", "done");
    await this.line(r, "execute", "done", "w");
    await this.logStatus(r, "0 tools forged");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    await this.cap(r, "Done. Talos read its own manifest.");
    r.outcome = { ...r.outcome, summary: "Built-in" };
    await this.emit(r, "answer.done", {
      html: `There are ${n} tools in the vault. The most used are <span class="mono">${esc(top[0]!.name)}</span> and <span class="mono">${esc(top[1]!.name)}</span>, with ${top[0]!.uses} uses each.`,
      note: 'Open <a href="#vault">the Vault</a> to see all of them.',
      chips: [],
    });
  }

  /** flowChat() (line 1930). */
  private async flowChat(r: DemoRun) {
    await this.planner(r, "The Planner returned an empty plan. There's nothing to run, so Talos answers directly.", "no sub-tasks, answering directly", null, null);
    await this.strip(r, "chat", "Conversational", null);
    await this.flowTo(r, "planner", "answer");
    await this.node(r, "answer", "answer");
    await this.logStatus(r, "0 tools forged");
    r.outcome = { ...r.outcome, summary: "Answered directly" };
    await this.emit(r, "answer.done", {
      html: `I split your request into steps, then use a built-in tool, reuse one from my vault, or write and test a new Python tool for whatever's missing. The vault holds ${this.world.tools().length} tools right now.`,
      note: "Try asking me to build a Caesar cipher.",
      chips: [],
    });
  }

  /** flowUnknown() (line 1940). */
  private async flowUnknown(r: DemoRun) {
    await this.planner(r, "This demo only replays a few scripted runs, so the Planner stops here.", "not in this demo", null, null);
    await this.strip(r, "chat", "Scripted demo", null, "Not in this demo");
    await this.flowTo(r, "planner", "answer");
    await this.node(r, "answer", "answer");
    await this.logStatus(r, "Nothing ran");
    r.outcome = { ...r.outcome, summary: "Not in this demo" };
    await this.emit(r, "answer.done", {
      html: "This demo can't plan that one. It replays a few scripted runs over the real vault. Try one of these:",
      note: null,
      chips: [],
      suggest: true,
    });
  }
}
