/* The run event contract (overview spec §4) and the stage 2 API shapes. Normative for live and demo. */

export type StepKey = "planner" | "forger" | "tester" | "human" | "learn" | "executor" | "answer" | "vault" | "primitive" | "skip";
export type Variant = "forge" | "vault" | "primitive" | "chat";

export interface Sig {
  name: string;
  args: string;
  ret: string;
}

export interface VaultEntry {
  name: string;
  args: string;
  ret: string;
  signature: string;
  description: string;
  keywords: string[];
  uses: number;
  failures: number;
  streak: number;
  /** Stage 2 sends null when the manifest entry has no creation time. */
  created_at: string | null;
  last_used: string | null;
  last_failure: string | null;
  last_failed_at: string | null;
  web: boolean;
  file: string;
}

export interface EventData {
  "run.started": { session_id: string; query: string; n: number };
  "log.cmd": { text: string };
  "plan.ready": {
    subtasks: { id: number; action: string; needs: "primitive" | "vault" | "forge"; tool_hint: string | null; depends_on: number[] }[];
    verdict: string;
  };
  "strip.set": {
    variant: Variant;
    subtask: { index: number; total: number; label: string };
    sig: Sig | null;
    /** Demo transport only (ruling 2): the bench heading when there's no signature. */
    title?: string;
  };
  "subtask.started": { index: number; total: number };
  "node.started": { step: StepKey; label?: string };
  /** Stop sends status "stopped" for every step that was active. */
  "node.finished": { step: StepKey; status: "done" | "forge" | "skip" | "fail" | "answer" | "stopped"; label?: string };
  "link.flow": { from: StepKey; to: StepKey };
  caption: { html: string };
  "log.line": { label: string; text: string; tone: "plain" | "g" | "w" | "sub"; caret?: boolean };
  "log.pop": Record<string, never>;
  "log.status": { text: string; gold: boolean; tone: "" | "warm" | "alert" };
  "talos.status": { text: string };
  "forge.code": {
    tool: string;
    attempt: number;
    file: string;
    lines: string[];
    changed: number | null;
    note: string | null;
    /** Ruling 1: how many tests the Forger wrote for this attempt (stage 2 sends it too). */
    tests?: number;
  };
  "forge.tests": { tool: string; attempt: number; results: { name: string; passed: boolean; why: string | null }[] };
  "forge.attempt": { attempt: number; ok: boolean; detail: string };
  "forge.smoke": { call: string; result: string | null; passed: boolean };
  "vault.saved": { tool: VaultEntry; sub: string };
  "vault.failure": { tool: string; streak: number; pruned: boolean; error: string };
  "call.args": {
    tool: string;
    args: [string, string, boolean][];
    caption: string | null;
    /** Demo transport only (ruling 10): the reused tool's Code tab caption, when the reference hard-codes one. */
    code_cap?: string;
  };
  "call.result": { repr: string; type: string; small: boolean };
  /** `when` is a code from stage 2 (e.g. "run", "declined"), not display text. */
  "call.error": { error: string; when: string };
  interrupt:
    | { kind: "confirm_exec"; payload: { tool: "python_exec" | "shell_exec"; preview: string } }
    | { kind: "missing_api_key"; payload: { env_var: string; tool_name: string; service: string } };
  "interrupt.resolved": { kind: "confirm_exec" | "missing_api_key"; decision: "approve" | "decline" | "save" | "skip" };
  "answer.delta": { text: string };
  "answer.done": {
    html: string;
    note: string | null;
    chips: { kind: "forged" | "reused" | "failed"; text: string }[];
    /** Demo transport only (ruling 2): show the suggestion buttons under the answer. */
    suggest?: boolean;
  };
  "run.finished": {
    status: "done" | "failed" | "stopped" | "declined";
    summary: string;
    summary_gold: boolean;
    forged: string[];
    used: string[];
  };
  error: { message: string };
}

export type EventType = keyof EventData;
export type RunEvent = { [T in EventType]: { run_id: string; seq: number; ts: string; type: T; data: EventData[T] } }[EventType];
export type EventOf<T extends EventType> = Extract<RunEvent, { type: T }>;

export type ResumeDecision = { decision: "approve" } | { decision: "decline" } | { decision: "save"; value: string } | { decision: "skip" };

/** Applies one event. Resolves when the event is on screen and its animation is done (the demo waits on it). */
export type EventSink = (event: RunEvent) => Promise<void>;

export interface StartedRun {
  runId: string;
  n: number;
  /** Set when the server (or the demo) renamed the session on its first run. */
  sessionName: string | null;
}

/** How runs reach the UI. Demo: DemoTransport (part A). Live: LiveTransport (part B). */
export interface Transport {
  startRun(sessionId: string, text: string): Promise<StartedRun>;
  /** Streams the run's events with seq > after into `sink`, in order. Returns an unsubscribe function. */
  subscribe(runId: string, sink: EventSink, after?: number): () => void;
  resume(runId: string, decision: ResumeDecision): Promise<void>;
  stop(runId: string): Promise<void>;
}

/* Stage 2 API shapes (spec 02 §4), for part B's live data source. */
export interface ApiSession {
  id: string;
  name: string;
  number: number;
  created_at: string;
  updated_at: string;
}
export interface ApiMessage {
  id: string;
  role: "user" | "assistant";
  html: string;
  note: string | null;
  chips: { kind: "forged" | "reused" | "failed"; text: string }[];
  run_id: string | null;
  created_at: string;
}
export interface ApiRunSummary {
  id: string;
  n: number;
  query: string;
  status: "running" | "waiting" | "done" | "failed" | "stopped" | "declined";
  summary: string | null;
  summary_gold: boolean;
  forged: string[];
  used: string[];
  /** Stage 2 sends a flag: whether a tool call failed in this run. */
  failed: boolean;
  started_at: string;
  finished_at: string | null;
}
export type ApiVaultEntry = VaultEntry;
export interface ApiSettings {
  model: string;
  ask_before_exec: boolean;
  forge_retries: number;
  test_timeout_s: number;
  llm_timeout_s: number;
  prune_after: number;
  keys: { name: string; set: boolean; required: boolean; description: string }[];
}
/** Every stage 2 error body. A 409 `run_active` also names the active run and its session. */
export interface ApiError {
  error: { code: string; message: string; run_id?: string; session_id?: string };
}
