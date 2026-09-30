import { act, render } from "@testing-library/react";
import { App } from "../App";
import { SettingsView } from "../components/settings/SettingsView";
import { Idle } from "../components/workbench/Idle";
import { createServices } from "../services";
import type { Stores } from "../store/stores";
import type { LiveSettings, VaultTool } from "../store/types";
import { expectParity, fixtureCase } from "../test/parity";
import { ssr } from "../test/ssr";
import { Workbench } from "./workbench";

/* Spec 04 §8: the only differences live mode shows, and nothing else. */

const LIVE: LiveSettings = {
  keys: [
    { name: "OPENROUTER_API_KEY", set: true, required: true, description: "x" },
    { name: "TAVILY_API_KEY", set: false, required: false, description: "x" },
    { name: "JINA_API_KEY", set: false, required: false, description: "x" },
    { name: "LANGSMITH_API_KEY", set: false, required: false, description: "x" },
    { name: "OPENWEATHERMAP_API_KEY", set: true, required: false, description: "Saved by Human check" },
  ],
  forgeRetries: 3,
  testTimeoutS: 10,
  llmTimeoutS: 120.0,
  pruneAfter: 2,
};
const tool = (name: string): VaultTool => ({
  name, args: "x: str", ret: "str", desc: "d", kw: ["k"], uses: 1, fails: 0, streak: 0,
  created: "2026-09-30T10:00:00.000Z", last: "", lastFail: "", lastFailAt: "", web: false, fresh: false,
});

async function mountLive(view: "workbench" | "vault" | "settings" = "workbench") {
  const { stores, services } = await createServices("demo");
  stores.settings.set({ model: "server/model", askExec: true, env: { OPENROUTER_API_KEY: "set" }, live: LIVE });
  stores.vault.set({ tools: [tool("with_src"), tool("no_src")], sources: { with_src: ["a", "b", "c"], no_src: null } });
  const wb = new Workbench(stores, { ...services, mode: "live" });
  window.location.hash = view === "workbench" ? "" : `#${view}`;
  const r = render(<App stores={stores} workbench={wb} />);
  await act(async () => {});
  return { stores, wb, ...r };
}
const text = (sel: string) => document.querySelector(sel)?.textContent ?? null;
const select = async (stores: Stores, name: string) => {
  await act(async () => stores.ui.set({ selected: name }));
};

test("live mode hides the Demo controls and shows the server's model", async () => {
  await mountLive();
  expect(document.querySelector("#demo-toggle")).toBeNull();
  expect(document.querySelector("#demo-pop")).toBeNull();
  expect(document.body.textContent).not.toContain("Reset the demo");
  expect(text(".top-right .model")).toBe("server/model");
});

test("the key dialog footer has no demo sentence", async () => {
  const { stores } = await mountLive();
  await act(async () => stores.ui.set({ dialog: { kind: "key", runId: "r", toolName: "t", envVar: "K", service: "S" } }));
  expect(text(".d-foot")).toBe("If you skip, the tool is still saved to the vault, but it fails when it runs until the key is set.");
});

test("the vault detail has no 'This demo only bundles' line, and shows the source when there is one", async () => {
  const { stores } = await mountLive("vault");
  await select(stores, "no_src");
  expect(document.querySelector(".code-read")).toBeNull();
  expect(document.body.textContent).not.toContain("This demo only bundles");
  await select(stores, "with_src");
  expect(document.querySelector(".code-read")).not.toBeNull();
  expect(document.body.textContent).toContain("Read full file");
  expect(document.querySelector(".code-read .fig-cap .meta")?.textContent).toContain("3 lines, written by the Forger");
});

test("settings rows and facts come from the server", async () => {
  await mountLive("settings");
  const rows = [...document.querySelectorAll("#set-keys ~ ul li")].map((li) => ({
    name: li.querySelector(".mono")?.textContent,
    desc: li.querySelector(".d")?.textContent,
    state: li.lastElementChild?.textContent,
    muted: li.lastElementChild?.classList.contains("muted"),
  }));
  expect(rows).toEqual([
    { name: "OPENROUTER_API_KEY", desc: "Required. Every model call goes through OpenRouter.", state: "Set", muted: false },
    { name: "TAVILY_API_KEY", desc: "Needed for web search.", state: "Not set", muted: true },
    { name: "JINA_API_KEY", desc: "Optional. Raises web-reading limits.", state: "Not set", muted: true },
    { name: "LANGSMITH_API_KEY", desc: "Optional. Traces every node in LangSmith.", state: "Not set", muted: true },
    { name: "OPENWEATHERMAP_API_KEY", desc: "Saved by Human check this session.", state: "Set", muted: false },
  ]);
  expect([...document.querySelectorAll(".facts dd")].slice(1).map((d) => d.textContent)).toEqual(["3", "10 seconds", "120 seconds", "2 failures in a row"]);
});

test("the idle setup line counts the server's keys", async () => {
  await mountLive();
  expect(text(".setup-line")).toBe("2 of 5 keys set in .env. Ask before running code is on. Settings");
});

test("no demo-only copy anywhere in live mode", async () => {
  const { stores } = await mountLive("vault");
  await select(stores, "no_src");
  const html = document.documentElement.innerHTML;
  for (const s of ["Demo controls", "This demo", "demo keeps", "Scripted runs"]) expect(html).not.toContain(s);
});

test("demo rendering is unchanged when the optional props are absent", () => {
  const noop = () => {};
  for (const id of ["settings/default", "settings/off-key"]) {
    const c = fixtureCase(id);
    const s = c.state as { askExec: boolean; env: Record<string, string> };
    expectParity(ssr(<SettingsView askExec={s.askExec} env={s.env} model="deepseek/deepseek-v4.1-flash" onToggleAsk={noop} />), c.html!);
  }
  for (const id of ["idle/default", "idle/key-set-ask-off"]) {
    const c = fixtureCase(id);
    const s = c.state as { count: number; env: Record<string, string>; askExec: boolean };
    expectParity(ssr(<Idle count={s.count} weatherKeySet={!!s.env.OPENWEATHERMAP_API_KEY} askExec={s.askExec} onSuggest={noop} />), c.html!);
  }
});
