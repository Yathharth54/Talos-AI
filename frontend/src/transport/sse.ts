import type { EventType, RunEvent } from "./types";

/* A Record so the compiler rejects a missing or unknown event type. */
const ALL: Record<EventType, true> = {
  "run.started": true, "log.cmd": true, "plan.ready": true, "strip.set": true, "subtask.started": true,
  "node.started": true, "node.finished": true, "link.flow": true, caption: true, "log.line": true, "log.pop": true,
  "log.status": true, "talos.status": true, "forge.code": true, "forge.tests": true, "forge.attempt": true,
  "forge.smoke": true, "vault.saved": true, "vault.failure": true, "call.args": true, "call.result": true,
  "call.error": true, interrupt: true, "interrupt.resolved": true, "answer.delta": true, "answer.done": true,
  "run.finished": true, error: true,
};

/** Every contract event type: EventSource only delivers named events to listeners for their name. */
export const EVENT_TYPES = Object.keys(ALL) as EventType[];

/** Parses a whole SSE body (a finished run's backlog). Comments (": keep-alive") are skipped. */
export function parseSse(text: string): RunEvent[] {
  const out: RunEvent[] = [];
  for (const block of text.replace(/\r\n/g, "\n").split("\n\n")) {
    const data = block
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data) continue;
    try {
      out.push(JSON.parse(data) as RunEvent);
    } catch (err) {
      console.warn("Skipped an SSE block that isn't JSON", err);
    }
  }
  return out;
}

export type EventSourceCtor = new (url: string) => {
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void): void;
  close(): void;
  onerror: ((this: unknown, ev: Event) => unknown) | null;
};

/**
 * One EventSource per run. On an error it closes and reconnects itself with ?after=<last seq>
 * (a new EventSource can't set Last-Event-ID, and stage 2 reads the header before ?after).
 * Events at or below the last delivered seq are dropped. It closes for good on run.finished,
 * because the browser would otherwise reconnect when the server ends the stream and replay it.
 * Reconnects back off from `retryMs`, doubling up to RETRY_CAP_MS; a delivered event resets them.
 */
export const RETRY_CAP_MS = 30_000;

export function openRunStream(o: {
  runId: string;
  after: number;
  onEvent(e: RunEvent): void;
  ES?: EventSourceCtor;
  retryMs?: number;
}): { close(): void } {
  const ES = o.ES ?? (EventSource as unknown as EventSourceCtor);
  let last = o.after;
  let closed = false;
  let es: InstanceType<EventSourceCtor> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const base = o.retryMs ?? 1000;
  let delay = base;

  const close = () => {
    closed = true;
    if (timer) clearTimeout(timer);
    timer = null;
    es?.close();
  };
  const onMessage = (m: MessageEvent<string>) => {
    // A dropped connection also fires "error" (the contract's `error` type) with no data.
    if (closed || typeof m.data !== "string") return;
    let e: RunEvent;
    try {
      e = JSON.parse(m.data) as RunEvent;
    } catch (err) {
      console.warn("Skipped an SSE event that isn't JSON", err);
      return;
    }
    delay = base;
    if (e.seq <= last) return;
    last = e.seq;
    o.onEvent(e);
    if (e.type === "run.finished") close();
  };
  const connect = () => {
    timer = null;
    if (closed) return;
    const cur = new ES(`/api/runs/${encodeURIComponent(o.runId)}/events?after=${last}`);
    es = cur;
    for (const t of EVENT_TYPES) cur.addEventListener(t, onMessage);
    cur.onerror = (ev) => {
      // A server-sent `event: error` also reaches onerror; it's a contract event, not a failure.
      if ("data" in ev) return;
      cur.close();
      if (!closed && es === cur && timer === null) {
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, RETRY_CAP_MS);
      }
    };
  };
  connect();
  return { close };
}
