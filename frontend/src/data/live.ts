import { sanitize } from "../lib/sanitize";
import { newRun } from "../store/runOps";
import type { Message, Run, SessionRec, SettingsState, VaultTool } from "../store/types";
import { fromVaultEntry } from "../store/vaultOps";
import { ApiError, type Api } from "../transport/api";
import { normalise } from "../transport/live";
import type { ApiRun, ApiRunSummary, ApiSessionDetail, ApiSessionSummary, ApiSettings, RunEvent } from "../transport/types";
import type { DataSource } from "./source";

/** A past session as the stores hold it, plus its running or waiting run (Task 3 reattaches to it). */
export interface LoadedSession {
  rec: SessionRec;
  runs: Run[];
  active: ApiRunSummary | null;
}

const ACTIVE = new Set<ApiRunSummary["status"]>(["running", "waiting"]);

/**
 * A tool's source → the reader's lines. One trailing newline is dropped, so a file's lines match the
 * reference's getSource() (a <script> body with no trailing newline) and the "N lines" counts agree.
 */
export function sourceLines(source: string): string[] {
  return (source.endsWith("\n") ? source.slice(0, -1) : source).split("\n");
}

/** GET /api/settings → the store. `env` holds "set" for each key that is set: the API never sends a value. */
export function toSettings(s: ApiSettings): SettingsState {
  const env: Record<string, string> = {};
  for (const k of s.keys) if (k.set) env[k.name] = "set";
  return {
    askExec: s.ask_before_exec,
    env,
    model: s.model,
    live: {
      keys: s.keys.map((k) => ({ ...k })),
      forgeRetries: s.forge_retries,
      testTimeoutS: s.test_timeout_s,
      llmTimeoutS: s.llm_timeout_s,
      pruneAfter: s.prune_after,
    },
  };
}

/** The server stores user text as html.escape(text); the component escapes it again, so unescape here. */
function unescapeHtml(html: string): string {
  const t = document.createElement("textarea");
  t.innerHTML = html;
  return t.value;
}

/**
 * A session's stored messages → the transcript. Messages of a running or waiting run are dropped: the
 * reattached player re-adds You and Talos from run.started (Task 3). Keys use the message id, so they
 * never collide with the player's `you-${n}` / `talos-${n}`.
 */
export function toMessages(detail: ApiSessionDetail): Message[] {
  const byId = new Map(detail.runs.map((r) => [r.id, r]));
  const out: Message[] = [];
  for (const m of detail.messages) {
    const r = m.run_id == null ? undefined : byId.get(m.run_id);
    if (r && ACTIVE.has(r.status)) continue;
    if (m.role === "user") {
      out.push({ kind: "you", key: `you-${m.id}`, text: unescapeHtml(m.html), past: false });
      continue;
    }
    /* A stopped run's message is empty HTML with the stop note in `note` (plain text: rendered as text). */
    const stopped = m.html === "" && m.note != null;
    out.push({
      kind: "talos",
      key: `talos-${m.id}`,
      runN: r?.n ?? 0,
      status: null,
      html: stopped ? null : sanitize(m.html),
      wrap: false,
      wordsOn: 0,
      note: stopped || m.note == null ? null : sanitize(m.note),
      chips: m.chips.map((c) => ({ ...c })),
      suggest: false,
      stopNote: stopped ? m.note : null,
      runLink: r != null,
      past: false,
    });
  }
  return out;
}

/** A run summary → enough of a Run for the Sessions cards and the Earlier list. The full run is replayed on demand. */
export function stubRun(sessionId: string, r: ApiRunSummary): Run {
  return {
    ...newRun({ id: r.id, n: r.n, query: r.query, sessionId }),
    status: r.status,
    summary: r.summary ?? "",
    summaryGold: r.summary_gold,
    forged: r.forged.length > 0,
    toolUsed: r.forged[0] ?? r.used[0],
    failed: r.failed,
    strip: "chat",
    nodes: {},
  };
}

/** Live mode's data source: stage 2's REST API mapped to the stores' shapes. */
export class LiveDataSource implements DataSource {
  private currentStarted: string | null = null;

  constructor(private readonly api: Api) {}

  /** The current session's created_at: tools created at or after it are "New this session" (spec 04 §5). */
  setCurrentStarted(iso: string | null): void {
    this.currentStarted = iso;
  }

  private isFresh(created: string | null): boolean {
    return !!created && !!this.currentStarted && Date.parse(created) >= Date.parse(this.currentStarted);
  }

  async vault(): Promise<VaultTool[]> {
    const { tools } = await this.api.vault();
    return tools.map((e) => fromVaultEntry({ ...e, created_at: e.created_at ?? "" }, this.isFresh(e.created_at)));
  }

  async toolSource(name: string): Promise<string[] | null> {
    try {
      const { source } = await this.api.tool(name);
      return source == null ? null : sourceLines(source);
    } catch (err) {
      /* The tool was removed meanwhile. */
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  }

  async settings(): Promise<SettingsState> {
    return toSettings(await this.api.settings());
  }

  async setAskBeforeExec(on: boolean): Promise<void> {
    await this.api.setAskBeforeExec(on);
  }

  /** Part A's boot path. Live boot uses loadSessions() instead (Task 3), so this is empty. */
  async sessions(): Promise<{ sessions: SessionRec[]; runs: Run[]; lastRunNumber: number }> {
    return { sessions: [], runs: [], lastRunNumber: 0 };
  }

  /** POST /api/sessions. The server numbers sessions and reuses the newest empty one, so `count` is ignored. */
  newSession(): Promise<{ id: string; name: string; started: string }> {
    return this.createSession();
  }

  async createSession(): Promise<{ id: string; name: string; started: string }> {
    const s = await this.api.createSession();
    this.currentStarted = s.created_at;
    return { id: s.id, name: s.name, started: s.created_at };
  }

  async removeTool(name: string): Promise<void> {
    await this.api.removeTool(name);
  }

  /** GET /api/sessions: the sessions with runs, newest first. */
  listSessions(): Promise<ApiSessionSummary[]> {
    return this.api.listSessions();
  }

  /** Reads each listed session: its record, its runs as stubs (sorted by n), and its active run if any. */
  async loadSessions(list: ApiSessionSummary[]): Promise<LoadedSession[]> {
    const details = await Promise.all(list.map((s) => this.api.getSession(s.id)));
    return details.map((d) => {
      const sorted = [...d.runs].sort((a, b) => a.n - b.n);
      const rec: SessionRec = {
        id: d.session.id,
        name: d.session.name,
        started: d.session.created_at,
        live: false,
        runIds: sorted.map((r) => r.id),
        messages: toMessages(d),
      };
      return { rec, runs: sorted.map((r) => stubRun(d.session.id, r)), active: sorted.find((r) => ACTIVE.has(r.status)) ?? null };
    });
  }

  /** A finished run's event log, normalised like the live stream. */
  async runEvents(id: string): Promise<RunEvent[]> {
    return (await this.api.runEvents(id)).map(normalise);
  }

  getRun(id: string): Promise<ApiRun> {
    return this.api.getRun(id);
  }
}
