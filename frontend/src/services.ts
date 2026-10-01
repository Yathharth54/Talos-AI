import { LiveDataSource } from "./data/live";
import type { DataSource } from "./data/source";
import { createDemoDataSource } from "./demo/source";
import type { Mode } from "./mode";
import { createStores, type Stores } from "./store/stores";
import { createApi, type Api } from "./transport/api";
import { DemoTransport, type DemoWorld } from "./transport/demo";
import { LiveTransport } from "./transport/live";
import type { EventSourceCtor } from "./transport/sse";
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

/** Demo: the scripted data and DemoTransport. Live: the stage 2 API and LiveTransport. */
export async function createServices(mode: Mode): Promise<{ stores: Stores; services: Services }> {
  if (mode === "live") return createLiveServices();
  const data = createDemoDataSource();
  const [tools, settings, past] = await Promise.all([data.vault(), data.settings(), data.sessions()]);
  const current = await data.newSession(1);
  const stores = createStores({ tools, settings, sessions: past.sessions, runs: past.runs, current, count: 1 });
  const demo = new DemoTransport(demoWorld(stores), { lastRunNumber: past.lastRunNumber });
  return { stores, services: { mode, data, transport: demo, demo, lastRunNumber: past.lastRunNumber } };
}

/**
 * Live boot (spec 04 §5, ruling 7): the newest session with runs is the current one, or a new (or the
 * server's reused empty) session when there is none. The others are past sessions with stub runs.
 * `api` and `ES` are injectable for tests.
 */
export async function createLiveServices(api: Api = createApi(), ES?: EventSourceCtor): Promise<{ stores: Stores; services: Services }> {
  const data = new LiveDataSource(api);
  const [settings, list] = await Promise.all([data.settings(), api.listSessions()]);
  const head = list[0];
  const current = head ? { id: head.id, name: head.name, started: head.created_at } : await data.newSession();
  data.setCurrentStarted(current.started);
  const [tools, loaded] = await Promise.all([data.vault(), data.loadSessions(list)]);
  const cur = loaded.find((l) => l.rec.id === current.id);
  const past = loaded.filter((l) => l !== cur);
  const stores = createStores({
    tools, settings, sessions: past.map((l) => l.rec), runs: loaded.flatMap((l) => l.runs), current, count: 0,
  });
  if (cur) {
    stores.session.update((s) => ({
      ...s,
      sessions: s.sessions.map((x) => (x.id === cur.rec.id ? { ...x, runIds: cur.rec.runIds, messages: cur.rec.messages } : x)),
    }));
  }
  // The reference's initial caesar_cipher selection belongs to the demo's vault: the Vault falls back to its first row.
  stores.ui.set({ selected: null });
  return { stores, services: { mode: "live", data, transport: new LiveTransport(api, ES), demo: null, lastRunNumber: 0 } };
}
