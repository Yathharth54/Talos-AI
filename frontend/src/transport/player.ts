import { COPY, fill, healthText, removedSub, retryLabel } from "../lib/copy";
import { fmtTime, nowIso } from "../lib/format";
import { still as reducedMotion, wrapWordsHtml } from "../lib/motion";
import { NUM_WORDS, PRUNE_AT, provisionalVariant } from "../lib/routing";
import * as R from "../store/runOps";
import * as M from "../store/sessionOps";
import { updateRun, type Stores } from "../store/stores";
import type { CallArg, CallState, Run, Tab, TalosMessage } from "../store/types";
import * as V from "../store/vaultOps";
import type { EventOf, EventSink, RunEvent, StepKey } from "./types";

export const STILL_CAP_MS = 40;
/** The reference's wait() scaling (line 929). */
export const dwell = (ms: number, speed: number, still: boolean): number => (still ? Math.min(ms, STILL_CAP_MS) : ms / speed);

/** typeCmd() (line 1299). */
export function typingPlan(len: number): { step: number; ticks: number } {
  const step = Math.max(1, Math.ceil(len / 40));
  return { step, ticks: Math.ceil(len / step) };
}
/** revealCode() (line 1314). */
export function revealPlan(lines: number): { perTick: number; ticks: number } {
  const perTick = Math.max(1, Math.round(lines / 45));
  return { perTick, ticks: Math.ceil(lines / perTick) };
}

/** Fact animations: always player-side (ruling 4). */
export const PACE = { typeStep: 22, revealTick: 24, testRun: 360, testGap: 90, smokeRun: 800, argEach: 260, argSingle: 350, word: 34 } as const;
/** Spec 04 §6 minimum dwells: live runs only (momentDwell). DemoTransport waits these itself. */
export const MOMENTS = {
  afterVaultNoMatch: 400, retryShown: 1300, afterFailedAttempt: 700, afterSmoke: 400, humanPass: 450, afterSaved: 900,
  beforeResult: 450, beforeResultSingle: 500, vaultStep: 500, vaultSkip: 350, beforeDialog: 350,
} as const;
export const MIN_ACTIVE: Partial<Record<StepKey, number>> = { planner: 900, learn: 600 };

export function momentAfter(e: RunEvent): number {
  switch (e.type) {
    case "log.line":
      if (e.data.label === "vault" && e.data.text === "no match") return MOMENTS.afterVaultNoMatch;
      return e.data.label === "smoke" ? MOMENTS.afterSmoke : 0;
    case "forge.code":
      return e.data.attempt > 1 ? MOMENTS.retryShown : 0;
    case "forge.attempt":
      return e.data.ok ? 0 : MOMENTS.afterFailedAttempt;
    case "node.finished":
      if (e.data.step === "human" && e.data.status === "skip") return MOMENTS.humanPass;
      return e.data.step === "vault" ? MOMENTS.vaultStep : 0;
    case "link.flow":
      return e.data.from === "vault" && e.data.to === "skip" ? MOMENTS.vaultSkip : 0;
    case "vault.saved":
      return MOMENTS.afterSaved;
    case "call.args":
      if (e.data.caption) return 0;
      return e.data.args.length === 1 ? MOMENTS.beforeResultSingle : MOMENTS.beforeResult;
    default:
      return 0;
  }
}

const RUNNING_PENDING = `${COPY.call.running}<span class="caret" aria-hidden="true"></span>`;
const textOf = (html: string): string => {
  const p = document.createElement("p");
  p.innerHTML = html;
  return p.textContent ?? "";
};
const wordCount = (html: string | null): number => (html == null ? 0 : wrapWordsHtml(html, 0).count);

/** Stage 2's `call.error.when` codes (talos/agents/executor.py) that the reference shows as the failure's time. */
const TIMED_CODES = new Set(["run", "dispatch", "arguments", "skipped"]);

/**
 * `call.error.when` is a code from stage 2. The reference shows the time of a failed call (lines 1713,
 * 1881), taken from the event's `ts` so a replay shows when it happened, and "You chose Don't run" for a
 * declined one (line 1813). Anything else is already display text and passes through.
 */
