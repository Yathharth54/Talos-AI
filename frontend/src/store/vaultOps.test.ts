import { VAULT_ROWS } from "../demo/data";
import { fixtureCase } from "../test/parity";
import type { VaultTool } from "./types";
import { freshVault, fromVaultEntry, recordFailure, recordUse, removeTool, vaultRows } from "./vaultOps";

test("freshVault equals the reference's S.vault at boot", () => {
  expect(freshVault(VAULT_ROWS)).toEqual(fixtureCase("vault/default").state.tools);
});

test("vaultRows filters, searches and sorts like the reference", () => {
  const tools = freshVault(VAULT_ROWS);
  const html = fixtureCase("vault/failed-query").html!;
  const rows = vaultRows(tools, "failed", "date");
  expect(rows.map((t) => t.name)).toEqual(["normalize_date_strings"]);
  expect(html).toContain('data-tool="normalize_date_strings"');
  expect(vaultRows(tools, "web", "").every((t) => t.web)).toBe(true);
  expect(vaultRows(tools, "all", "zzzz")).toEqual([]);
  expect(vaultRows(tools, "all", "")[0]!.name).toBe("flatten_json");
});

test("use, failure, removal and API entries", () => {
  let tools: VaultTool[] = freshVault(VAULT_ROWS);
  tools = recordUse(tools, "flatten_json", "2026-09-30T12:00");
  expect(tools.find((t) => t.name === "flatten_json")).toMatchObject({ uses: 3, streak: 0, last: "2026-09-30T12:00" });
  tools = recordFailure(tools, "flatten_json", 1, "TypeError: x", "2026-09-30T12:01");
  expect(tools.find((t) => t.name === "flatten_json")).toMatchObject({ fails: 2, streak: 1, lastFail: "TypeError: x", lastFailAt: "2026-09-30T12:01" });
  expect(removeTool(tools, "flatten_json")).toHaveLength(39);
  expect(
    fromVaultEntry({ name: "a", args: "x: int", ret: "int", signature: "a(x: int) -> int", description: "d", keywords: ["k"], uses: 0, failures: 0, streak: 0, created_at: "2026-09-30T12:00", last_used: null, last_failure: null, last_failed_at: null, web: false, file: "talos/vault/tools/a.py" }, true),
  ).toEqual({ name: "a", args: "x: int", ret: "int", desc: "d", kw: ["k"], uses: 0, fails: 0, streak: 0, created: "2026-09-30T12:00", last: "", lastFail: "", lastFailAt: "", web: false, fresh: true });
});
