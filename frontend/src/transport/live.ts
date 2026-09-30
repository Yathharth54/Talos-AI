import { sanitize } from "../lib/sanitize";
import type { Api } from "./api";
import { openRunStream, type EventSourceCtor } from "./sse";
import type { EventSink, ResumeDecision, RunEvent, StartedRun, Transport } from "./types";

/**
 * Server facts → what the player expects: every server HTML field it renders as HTML goes through the
 * allowlist sanitiser. `call.error.when` stays a code: the player's whenText() turns the stage 2 codes
 * (skipped, dispatch, arguments, declined, run) into the reference's text for live and demo alike.
 */
export function normalise(e: RunEvent): RunEvent {
  switch (e.type) {
    case "caption":
      return { ...e, data: { html: sanitize(e.data.html) } };
    case "forge.code":
      return e.data.note == null ? e : { ...e, data: { ...e.data, note: sanitize(e.data.note) } };
    case "answer.done":
      return { ...e, data: { ...e.data, html: sanitize(e.data.html), note: e.data.note == null ? null : sanitize(e.data.note) } };
    default:
      return e;
  }
}

/** Live runs over stage 2: POST to start, one EventSource per run, /resume and /stop. */
export class LiveTransport implements Transport {
  constructor(
    private readonly api: Api,
    private readonly ES?: EventSourceCtor,
  ) {}

  async startRun(sessionId: string, text: string): Promise<StartedRun> {
    const { run } = await this.api.send(sessionId, text);
    /* Stage 2 renames the session on its first run: read the new name back. */
    const sessionName = run.n === 1 ? (await this.api.getSession(sessionId)).session.name : null;
    return { runId: run.id, n: run.n, sessionName };
  }

  subscribe(runId: string, sink: EventSink, after = 0): () => void {
    const s = openRunStream({ runId, after, ES: this.ES, onEvent: (e) => void sink(normalise(e)) });
    return () => s.close();
  }

  /** A saved key's value goes into the one request body and is not kept anywhere here. */
  resume(runId: string, decision: ResumeDecision): Promise<void> {
    return this.api.resume(runId, decision);
  }

  stop(runId: string): Promise<void> {
    return this.api.stop(runId);
  }
}