export function whenText(when: string, ts: string): string {
  if (when === "declined") return COPY.call.declinedWhen;
  return TIMED_CODES.has(when) ? fmtTime(ts || nowIso()) : when;
}

export interface PlayerOptions {
  runId: string;
  sessionId: string;
  /** Live runs apply the §6 minimum dwells; DemoTransport performs them itself (ruling 4). */
  momentDwell: boolean;
  /** Replaying a finished run: no pacing, final states, no messages. */
  replay?: boolean;
  /** Tool source for vault runs' Code tab. */
  source?: (tool: string) => Promise<string[] | null>;
  /** Reattach (spec 04 §6): events stamped at or before this ISO time apply without pacing or dialogs. */
  catchUpUntil?: string;
}

/** Turns contract events into store updates, with the reference's pacing (spec 04 §6). */
export class Player {
  private queue: Promise<void> = Promise.resolve();
  private aborted = false;
  private gone = false;
  private wake: (() => void) | null = null;
  private startedAt = new Map<StepKey, number>();
  private callTool: string | null = null;
  private testsCount: number | undefined;
  private catching = false;

  constructor(
    private readonly stores: Stores,
    private readonly opts: PlayerOptions,
  ) {}

  /** The EventSink: resolves once the event is on screen and its animation is over. */
  push: EventSink = (e) => {
    this.queue = this.queue
      .then(() => (this.gone ? undefined : this.apply(e)))
      .catch((err: unknown) => console.error("player", err));
    return this.queue;
  };

  /** Stop: animations stay where they are; later events apply without pacing. */
  abort(): void {
    this.aborted = true;
    this.wake?.();
  }
  /** Whether Stop (or Reset) has aborted this player. */
  get stopped(): boolean {
    return this.aborted;
  }
  /** Reset: nothing more is applied. */
  dispose(): void {
    this.gone = true;
    this.abort();
  }

  private get fast(): boolean {
    return this.aborted || !!this.opts.replay || this.catching;
  }
  /** Replays and caught-up events describe the past: the vault store is reloaded from the API instead. */
  private get quiet(): boolean {
    return !!this.opts.replay || this.catching;
  }
  private sleep(ms: number): Promise<void> {
    if (this.fast || ms <= 0) return Promise.resolve();
    const d = dwell(ms, this.stores.ui.get().speed, reducedMotion());
    return new Promise((resolve) => {
      const t = setTimeout(() => {
        this.wake = null;
        resolve();
      }, d);
      this.wake = () => {
        clearTimeout(t);
        this.wake = null;
        resolve();
      };
    });
  }
  private run(): Run {
    return this.stores.runs.get().byId[this.opts.runId]!;
  }
  private up(fn: (r: Run) => Run): void {
    updateRun(this.stores, this.opts.runId, fn);
  }
  private talos(fn: (m: TalosMessage) => TalosMessage): void {
    const n = this.run().n;
    this.stores.session.update((s) => M.updateTalos(s, n, fn));
  }

  private async apply(e: RunEvent): Promise<void> {
    this.catching = !!this.opts.catchUpUntil && Date.parse(e.ts) <= Date.parse(this.opts.catchUpUntil);
    if (this.opts.momentDwell) {
      if (e.type === "node.finished") {
        const min = MIN_ACTIVE[e.data.step];
        const at = this.startedAt.get(e.data.step);
        if (min && at != null) await this.sleep(Math.max(0, min - (Date.now() - at)));
      }
      if (e.type === "interrupt") await this.sleep(MOMENTS.beforeDialog);
    }
    await this.handle(e);
    if (this.opts.momentDwell) await this.sleep(momentAfter(e));
  }

