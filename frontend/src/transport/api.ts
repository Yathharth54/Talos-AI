import type {
  ApiMessage,
  ApiRun,
  ApiRunSummary,
  ApiSession,
  ApiSessionDetail,
  ApiSessionSummary,
  ApiSettings,
  ApiVaultDetail,
  ApiVaultList,
  ResumeDecision,
  RunEvent,
} from "./types";
import { parseSse } from "./sse";

/** A non-2xx stage 2 response. A 409 `run_active` also names the active run and its session. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly runId?: string,
    readonly sessionId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface Api {
  listSessions(): Promise<ApiSessionSummary[]>;
  createSession(): Promise<ApiSession>;
  getSession(id: string): Promise<ApiSessionDetail>;
  send(sessionId: string, text: string): Promise<{ run: ApiRunSummary; message: ApiMessage }>;
  getRun(id: string): Promise<ApiRun>;
  /** A finished run's whole event log (the server sends the backlog and closes). Not for running or waiting runs. */
  runEvents(id: string): Promise<RunEvent[]>;
  resume(id: string, d: ResumeDecision): Promise<void>;
  stop(id: string): Promise<void>;
  vault(): Promise<ApiVaultList>;
  tool(name: string): Promise<ApiVaultDetail>;
  removeTool(name: string): Promise<void>;
  settings(): Promise<ApiSettings>;
  setAskBeforeExec(on: boolean): Promise<ApiSettings>;
}

type ErrorBody = { error?: { code?: string; message?: string; run_id?: string; session_id?: string } };

/** Builds an ApiError from a non-2xx response, reading stage 2's `{error: {...}}` body when there is one. */
async function toError(res: Response): Promise<ApiError> {
  const data: unknown = await res.json().catch(() => null);
  const e = (data as ErrorBody | null)?.error;
  return new ApiError(res.status, e?.code ?? `http_${res.status}`, e?.message ?? res.statusText, e?.run_id, e?.session_id);
}

/** The stage 2 REST client. `fetchImpl` is injectable for tests. */
export function createApi(fetchImpl: typeof fetch = (...a) => fetch(...a)): Api {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetchImpl(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 204) return undefined as T;
    if (!res.ok) throw await toError(res);
    return (await res.json().catch(() => null)) as T;
  }
  const enc = encodeURIComponent;
  return {
    listSessions: () => call("GET", "/sessions"),
    createSession: () => call("POST", "/sessions"),
    getSession: (id) => call("GET", `/sessions/${enc(id)}`),
    send: (id, text) => call("POST", `/sessions/${enc(id)}/messages`, { text }),
    getRun: (id) => call("GET", `/runs/${enc(id)}`),
    runEvents: async (id) => {
      const res = await fetchImpl(`/api/runs/${enc(id)}/events?after=0`);
      if (!res.ok) throw await toError(res);
      return parseSse(await res.text());
    },
    resume: async (id, d) => void (await call("POST", `/runs/${enc(id)}/resume`, d)),
    stop: async (id) => void (await call("POST", `/runs/${enc(id)}/stop`)),
    vault: () => call("GET", "/vault"),
    tool: (name) => call("GET", `/vault/${enc(name)}`),
    removeTool: (name) => call("DELETE", `/vault/${enc(name)}`),
    settings: () => call("GET", "/settings"),
    setAskBeforeExec: (on) => call("PATCH", "/settings", { ask_before_exec: on }),
  };
}
