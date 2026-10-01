import { fireEvent, render, screen } from "@testing-library/react";
import { seedSessions } from "../../demo/seeds";
import { VAULT_ROWS } from "../../demo/data";
import { freshVault } from "../../store/vaultOps";
import { expectParity, fixtureCase, snap } from "../../test/parity";
import { asRun } from "../../test/parity/runs";
import { innerOf, ssr } from "../../test/ssr";
import type { Run, SessionRec } from "../../store/types";
import { SessionsView } from "./SessionsView";

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
});
afterAll(() => vi.useRealTimers());

const seeded = () => seedSessions(freshVault(VAULT_ROWS));
// The reference's `s${count}-${Date.now()}` at the fixture clock.
const SID = "s1-1790769600000";
const current = (runs: Run[] = [], name = "Session 1"): SessionRec => ({ id: SID, name, started: "2026-09-30T12:00", live: true, runIds: runs.map((r) => r.id), messages: [] });

test("sessions/boot (seeds plus the empty current session)", () => {
  const { sessions, runs } = seeded();
  const byId = Object.fromEntries(runs.map((r) => [r.id, r]));
  expectParity(ssr(<SessionsView sessions={[...sessions, current()]} runsById={byId} curId={SID} onOpen={() => {}} />), fixtureCase("sessions/boot").html!);
});

test("escapes queries (unknown-html flow)", () => {
  const s = snap("unknown-html", "sessions");
  const { sessions, runs } = seeded();
  const mine = s.sessionRuns.map(asRun).map((r) => ({ ...r, id: `run-${r.n}` }));
  const byId = Object.fromEntries([...runs, ...mine].map((r) => [r.id, r]));
  const name = "Summarise <b>this</b> PDF &";
  expectParity(ssr(<SessionsView sessions={[...sessions, current(mine, name)]} runsById={byId} curId={SID} onOpen={() => {}} />), innerOf(s.regions["#view-sessions"]!, "#sessions-in"));
  expect(s.regions["#view-sessions"]).toContain("Summarise &lt;b&gt;this&lt;/b&gt; PDF &amp;");
});

test("Open and Continue call back with the session id", () => {
  const onOpen = vi.fn();
  const { sessions, runs } = seeded();
  render(<SessionsView sessions={[...sessions, current()]} runsById={Object.fromEntries(runs.map((r) => [r.id, r]))} curId={SID} onOpen={onOpen} />);
  fireEvent.click(screen.getAllByText("Open")[0]!);
  expect(onOpen).toHaveBeenCalledWith("seed-b64");
});