  private async handle(e: RunEvent): Promise<void> {
    switch (e.type) {
      case "run.started":
        return this.started(e);
      case "log.cmd":
        return this.typeCmd(e.data.text);
      case "plan.ready":
      case "subtask.started":
      case "answer.delta":
      case "error":
        return;
      case "strip.set": {
        const d = e.data;
        this.up((r) => {
          let x = r.strip === d.variant ? r : R.initStrip(r, d.variant, true);
          x = R.setSig(R.setLabel(x, d.subtask.label), d.sig);
          return d.sig ? x : R.setTitle(x, d.title ?? COPY.bench.noTools);
        });
        return;
      }
      case "node.started": {
        const { step, label } = e.data;
        this.startedAt.set(step, Date.now());
        this.up((r) => {
          const x = R.setNode(r, step, "active", label);
          return step === "forger" && (r.attempts?.length ?? 0) > 0 ? R.patch(x, { retrying: true }) : x;
        });
        return;
      }
      case "node.finished": {
        const { step, status, label } = e.data;
        this.up((r) => {
          const x = R.setNode(r, step, status, label);
          return step === "forger" && r.retrying ? R.patch(x, { retrying: false }) : x;
        });
        return;
      }
      case "link.flow":
        this.up((r) => R.flow(r, e.data.from, e.data.to));
        return;
      case "caption":
        this.up((r) => R.setCaption(r, e.data.html));
        return;
      case "log.line": {
        const { label, text, tone, caret } = e.data;
        this.up((r) => {
          const x = R.log(r, label, text, tone === "plain" || tone === "sub" ? "" : tone, { caret, sub: tone === "sub" });
          return label === "execute" && text === "running" && x.call ? R.patchCall(x, { pending: RUNNING_PENDING }) : x;
        });
        return;
      }
      case "log.pop":
        this.up(R.logPop);
        return;
      case "log.status":
        this.up((r) => R.logTone(R.logStatus(r, e.data.text, e.data.gold), e.data.tone));
        return;
      case "talos.status":
        this.talos((m) => ({ ...m, status: e.data.text }));
        return;
      case "forge.code":
        return this.forgeCode(e);
      case "forge.tests":
        return this.forgeTests(e);
      case "forge.attempt": {
        const { attempt, ok, detail } = e.data;
        this.up((r) => ({ ...r, attempts: (r.attempts ?? []).map((a) => (a.n === attempt ? { ...a, ok, detail } : a)) }));
        return;
      }
      case "forge.smoke": {
        const { call, result } = e.data;
        this.up((r) => ({ ...r, smoke: { call, result: null } }));
        await this.sleep(PACE.smokeRun);
        if (this.aborted) return;
        this.up((r) => ({ ...r, smoke: { call, result } }));
        return;
      }
      case "vault.saved": {
        const tool = V.fromVaultEntry(e.data.tool, true);
        if (this.quiet) {
          this.up((r) => R.setBanner(r, { kind: "saved", name: tool.name, sub: e.data.sub }));
          return;
        }
        this.stores.vault.update((v) => ({ ...v, tools: V.addTool(v.tools, tool) }));
        this.stores.ui.set({ selected: tool.name, badge: true });
        this.up((r) => R.setBanner(r, { kind: "saved", name: tool.name, sub: e.data.sub }));
        return;
      }
      case "vault.failure":
        return this.failure(e);
      case "call.args":
        return this.callArgs(e);
      case "call.result":
        return this.callResult(e);
      case "call.error":
        this.up((r) => R.patchCall(r, { error: e.data.error, when: whenText(e.data.when, e.ts) }));
        return;
      case "interrupt": {
        const d = e.data;
        const runId = this.opts.runId;
        this.up((r) => R.patch(r, { status: "waiting" }));
        // A caught-up interrupt's dialog comes from GET /api/runs/{id}.pending (the Workbench's reattach).
        // After Stop the run is being stopped on the server, so its interrupt asks nothing (stopRun, line 1485).
        // This assumes the /stop request reaches the server: if it fails, the run stays paused with no dialog
        // (the re-attach fallback is gated on Stop too), and Stop is the way out. There's no error copy (ruling 10).
        if (this.opts.replay || this.catching || this.aborted) return;
        this.stores.ui.set({
          dialog:
            d.kind === "confirm_exec"
              ? { kind: "approval", runId, tool: d.payload.tool, code: d.payload.preview }
              : { kind: "key", runId, toolName: d.payload.tool_name, envVar: d.payload.env_var, service: d.payload.service },
        });
        return;
      }
      case "interrupt.resolved": {
        this.up((r) => R.patch(r, { status: "running" }));
        const dlg = this.stores.ui.get().dialog;
        if (dlg && "runId" in dlg && dlg.runId === this.opts.runId) this.stores.ui.set({ dialog: null });
        return;
      }
      case "answer.done":
        return this.answer(e);
      case "run.finished":
        return this.finished(e);
    }
  }

