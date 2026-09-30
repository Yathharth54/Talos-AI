import { createContext, useContext, type ReactNode } from "react";
import { createStore, useStoreState, type Store } from "./createStore";
import type { Run, RunsState, SessionRec, SessionState, SettingsState, UiState, VaultState, VaultTool } from "./types";

export interface Stores {
  runs: Store<RunsState>;
  session: Store<SessionState>;
  vault: Store<VaultState>;
  settings: Store<SettingsState>;
  ui: Store<UiState>;
}

export interface InitialData {
  tools: VaultTool[];
  settings: SettingsState;
  sessions: SessionRec[];
  runs: Run[];
  current: { id: string; name: string; started: string };
  count: number;
}

export const initialUi = (): UiState => ({
  view: "workbench", viewEnter: 0, dialog: null, busy: false, currentRunId: null, viewingRunId: null,
  selected: "caesar_cipher", filter: "all", query: "", stagger: false, vaultRender: 0, popOpen: false, speed: 1, badge: false,
  booted: false, live: "", confirmRemove: null, draft: "", benchKey: 0, titleAnimate: false, titleSeq: 0,
});

export function initialStates(d: InitialData) {
  return {
    runs: { byId: Object.fromEntries(d.runs.map((r) => [r.id, r])) } as RunsState,
    session: {
      sessions: [...d.sessions, { ...d.current, live: true, runIds: [], messages: [] }],
      curId: d.current.id,
      viewId: null,
      count: d.count,
    } as SessionState,
    vault: { tools: d.tools, sources: {} } as VaultState,
    settings: d.settings,
    ui: initialUi(),
  };
}

export function createStores(d: InitialData): Stores {
  const s = initialStates(d);
  return { runs: createStore(s.runs), session: createStore(s.session), vault: createStore(s.vault), settings: createStore(s.settings), ui: createStore(s.ui) };
}

export function updateRun(stores: Stores, id: string, fn: (r: Run) => Run): void {
  stores.runs.update((s) => {
    const r = s.byId[id];
    return r ? { byId: { ...s.byId, [id]: fn(r) } } : s;
  });
}

export const StoresContext = createContext<Stores | null>(null);
export function StoresProvider({ stores, children }: { stores: Stores; children: ReactNode }) {
  return <StoresContext.Provider value={stores}>{children}</StoresContext.Provider>;
}
export function useStores(): Stores {
  const s = useContext(StoresContext);
  if (!s) throw new Error("StoresProvider is missing");
  return s;
}
export const useRuns = <T,>(sel: (s: RunsState) => T) => useStoreState(useStores().runs, sel);
export const useSession = <T,>(sel: (s: SessionState) => T) => useStoreState(useStores().session, sel);
export const useVault = <T,>(sel: (s: VaultState) => T) => useStoreState(useStores().vault, sel);
export const useSettings = <T,>(sel: (s: SettingsState) => T) => useStoreState(useStores().settings, sel);
export const useUi = <T,>(sel: (s: UiState) => T) => useStoreState(useStores().ui, sel);
