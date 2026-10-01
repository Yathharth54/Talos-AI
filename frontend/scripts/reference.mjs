import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// npm scripts and Vitest both run with frontend/ as the working directory.
export const REF_DIR = resolve(process.cwd(), "../docs/superpowers/specs/reference/workbench-demo");
export const REF_BODY = resolve(REF_DIR, "artifact-body.html");
export const REF_INDEX = resolve(REF_DIR, "index.html");
export const REF_ASSETS = resolve(REF_DIR, "assets");

export function readRef() {
  return readFileSync(REF_BODY, "utf8").replace(/\r\n/g, "\n");
}

export function extractStyle(ref) {
  const m = ref.match(/<style>\n([\s\S]*?)<\/style>/);
  if (!m) throw new Error("no <style> block in the reference");
  return m[1];
}

export function extractTextScript(ref, id) {
  const m = ref.match(new RegExp(`<script type="text/plain" id="${id}">([\\s\\S]*?)</script>`));
  if (!m) throw new Error(`no text script #${id} in the reference`);
  return m[1];
}

export function extractVaultData(ref) {
  const m = ref.match(/const VAULT_DATA = (\[[\s\S]*?\]);\n/);
  if (!m) throw new Error("no VAULT_DATA in the reference");
  return JSON.parse(m[1]);
}