  private async started(e: EventOf<"run.started">): Promise<void> {
    const { query, n } = e.data;
    const sid = this.opts.sessionId;
    const names = this.stores.vault.get().tools.map((t) => t.name);
    const run = R.initStrip(R.newRun({ id: this.opts.runId, n, query, sessionId: sid }), provisionalVariant(query, names));
    this.stores.runs.update((s) => ({ byId: { ...s.byId, [run.id]: run } }));
    if (this.opts.replay) return;
    this.stores.session.update((s) => M.addTalos(M.attachRun(M.addYou(s, sid, query, `you-${n}`), sid, run.id), sid, n, `talos-${n}`, COPY.convo.thinking));
    // submit() (lines 1455-1466) scrolls the conversation in addYou/addTalos, which lays out the page while
    // the previous run is still on the bench, and only then draws the new run. Let React commit the
    // messages (and run that scroll) first: its forced layout must not see the new bench before log.cmd's
    // command row, or `.views` (below 820 px) clamps against a shorter page than the reference ever has.
    await Promise.resolve();
    if (this.gone) return;
    this.stores.ui.set({ currentRunId: run.id, viewingRunId: run.id, busy: true });
  }

  private async typeCmd(text: string): Promise<void> {
    this.up((r) => R.startCmd(r, text));
    if (!this.fast) {
      const { step } = typingPlan(text.length);
      let shown = 0;
      while (shown < text.length) {
        shown = Math.min(text.length, shown + step);
        const s = shown;
        this.up((r) => R.typeCmd(r, s));
        await this.sleep(PACE.typeStep);
        if (this.aborted) return;
      }
    }
    this.up(R.endCmd);
  }

  private async forgeCode(e: EventOf<"forge.code">): Promise<void> {
    const d = e.data;
    if (d.tests != null) this.testsCount = d.tests;
    const count = this.testsCount;
    const first = d.attempt === 1 || !this.run().code;
    this.up((r) => {
      const attempts = [...(r.attempts ?? []), { n: d.attempt, ok: null, detail: "" }];
      const tabs: Tab[] = r.tabs.some((t) => t.id === "code")
        ? r.tabs.map((t) => (t.id === "attempts" ? { ...t, count: attempts.length } : t.id === "tests" && count != null ? { ...t, count } : t))
        : [
            { id: "code", label: COPY.bench.tabs.code },
            { id: "tests", label: COPY.bench.tabs.tests, count },
            { id: "attempts", label: COPY.bench.tabs.attempts, count: attempts.length },
          ];
      const cap = fill(COPY.code.cap, { n: d.lines.length, a: d.attempt });
      const next: Run = first
        ? { ...r, attempts, tabs, code: { file: d.file, cap, lines: d.lines, shown: 0, changed: null, note: "" }, codeScroll: "bottom" }
        : { ...r, attempts, tabs, code: { ...r.code!, lines: d.lines, cap, changed: d.changed, flash: true, note: d.note ?? "", shown: d.lines.length }, codeScroll: d.changed };
      return R.setTab(next, "code");
    });
    if (!first) return;
    if (this.fast) {
      this.up((r) => R.patchCode(r, { shown: d.lines.length }));
      return;
    }
    const { perTick } = revealPlan(d.lines.length);
    let shown = 0;
    while (shown < d.lines.length) {
      shown = Math.min(d.lines.length, shown + perTick);
      const s = shown;
      this.up((r) => R.patchCode(r, { shown: s }));
      await this.sleep(PACE.revealTick);
      if (this.aborted) return;
    }
  }

