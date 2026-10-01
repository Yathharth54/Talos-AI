import { addTalos, addYou, attachRun, openNewSession, updateTalos } from "./sessionOps";
import type { SessionState } from "./types";

const empty = (): SessionState => ({ sessions: [{ id: "s1", name: "Session 1", started: "2026-09-30T12:00", live: true, runIds: [], messages: [] }], curId: "s1", viewId: null, count: 1 });

test("addYou marks earlier messages past; addTalos starts thinking", () => {
  let s = addYou(empty(), "s1", "one", "y1");
  s = addTalos(s, "s1", 6, "t1", "Working on it");
  s = addYou(s, "s1", "two", "y2");
  const msgs = s.sessions[0]!.messages;
  expect(msgs.map((m) => m.past)).toEqual([true, true, false]);
  expect(msgs[1]).toMatchObject({ kind: "talos", status: "Working on it", html: null, runLink: false });
  s = updateTalos(s, "s1", 6, (m) => ({ ...m, runLink: true }));
  expect(s.sessions[0]!.messages[1]).toMatchObject({ runLink: true });
});

test("updateTalos changes only the given session's message: run numbers repeat across sessions", () => {
  let s = addTalos(empty(), "s1", 1, "t1", "Working on it");
  s = { ...s, sessions: [...s.sessions, { id: "s2", name: "Session 2", started: "2026-09-30T12:05", live: false, runIds: [], messages: [] }] };
  s = addTalos(s, "s2", 1, "t1", "Working on it");
  s = updateTalos(s, "s2", 1, (m) => ({ ...m, html: "two" }));
  expect(s.sessions.map((x) => x.messages[0])).toMatchObject([{ html: null }, { html: "two" }]);
});

test("openNewSession drops an empty current session and keeps one with runs", () => {
  let s = openNewSession(empty(), { id: "s2", name: "Session 2", started: "2026-09-30T12:05" });
  expect(s.sessions.map((x) => x.id)).toEqual(["s2"]);
  expect(s.count).toBe(2);
  s = { ...s, sessions: s.sessions.map((x) => ({ ...x, runIds: ["run-6"] })) };
  s = openNewSession(s, { id: "s3", name: "Session 3", started: "2026-09-30T12:06" });
  expect(s.sessions.map((x) => [x.id, x.live])).toEqual([["s2", false], ["s3", true]]);
  expect(s.curId).toBe("s3");
});

test("attachRun adds a run once: a re-attached run's run.started finds it already listed", () => {
  let s = attachRun(empty(), "s1", "run-1");
  s = attachRun(s, "s1", "run-1");
  expect(s.sessions[0]!.runIds).toEqual(["run-1"]);
});
