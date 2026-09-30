import type { Sig, StepKey, Variant } from "../transport/types";

/* The reference's run object (lines 1446–1449 and every renderer), plus `id` and `sessionId`. */
export type NodeState = "pending" | "active" | "done" | "forge" | "skip" | "fail" | "answer" | "stopped";
export interface StripNode {
  label: string;
  llm: boolean;
  state: NodeState;
}
export type TabId = "code" | "tests" | "attempts" | "call" | "history" | "answer" | "log";
export interface Tab {
  id: TabId;
  label: string;
  count?: number;
}
export interface CmdLine {
  kind: "cmd";
  text: string;
  shown?: number | null;
  typing?: boolean;
  key?: number;
}
export interface LogLn {
  kind: "ln" | "sub";
  label: string;
  text: string;
  tone?: string;
  caret?: boolean;
  fresh?: boolean;
  key?: number;
}
export type LogLine = CmdLine | LogLn;
export interface CodeState {
  file: string;
  cap: string;
  lines: string[];
  shown: number;
  changed?: number | null;
  flash?: boolean;
  note?: string;
}
export interface TestItem {
  name: string;
  state: "waiting" | "running" | "passed" | "failed";
  why: string;
  drawn?: boolean;
  flashed?: boolean;
}
export interface TestsState {
  attempt: number;
  list: TestItem[];
}
export interface Attempt {
  n: number;
  ok: boolean | null;
  detail: string;
}
export interface Smoke {
  call: string;
  result: string | null;
}
export type CallArg = [string, string] | [string, string, boolean];
export interface Health {
  streak: number;
  tool: string;
  text: string;
  retry: { q: string; label: string } | null;
}
export interface CallState {
  args: CallArg[];
  shownArgs?: number | null;
  noArgs?: boolean;
  argsCap?: string;
  resultCap?: string;
  result?: string | null;
  resultType?: string;
  smallResult?: boolean;
  pending?: string;
  error?: string;
  when?: string;
  record?: { forged: string; uses: string; fails: string };
  health?: Health;
}
export interface Banner {
  kind: "saved" | "removed";
  name: string;
  sub: string;
}
export type RunStatus = "running" | "waiting" | "done" | "failed" | "stopped" | "declined";
export interface Run {
  id: string;
  sessionId: string;
  n: number;
  query: string;
  status: RunStatus;
  tab: TabId;
  tabs: Tab[];
  strip: Variant;
  nodes: Partial<Record<StepKey, StripNode>>;
  links: Record<string, boolean>;
  title?: string;
  label?: string;
  sig?: Sig | null;
  caption?: string;
  code?: CodeState;
  codeScroll?: "bottom" | number | null;
  tests?: TestsState;
  attempts?: Attempt[];
  smoke?: Smoke | null;
  call?: CallState;
  banner?: Banner | null;
  log: LogLine[];
  logStatus?: string;
  logStatusGold?: boolean;
  logTone?: "" | "warm" | "alert";
  summary?: string;
  summaryGold?: boolean;
  toolName?: string;
  toolUsed?: string;
  forged?: boolean;
  failed?: boolean;
  seeded?: boolean;
  answer?: string;
  /** The Forger–Tester link's backwards packet (retrying(), line 1040). */
  retrying?: boolean;
  /** How many times each link has flowed; a change restarts its packet animation. */
  flows?: Record<string, number>;
}

export interface Chip {
  kind: "forged" | "reused" | "failed";
  text: string;
}
export interface YouMessage {
  kind: "you";
  key: string;
  text: string;
  past: boolean;
}
export interface TalosMessage {
  kind: "talos";
  key: string;
  runN: number;
  /** The orbit spinner's text while working; null once the answer (or stop note) is in. */
  status: string | null;
  html: string | null;
  /** Live answers are word-wrapped for the fade-in; seeded transcripts are not (sessionHtml, line 2229). */
  wrap: boolean;
  wordsOn: number;
  note: string | null;
  chips: Chip[];
  suggest: boolean;
  stopNote: string | null;
  runLink: boolean;
  past: boolean;
}
export type Message = YouMessage | TalosMessage;

export interface SessionRec {
  id: string;
  name: string;
  started: string;
  live: boolean;
  runIds: string[];
  messages: Message[];
}

export interface VaultTool {
  name: string;
  args: string;
  ret: string;
  desc: string;
  kw: string[];
  uses: number;
  fails: number;
  streak: number;
  created: string;
  last: string;
  lastFail: string;
  lastFailAt: string;
  web: boolean;
  fresh: boolean;
}

export type View = "workbench" | "vault" | "sessions" | "settings";
export type DialogReq =
  | { kind: "approval"; runId: string; tool: "python_exec" | "shell_exec"; code: string }
  | { kind: "key"; runId: string; toolName: string; envVar: string; service: string }
  | { kind: "reader"; name: string; lines: string[] };

export interface RunsState {
  byId: Record<string, Run>;
}
export interface SessionState {
  sessions: SessionRec[];
  curId: string;
  viewId: string | null;
  count: number;
}
export interface VaultState {
  tools: VaultTool[];
  /** Tool name → source lines (null: not available). Filled lazily from the data source. */
  sources: Record<string, string[] | null>;
}
export interface SettingsState {
  askExec: boolean;
  /** Demo: keys pasted into the key dialog, kept in memory. Live: names of keys that are set. */
  env: Record<string, string>;
  model: string;
}
export interface UiState {
  view: View;
  /** Bumped when the view changes, to restart `.view.enter`. */
  viewEnter: number;
  dialog: DialogReq | null;
  busy: boolean;
  currentRunId: string | null;
  viewingRunId: string | null;
  selected: string | null;
  filter: "all" | "web" | "failed";
  query: string;
  /** The vault table's rows rise in (renderVault({ stagger: true }), line 1973). */
  stagger: boolean;
  /** Bumped on every renderVault(): rows are keyed by it, so they're re-created as in the reference. */
  vaultRender: number;
  popOpen: boolean;
  speed: number;
  badge: boolean;
  booted: boolean;
  /** The polite live region (#live). */
  live: string;
  /** Tool name whose Remove button is in its confirm step. */
  confirmRemove: string | null;
  /** The composer's text. */
  draft: string;
  /** Bumped whenever the reference would call renderBench(): remounts the bench (clears `flow`, resets the tab indicator). */
  benchKey: number;
  /** The next session-title change decodes into place (setTitle(name, true)). */
  titleAnimate: boolean;
  /** Bumped on every setTitle(name, true): the title decodes again even when the name is unchanged (openSession, backToNow, newSession). */
  titleSeq: number;
  /**
   * The run whose "View this run" link has aria-current="true". The reference sets it only in
   * markRunLinks() (run end, View this run, openSession, backToNow), so it lags S.viewing while a new
   * run goes: the previous run's link stays marked (line 2232).
   */
  markedRunN: number | null;
}