  private async forgeTests(e: EventOf<"forge.tests">): Promise<void> {
    const d = e.data;
    this.testsCount = d.results.length;
    this.up((r) =>
      R.setTab({ ...R.patchCode(r, { flash: false }), tests: { attempt: d.attempt, list: d.results.map((x) => ({ name: x.name, state: "waiting" as const, why: "" })) } }, "tests"),
    );
    const set = (i: number, state: "running" | "passed" | "failed", why = "") =>
      this.up((r) => ({ ...r, tests: { ...r.tests!, list: r.tests!.list.map((x, j) => (j === i ? { ...x, state, why } : x)) } }));
    for (let i = 0; i < d.results.length; i++) {
      const res = d.results[i]!;
      const final = res.passed ? "passed" : "failed";
      if (this.fast) {
        if (!this.aborted) set(i, final, res.passed ? "" : (res.why ?? ""));
        continue;
      }
      set(i, "running");
      await this.sleep(PACE.testRun);
      if (this.aborted) return;
      set(i, final, res.passed ? "" : (res.why ?? ""));
      await this.sleep(PACE.testGap);
      if (this.aborted) return;
    }
  }

  private failure(e: EventOf<"vault.failure">): void {
    const { tool, streak, pruned, error } = e.data;
    const now = nowIso();
    if (!this.quiet) this.stores.vault.update((v) => ({ ...v, tools: pruned ? V.removeTool(v.tools, tool) : V.recordFailure(v.tools, tool, streak, error, now) }));
    const r0 = this.run();
    // The retry button (lines 1717–1718, 1731): a word where the tool wanted a number.
    let retry: { q: string; label: string } | null = null;
    const bad = r0.call?.args.find((a) => a[2]);
    if (bad) {
      const [name, repr] = bad;
      const word = repr.replace(/^"|"$/g, "");
      const digit = NUM_WORDS[word.toLowerCase()];
      if (digit != null) retry = { q: r0.query.replace(new RegExp(`${name}(\\s+of)?\\s+${word}`, "i"), `${name} ${digit}`), label: retryLabel(name, digit) };
    }
    this.up((r) => {
      let x = R.patch(R.patchCall(r, { health: { streak: Math.min(streak, PRUNE_AT), tool, text: healthText(tool, pruned), retry } }), { failed: true });
      if (pruned) x = R.setBanner(x, { kind: "removed", name: tool, sub: removedSub(tool) });
      return x;
    });
  }

  private async callArgs(e: EventOf<"call.args">): Promise<void> {
    const d = e.data;
    const r0 = this.run();
    this.callTool = d.tool;
    const exec = d.tool === "python_exec" || d.tool === "shell_exec";
    const args: CallArg[] = d.args.map(([k, v, bad]) => [k, v, bad]);
    let tabs = r0.tabs;
    let code = r0.code;
    if (r0.strip === "forge") tabs = [...r0.tabs.filter((t) => t.id !== "call" && t.id !== "log"), { id: "call", label: COPY.bench.tabs.call }];
    else if (r0.strip === "vault") {
      tabs = [{ id: "call", label: COPY.bench.tabs.call }, { id: "code", label: COPY.bench.tabs.code }, { id: "history", label: COPY.bench.tabs.history }];
      const lines = await this.source(d.tool);
      if (lines) code = { file: `${d.tool}.py`, cap: d.code_cap ?? fill(COPY.code.lines, { n: lines.length }), lines, shown: lines.length };
    } else tabs = [{ id: "call", label: COPY.bench.tabs.call }];
    const call: CallState = {
      args,
      shownArgs: d.caption || this.fast ? undefined : 0,
      noArgs: args.length === 0 ? true : undefined,
      argsCap: d.caption ?? undefined,
      resultCap: r0.strip === "primitive" ? COPY.call.output : undefined,
      pending: exec ? COPY.call.awaitingApproval : undefined,
    };
    this.up((r) =>
      R.setTab(
        { ...r, tabs, code, call, toolName: r.strip === "vault" ? d.tool : r.toolName, toolUsed: r.strip === "primitive" ? r.toolUsed : d.tool },
        "call",
      ),
    );
    if (d.caption || this.fast) return;
    const each = args.length === 1 ? PACE.argSingle : PACE.argEach;
    for (let i = 1; i <= args.length; i++) {
      await this.sleep(each);
      if (this.aborted) return;
      this.up((r) => R.patchCall(r, { shownArgs: i }));
    }
  }

