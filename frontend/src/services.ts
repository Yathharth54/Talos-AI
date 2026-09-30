import type { DataSource } from "./data/source";
import { createDemoDataSource } from "./demo/source";
import type { Mode } from "./mode";
import { createStores, type Stores } from "./store/stores";
import { DemoTransport, type DemoWorld } from "./transport/demo";
import type { Transport } from "./transport/types";

export interface Services {
  mode: Mode;
  data: DataSource;
  transport: Transport;
  demo: DemoTransport | null;
  lastRunNumber: number;
}

export function demoWorld(stores: Stores): DemoWorld {
  return {
    tools: () => stores.vault.get().tools,
    hasKey: (env) => !!stores.settings.get().env[env],
    saveKey: (env, value) => stores.settings.update((s) => ({ ...s, env: { ...s.env, [env]: value } })),
    askExec: () => stores.settings.get().askExec,
    speed: () => stores.ui.get().speed,
    sessionRunCount: (sid) => stores.session.get().sessions.find((s) => s.id === sid)?.runIds.length ?? 0,
  };
}

/** The seam part B changes: live mode gets the API data source and LiveTransport. Ruling 12. */
export async function createServices(mode: Mode): Promise<{ stores: Stores; services: Services }> {
  const data = createDemoDataSource();
  const [tools, settings, past] = await Promise.all([data.vault(), data.settings(), data.sessions()]);
  const current = await data.newSession(1);
  const stores = createStores({ tools, settings, sessions: past.sessions, runs: past.runs, current, count: 1 });
  const demo = new DemoTransport(demoWorld(stores), { lastRunNumber: past.lastRunNumber });
  return { stores, services: { mode, data, transport: demo, demo, lastRunNumber: past.lastRunNumber } };
}
