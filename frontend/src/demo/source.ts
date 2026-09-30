import type { DataSource } from "../data/source";
import { COPY, fill } from "../lib/copy";
import { nowIso } from "../lib/format";
import { freshVault } from "../store/vaultOps";
import { MODEL, SOURCES, VAULT_ROWS } from "./data";
import { seedSessions } from "./seeds";

/** In-memory data for demo mode: the reference's vault, seeded sessions and settings. */
export function createDemoDataSource(): DataSource {
  return {
    vault: async () => freshVault(VAULT_ROWS),
    toolSource: async (name) => SOURCES[name] ?? null,
    settings: async () => ({ askExec: true, env: {}, model: MODEL }),
    setAskBeforeExec: async () => {},
    sessions: async () => seedSessions(freshVault(VAULT_ROWS)),
    newSession: async (count) => ({ id: `s${count}-${Date.now()}`, name: fill(COPY.convo.sessionName, { n: count }), started: nowIso() }),
    removeTool: async () => {},
  };
}
