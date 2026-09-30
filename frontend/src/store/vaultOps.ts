import type { VaultRow } from "../demo/data";
import type { VaultEntry } from "../transport/types";
import type { UiState, VaultTool } from "./types";

/** freshVault() (line 912). */
export function freshVault(rows: VaultRow[]): VaultTool[] {
  return rows.map(([name, args, ret, desc, kw, uses, fails, streak, created, last, lastFail]) => ({
    name, args, ret, desc, kw, uses, fails, streak, created, last, lastFail,
    lastFailAt: lastFail ? last : "",
    web: name.startsWith("fetch_"),
    fresh: false,
  }));
}

/** API/contract entry → the reference's tool shape. `fresh` = "New this session". */
export function fromVaultEntry(e: VaultEntry, fresh: boolean): VaultTool {
  return {
    name: e.name, args: e.args, ret: e.ret, desc: e.description, kw: e.keywords, uses: e.uses, fails: e.failures, streak: e.streak,
    created: e.created_at ?? "", last: e.last_used ?? "", lastFail: e.last_failure ?? "", lastFailAt: e.last_failed_at ?? "", web: e.web, fresh,
  };
}

export const findTool = (tools: VaultTool[], name: string | null | undefined): VaultTool | undefined =>
  name ? tools.find((t) => t.name === name) : undefined;

/** vaultRows() (line 1956). */
export function vaultRows(tools: VaultTool[], filter: UiState["filter"], query: string): VaultTool[] {
  const q = query.toLowerCase();
  return tools
    .filter((t) => filter === "all" || (filter === "web" ? t.web : t.fails > 0))
    .filter((t) => !q || t.name.toLowerCase().includes(q) || t.kw.some((k) => k.includes(q)) || t.desc.toLowerCase().includes(q))
    .sort((a, b) => (b.last || b.created).localeCompare(a.last || a.created));
}

export const addTool = (tools: VaultTool[], tool: VaultTool): VaultTool[] => [...tools.filter((t) => t.name !== tool.name), tool];
export const removeTool = (tools: VaultTool[], name: string): VaultTool[] => tools.filter((t) => t.name !== name);

/** A successful call (lines 1743, 1896). */
export const recordUse = (tools: VaultTool[], name: string, now: string): VaultTool[] =>
  tools.map((t) => (t.name === name ? { ...t, uses: t.uses + 1, streak: 0, last: now } : t));

/** A failed call (lines 1711, 1880). */
export const recordFailure = (tools: VaultTool[], name: string, streak: number, error: string, now: string): VaultTool[] =>
  tools.map((t) => (t.name === name ? { ...t, fails: t.fails + 1, streak, lastFail: error, lastFailAt: now } : t));
