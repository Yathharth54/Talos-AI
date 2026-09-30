import { openRunStream, parseSse } from "./sse";
import type { RunEvent } from "./types";

const env = (seq: number, type: string, data: object = {}) => ({ run_id: "r", seq, ts: "2026-09-30T12:00:00.000Z", type, data });
const frame = (e: ReturnType<typeof env>) => `id: ${e.seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`;

test("parseSse skips a block that isn't JSON and keeps the rest", () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  const text = `${frame(env(1, "log.cmd", { text: "q" }))}event: log.cmd\ndata: {not json\n\n${frame(env(3, "caption", { html: "x" }))}`;
  expect(parseSse(text).map((e) => e.seq)).toEqual([1, 3]);
  expect(warn).toHaveBeenCalledTimes(1);
  warn.mockRestore();
});

test("parseSse reads envelopes and skips comments", () => {
  const text = `: keep-alive\n\n${frame(env(1, "run.started", { session_id: "s", query: "q", n: 1 }))}${frame(env(2, "log.cmd", { text: "q" }))}`;
  expect(parseSse(text).map((e) => [e.seq, e.type])).toEqual([[1, "run.started"], [2, "log.cmd"]]);
});

/* Like a browser: `onerror` is the attribute handler for the "error" event, so a server-sent
   `event: error` (a MessageEvent) and a connection failure (a plain Event) both reach it and any
   addEventListener("error") listener. */
class FakeES {
  static all: FakeES[] = [];
  listeners = new Map<string, (m: MessageEvent<string>) => void>();
  onerror: ((ev: Event) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeES.all.push(this);
  }
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void) {
    this.listeners.set(type, fn);
  }
  close() {
    this.closed = true;
  }
  fire(type: string, ev: Event) {
    if (this.closed) return;
    this.listeners.get(type)?.(ev as MessageEvent<string>);
    if (type === "error") this.onerror?.(ev);
  }
  emit(e: ReturnType<typeof env>) {
    this.fire(e.type, new MessageEvent(e.type, { data: JSON.stringify(e) }));
  }
  /** A dropped connection: a plain Event with no data. */
  drop() {
    this.fire("error", new Event("error"));
  }
}
beforeEach(() => {
  FakeES.all = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

test("opens at ?after=N, delivers in order, closes on run.finished and never reconnects", () => {
  const got: RunEvent[] = [];
  openRunStream({ runId: "r", after: 0, onEvent: (e) => got.push(e), ES: FakeES as never });
  const es = FakeES.all[0]!;
  expect(es.url).toBe("/api/runs/r/events?after=0");
  es.emit(env(1, "run.started", { session_id: "s", query: "q", n: 1 }));
  es.emit(env(2, "run.finished", { status: "done", summary: "", summary_gold: false, forged: [], used: [] }));
  expect(got.map((e) => e.seq)).toEqual([1, 2]);
  expect(es.closed).toBe(true);
  es.onerror?.(new Event("error"));
  vi.advanceTimersByTime(5000);
  expect(FakeES.all).toHaveLength(1);
});

test("reconnects with after=lastSeq and drops duplicates", () => {
  const got: number[] = [];
  openRunStream({ runId: "r", after: 0, onEvent: (e) => got.push(e.seq), ES: FakeES as never, retryMs: 1000 });
  const a = FakeES.all[0]!;
  a.emit(env(1, "run.started", { session_id: "s", query: "q", n: 1 }));
  a.emit(env(2, "log.cmd", { text: "q" }));
  a.drop();
  expect(a.closed).toBe(true);
  vi.advanceTimersByTime(1000);
  const b = FakeES.all[1]!;
  expect(b.url).toBe("/api/runs/r/events?after=2");
  b.emit(env(2, "log.cmd", { text: "q" }));
  b.emit(env(3, "caption", { html: "x" }));
  expect(got).toEqual([1, 2, 3]);
});

test("close() stops everything, including a pending reconnect", () => {
  const s = openRunStream({ runId: "r", after: 5, onEvent: () => {}, ES: FakeES as never, retryMs: 1000 });
  FakeES.all[0]!.drop();
  s.close();
  vi.advanceTimersByTime(5000);
  expect(FakeES.all).toHaveLength(1);
});

test("a server `error` event is delivered, doesn't close the stream, and run.finished still arrives", () => {
  const got: string[] = [];
  openRunStream({ runId: "r", after: 0, onEvent: (e) => got.push(e.type), ES: FakeES as never, retryMs: 1000 });
  const es = FakeES.all[0]!;
  es.emit(env(1, "error", { message: "The run failed." }));
  expect(es.closed).toBe(false);
  es.emit(env(2, "run.finished", { status: "failed", summary: "", summary_gold: false, forged: [], used: [] }));
  expect(got).toEqual(["error", "run.finished"]);
  vi.advanceTimersByTime(5000);
  expect(FakeES.all).toHaveLength(1);
});

test("a dropped connection (plain error Event) doesn't throw and reconnects", () => {
  const got: number[] = [];
  openRunStream({ runId: "r", after: 4, onEvent: (e) => got.push(e.seq), ES: FakeES as never, retryMs: 1000 });
  expect(() => FakeES.all[0]!.drop()).not.toThrow();
  expect(FakeES.all[0]!.closed).toBe(true);
  vi.advanceTimersByTime(1000);
  expect(FakeES.all[1]!.url).toBe("/api/runs/r/events?after=4");
  expect(got).toEqual([]);
});
