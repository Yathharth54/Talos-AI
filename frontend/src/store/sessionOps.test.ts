import { addTalos, addYou, openNewSession, updateTalos } from "./sessionOps";
import type { SessionState } from "./types";

const empty = (): SessionState => ({ sessions: [{ id: "s1", name: "Session 1", started: "2026-09-30T12:00", live: true, runIds: [], messages: [] }], curId: "s1", viewId: null, count: 1 });

test("addYou marks earlier messages past; addTalos starts thinking", () => {
  let s = addYou(empty(), "s1", "one", "y1");
  s = addTalos(s, "s1", 6, "t1", "Working on it");
  s = addYou(s, "s1", "two", "y2");
  const msgs = s.sessions[0]!.messages;
  expect(msgs.map((m) => m.past)).toEqual([true, true, false]);
  expect(msgs[1]).toMatchObject({ kind: "talos", status: "Working on it", html: null, runLink: false });
  s = updateTalos(s, 6, (m) => ({ ...m, runLink: true }));
  expect(s.sessions[0]!.messages[1]).toMatchObject({ runLink: true });
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
