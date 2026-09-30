import { COPY } from "../lib/copy";
import type { Sig, StepKey, Variant } from "../transport/types";
import type { Banner, CallState, CodeState, NodeState, Run, TabId } from "./types";

/** Line 992. [key, label, calls a model]. */
export const STRIPS: Record<Variant, [StepKey, string, boolean?][]> = {
  forge: [["planner", "Planner", true], ["forger", "Forger", true], ["tester", "Tester"], ["human", "Human check"], ["learn", "Learn"], ["executor", "Executor", true], ["answer", "Answer"]],
  vault: [["planner", "Planner", true], ["vault", "Vault tool"], ["skip", "Forge sub-graph skipped"], ["executor", "Executor", true], ["answer", "Answer"]],
  primitive: [["planner", "Planner", true], ["primitive", "Primitive"], ["executor", "Executor", true], ["answer", "Answer"]],
  chat: [["planner", "Planner", true], ["answer", "Answer"]],
};
export const DONE_STATES: NodeState[] = ["done", "forge", "skip", "answer", "fail", "stopped"];

let key = 0;
/** Unique React keys for log lines and messages. */
export const nextKey = (): number => ++key;

/** newRun() (line 1446) plus the label submit() sets (line 1465). */
export function newRun(o: { id: string; n: number; query: string; sessionId: string }): Run {
  return { ...o, tab: "log", title: COPY.bench.reading, label: COPY.bench.planning, status: "running", log: [], nodes: {}, links: {}, tabs: [], strip: "forge" };
}

/** initStrip() (line 1000). With `keep`, steps present in both strips keep their state (ruling 3). */
export function initStrip(run: Run, variant: Variant, keep = false): Run {
  const nodes: Run["nodes"] = {};
  for (const [k, label, llm] of STRIPS[variant]) {
    const prev = keep ? run.nodes[k] : undefined;
    nodes[k] = prev ? { ...prev } : { label, llm: !!llm, state: "pending" };
  }
  if (variant === "vault" && nodes.skip && nodes.skip.state === "pending") nodes.skip = { ...nodes.skip, state: "skip" };
  return { ...run, strip: variant, nodes, links: keep ? { ...run.links } : {} };
}

/** setNode() (line 1020). */
export function setNode(run: Run, k: StepKey, state: NodeState, label?: string): Run {
  const n = run.nodes[k];
  if (!n) return run;
  return { ...run, nodes: { ...run.nodes, [k]: { ...n, state, label: label || n.label } } };
}

/** flow() (line 1031): lights the link and restarts its packet. */
export function flow(run: Run, from: StepKey, to: StepKey): Run {
  const lk = `${from}-${to}`;
  const flows = run.flows ?? {};
  return { ...run, links: { ...run.links, [lk]: true }, flows: { ...flows, [lk]: (flows[lk] ?? 0) + 1 } };
}

/** log() (line 1280): clears every caret, marks only the new line fresh. */
export function log(run: Run, label: string, text: string, tone = "", opts: { caret?: boolean; sub?: boolean } = {}): Run {
  const lines = run.log.map((l) => (l.kind === "cmd" ? l : { ...l, caret: false, fresh: false }));
  lines.push({ kind: opts.sub ? "sub" : "ln", label, text, tone, caret: !!opts.caret, fresh: true, key: nextKey() });
  return { ...run, log: lines };
}
export const logPop = (run: Run): Run => ({ ...run, log: run.log.slice(0, -1) });

/**
 * The reference's log() sets `fresh` back to false right after drawing the line (line 1285), so the
 * class stays on screen only until the log is next redrawn (log(), typeCmd(), renderPanel on the Log tab).
 */
export const clearFresh = (run: Run): Run =>
  run.log.some((l) => l.kind !== "cmd" && l.fresh) ? { ...run, log: run.log.map((l) => (l.kind !== "cmd" && l.fresh ? { ...l, fresh: false } : l)) } : run;

/** typeCmd() (line 1296), in three steps so the player can pace it. Each step redraws the log. */
export const startCmd = (run: Run, text: string): Run => {
  const r = clearFresh(run);
  return { ...r, log: [...r.log, { kind: "cmd", text, shown: 0, typing: true, key: nextKey() }] };
};
export function typeCmd(run: Run, shown: number): Run {
  const log = clearFresh(run).log.slice();
  const i = log.length - 1;
  const last = log[i];
  if (last?.kind === "cmd") log[i] = { ...last, shown };
  return { ...run, log };
}
export function endCmd(run: Run): Run {
  const log = clearFresh(run).log.map((l) => (l.kind === "cmd" && l.typing ? { ...l, typing: false, shown: null } : l));
  return { ...run, log };
}

/** setTab() (line 1135); showing the Log tab redraws it, which drops `fresh`. */
export const setTab = (run: Run, tab: TabId): Run => ({ ...(tab === "log" ? clearFresh(run) : run), tab });
export const setCaption = (run: Run, caption: string): Run => ({ ...run, caption });
export const setLabel = (run: Run, label: string): Run => ({ ...run, label });
export const setSig = (run: Run, sig: Sig | null): Run => ({ ...run, sig });
export const setTitle = (run: Run, title: string): Run => ({ ...run, title });
export const setBanner = (run: Run, banner: Banner | null): Run => ({ ...run, banner });
export const logStatus = (run: Run, text: string, gold = false): Run => ({ ...run, logStatus: text, logStatusGold: gold });
export const logTone = (run: Run, tone: "" | "warm" | "alert"): Run => ({ ...run, logTone: tone });
export const patch = (run: Run, p: Partial<Run>): Run => ({ ...run, ...p });
export const patchCall = (run: Run, p: Partial<CallState>): Run => ({ ...run, call: { args: [], ...run.call, ...p } });
export const patchCode = (run: Run, p: Partial<CodeState>): Run => (run.code ? { ...run, code: { ...run.code, ...p } } : run);

/** updateRail()'s width (line 1051). */
export function railPercent(run: Run): number {
  const all = Object.values(run.nodes).filter((n) => !!n);
  if (!all.length) return 0;
  const d = all.filter((n) => DONE_STATES.includes(n.state)).length + all.filter((n) => n.state === "active").length * 0.5;
  return Math.round((d / all.length) * 100);
}
