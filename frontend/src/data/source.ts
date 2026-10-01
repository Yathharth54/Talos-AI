import type { Run, SessionRec, SettingsState, VaultTool } from "../store/types";

/** Where the stores load from. Demo: createDemoDataSource() (part A). Live: the API (part B). */
export interface DataSource {
  vault(): Promise<VaultTool[]>;
  toolSource(name: string): Promise<string[] | null>;
  settings(): Promise<SettingsState>;
  setAskBeforeExec(on: boolean): Promise<void>;
  /** Past sessions with their runs (final state) and messages, plus the highest run number used. */
  sessions(): Promise<{ sessions: SessionRec[]; runs: Run[]; lastRunNumber: number }>;
  /** Creates the next session. `count` is its number (Session {count}). */
  newSession(count: number): Promise<{ id: string; name: string; started: string }>;
  removeTool(name: string): Promise<void>;
}
