import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect } from "vitest";
import raw from "./fixtures.json";
import { normalizeHtml } from "../normalize";

export const FIXED_NOW = "2026-09-30T12:00:00Z";

export type FlowAction =
  | { do: "submit"; text: string }
  | { do: "click"; sel: string }
  | { do: "fill"; sel: string; value: string }
  | { do: "key"; key: string }
  | { do: "hash"; value: string }
  | { do: "until"; cond: string }
  | { do: "snap"; name: string; regions?: string[] }
  | { do: "snapAt"; name: string; cond: string; regions?: string[] }
  | { do: "at"; cond: string; click: string[] };

export interface Snap {
  regions: Record<string, string | null>;
  run: unknown;
  pure: { strip: string; banner: string; tabs: string; panel: string } | null;
  vault: unknown[];
  env: Record<string, string>;
  askExec: boolean;
  sessionRuns: unknown[];
  viewSession: boolean;
  isCurrent: boolean;
}
export interface FlowFixture {
  actions: FlowAction[];
  snaps: Record<string, Snap>;
}
export interface CaseFixture {
  state: Record<string, unknown>;
  html?: string;
  value?: unknown;
}

const data = raw as unknown as {
  generatedAt: string;
  reference: string;
  cases: Record<string, CaseFixture>;
  flows: Record<string, FlowFixture>;
};

export const fixtureSha = data.reference;
export const referenceSha = () =>
  createHash("sha256")
    .update(readFileSync(resolve(process.cwd(), "../docs/superpowers/specs/reference/workbench-demo/artifact-body.html")))
    .digest("hex");

export function fixtureCase(id: string): CaseFixture {
  const c = data.cases[id];
  if (!c) throw new Error(`no parity case ${id}; add it to scripts/parity-cases.mjs and run npm run fixtures`);
  return c;
}
export function flow(name: string): FlowFixture {
  const f = data.flows[name];
  if (!f) throw new Error(`no parity flow ${name}`);
  return f;
}
export function snap(flowName: string, snapName: string): Snap {
  const s = flow(flowName).snaps[snapName];
  if (!s) throw new Error(`no snapshot ${flowName}/${snapName}`);
  return s;
}
export const allFlows = () => Object.keys(data.flows);

/** Asserts DOM parity after normalisation. */
export function expectParity(actualHtml: string, expectedHtml: string): void {
  expect(normalizeHtml(actualHtml)).toBe(normalizeHtml(expectedHtml));
}
