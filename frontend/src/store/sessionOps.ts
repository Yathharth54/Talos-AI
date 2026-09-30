import type { Message, SessionRec, SessionState, TalosMessage } from "./types";

export const curSession = (s: SessionState): SessionRec => s.sessions.find((x) => x.id === s.curId)!;
/** The session the conversation column shows: the one being read, or the current one. */
export const shownSession = (s: SessionState): SessionRec => s.sessions.find((x) => x.id === (s.viewId ?? s.curId))!;

const mapSession = (s: SessionState, id: string, fn: (x: SessionRec) => SessionRec): SessionState => ({
  ...s,
  sessions: s.sessions.map((x) => (x.id === id ? fn(x) : x)),
});

/** addYou() (line 936), after submit() marks earlier messages past (line 1455). */
export function addYou(s: SessionState, sessionId: string, text: string, key: string): SessionState {
  return mapSession(s, sessionId, (x) => ({
    ...x,
    messages: [...x.messages.map((m) => ({ ...m, past: true })), { kind: "you", key, text, past: false }],
  }));
}

/** addTalos() (line 942). */
export function addTalos(s: SessionState, sessionId: string, runN: number, key: string, thinking: string): SessionState {
  const m: TalosMessage = { kind: "talos", key, runN, status: thinking, html: null, wrap: true, wordsOn: 0, note: null, chips: [], suggest: false, stopNote: null, runLink: false, past: false };
  return mapSession(s, sessionId, (x) => ({ ...x, messages: [...x.messages, m] }));
}

export function updateTalos(s: SessionState, runN: number, fn: (m: TalosMessage) => TalosMessage): SessionState {
  return {
    ...s,
    sessions: s.sessions.map((x) =>
      x.messages.some((m) => m.kind === "talos" && m.runN === runN)
        ? { ...x, messages: x.messages.map((m): Message => (m.kind === "talos" && m.runN === runN ? fn(m) : m)) }
        : x,
    ),
  };
}

export const rename = (s: SessionState, sessionId: string, name: string): SessionState => mapSession(s, sessionId, (x) => ({ ...x, name }));
/** Adds a run to a session once: a re-attached live run is already listed (from its stub) when run.started arrives. */
export const attachRun = (s: SessionState, sessionId: string, runId: string): SessionState =>
  mapSession(s, sessionId, (x) => (x.runIds.includes(runId) ? x : { ...x, runIds: [...x.runIds, runId] }));

/** newSession() (line 2157): keep the old current session if it has runs, else drop it. */
export function openNewSession(s: SessionState, rec: { id: string; name: string; started: string }): SessionState {
  const cur = s.sessions.find((x) => x.id === s.curId);
  let sessions = s.sessions;
  if (cur && cur.runIds.length) sessions = sessions.map((x) => (x.id === cur.id ? { ...x, live: false } : x));
  else if (cur) sessions = sessions.filter((x) => x.id !== cur.id);
  const next: SessionRec = { ...rec, live: true, runIds: [], messages: [] };
  return { sessions: [...sessions, next], curId: next.id, viewId: null, count: s.count + 1 };
}
