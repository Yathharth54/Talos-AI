import { fixtureCase } from "../test/parity";
import { freshVault } from "../store/vaultOps";
import { VAULT_ROWS } from "./data";
import { seedSessions } from "./seeds";

const strip = (x: unknown): unknown => JSON.parse(JSON.stringify(x, (k, v) => (["key", "id", "sessionId", "runIds", "messages", "cancelled"].includes(k) ? undefined : v)));

test("seeded sessions and runs equal the reference's seedSessions()", () => {
  const ours = seedSessions(freshVault(VAULT_ROWS));
  const all = fixtureCase("seeds/sessions").value as { id: string; name: string; started: string; live: boolean; runs: unknown[] }[];
  const ref = all.filter((s) => s.id.startsWith("seed-")); // the fourth is the boot session, "Session 1"
  expect(ours.lastRunNumber).toBe(5);
  expect(ours.sessions.map((s) => [s.id, s.name, s.started, s.live])).toEqual(ref.map((s) => [s.id, s.name, s.started, s.live]));
  expect(strip(ours.runs)).toEqual(strip(ref.flatMap((s) => s.runs)));
});