  private async source(tool: string): Promise<string[] | null> {
    const cached = this.stores.vault.get().sources[tool];
    if (cached !== undefined) return cached;
    const lines = (await this.opts.source?.(tool)) ?? null;
    this.stores.vault.update((v) => ({ ...v, sources: { ...v.sources, [tool]: lines } }));
    return lines;
  }

  private callResult(e: EventOf<"call.result">): void {
    const { repr, type, small } = e.data;
    const r0 = this.run();
    const tool = this.callTool;
    let record: CallState["record"];
    if (tool && r0.strip !== "primitive") {
      // The Uses shown for a past call are today's count: the only one the API has.
      if (!this.quiet) this.stores.vault.update((v) => ({ ...v, tools: V.recordUse(v.tools, tool, nowIso()) }));
      const t = V.findTool(this.stores.vault.get().tools, tool);
      if (t && r0.strip === "vault" && !small) {
        record = { forged: fmtTime(t.created), uses: fill(COPY.call.recordUses, { n: t.uses }), fails: t.fails ? fill(COPY.call.recordFails, { n: t.fails }) : COPY.call.recordNone };
      }
    }
    this.up((r) => R.patchCall(r, { result: repr, resultType: type || undefined, smallResult: small || undefined, record }));
  }

  private async answer(e: EventOf<"answer.done">): Promise<void> {
    const d = e.data;
    const total = wrapWordsHtml(d.html, 0).count;
    const instant = this.fast || reducedMotion();
    this.talos((m) => ({ ...m, status: null, html: d.html, wrap: true, wordsOn: instant ? total : 0 }));
    if (!instant) {
      for (let i = 1; i <= total; i++) {
        this.talos((m) => ({ ...m, wordsOn: i }));
        await this.sleep(PACE.word);
        if (this.aborted) break;
      }
    }
    // A stopped say (line 967): every word on, and no note, chips or live text, since say() never got past its wait.
    if (this.aborted) {
      this.talos((m) => ({ ...m, wordsOn: total }));
      return;
    }
    this.talos((m) => ({ ...m, note: d.note, chips: d.chips, suggest: !!d.suggest }));
    if (!this.opts.replay) this.stores.ui.set({ live: COPY.convo.livePrefix + textOf(d.html) });
  }

  private finished(e: EventOf<"run.finished">): void {
    const d = e.data;
    // The run's finally (line 1482) calls renderSide(run), which redraws the Log tab and drops `fresh`.
    this.up((r) => ({
      ...(r.tab === "log" ? R.clearFresh(r) : r),
      status: r.status === "running" || r.status === "waiting" ? d.status : r.status,
      summary: d.summary,
      summaryGold: d.summary_gold,
      forged: r.forged || d.forged.length > 0,
      retrying: false,
    }));
    if (this.opts.replay) return;
    const stopped = d.status === "stopped";
    this.talos((m) => ({
      ...m,
      // stop() (line 967) turns every word on.
      ...(stopped ? { status: null, wordsOn: wordCount(m.html), stopNote: COPY.convo.stopped } : {}),
      runLink: true,
    }));
    // The new link is followed by markRunLinks() (line 1481), which marks the run on the bench.
    const viewing = this.stores.ui.get().viewingRunId;
    this.stores.ui.set({ busy: false, markedRunN: viewing ? (this.stores.runs.get().byId[viewing]?.n ?? null) : null });
  }
}
