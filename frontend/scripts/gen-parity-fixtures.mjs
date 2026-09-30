// Runs the reference in headless Chromium and writes src/test/parity/fixtures.json.
// Regenerate with `npm run fixtures` whenever a case or flow changes. Never edit the output by hand.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";
import { CASES } from "./parity-cases.mjs";
import { DEFAULT_REGIONS, FLOWS } from "./parity-flows.mjs";
import { REF_BODY, REF_INDEX } from "./reference.mjs";

export const FIXED_NOW = "2026-09-30T12:00:00Z";
const OUT = resolve(process.cwd(), "src/test/parity/fixtures.json");

/** Installed in the page: clone helpers, state builders, snapshots and checkpoint hooks. */
function installHarness(defaultRegions) {
  const clone = (run) => {
    if (!run) return null;
    return JSON.parse(JSON.stringify(run, (k, v) => (k === "talos" || k === "timers" ? undefined : v)));
  };
  const cloneSession = (s) => ({ id: s.id, name: s.name, started: s.started, live: s.live, runs: s.runs.map(clone) });
  const pure = (run) => {
    const c = clone(run);
    const list = (S.viewSession || S.cur).runs;
    const i = list.indexOf(run);
    const cur = S.current;
    if (i >= 0) list[i] = c;
    if (cur === run) S.current = c;
    try {
      return { strip: stripHtml(c), banner: bannerHtml(c), tabs: tabsHtml(c), panel: panelHtml(c) };
    } finally {
      if (i >= 0) list[i] = run;
      S.current = cur;
    }
  };
  const snap = (regions) => {
    const out = {};
    for (const sel of regions || defaultRegions) {
      const el = document.querySelector(sel);
      out[sel] = el ? el.outerHTML : null;
    }
    return {
      regions: out,
      run: clone(S.viewing),
      pure: S.viewing ? pure(S.viewing) : null,
      vault: JSON.parse(JSON.stringify(S.vault)),
      env: { ...S.env },
      askExec: S.askExec,
      sessionRuns: (S.viewSession || S.cur).runs.map(clone),
      viewSession: !!S.viewSession,
      isCurrent: !!S.viewing && S.viewing === S.current,
    };
  };
  window.__t = {
    clone, cloneSession, snap, snaps: {}, hooks: [],
    mk(variant, states = {}, extra = {}) {
      const run = newRun(extra.query || "q");
      initStrip(run, variant);
      for (const [k, v] of Object.entries(states)) run.nodes[k].state = v;
      Object.assign(run, extra);
      return run;
    },
  };
  const orig = wait;
  wait = (run, ms) => {
    for (const h of window.__t.hooks) {
      if (h.done || !new Function(`return (${h.cond});`)()) continue;
      h.done = true;
      if (h.kind === "snapAt") window.__t.snaps[h.name] = snap(h.regions);
      else for (const sel of h.click) document.querySelector(sel).click();
    }
    return orig(run, ms);
  };
}

async function newPage(browser) {
  const ctx = await browser.newContext({ reducedMotion: "reduce", timezoneId: "UTC", viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.route(/^https?:/, (r) => r.abort());
  await page.clock.setFixedTime(new Date(FIXED_NOW));
  await page.goto(pathToFileURL(REF_INDEX).href);
  await page.evaluate(installHarness, DEFAULT_REGIONS);
  return { ctx, page };
}

async function runFlow(page, actions) {
  const snaps = {};
  for (const a of actions) {
    switch (a.do) {
      case "submit":
        await page.fill("#ask", a.text);
        // Don't return the promise: submit() only settles when the run ends.
        await page.evaluate(() => { document.querySelector("#composer").requestSubmit(); });
        break;
      case "click":
        await page.evaluate((sel) => { document.querySelector(sel).click(); }, a.sel);
        break;
      case "fill":
        await page.fill(a.sel, a.value);
        break;
      case "key":
        await page.keyboard.press(a.key);
        break;
      case "hash":
        await page.evaluate((h) => { location.hash = h; }, a.value);
        await page.waitForFunction((h) => location.hash === h && S.view === h.slice(1), a.value);
        break;
      case "until":
        await page.waitForFunction(a.cond, null, { timeout: 60000 });
        break;
      case "snap":
        snaps[a.name] = await page.evaluate((r) => window.__t.snap(r), a.regions ?? null);
        break;
      case "snapAt":
      case "at":
        await page.evaluate((h) => { window.__t.hooks.push({ ...h, kind: h.do, done: false }); }, a);
        break;
      default:
        throw new Error(`unknown action ${a.do}`);
    }
  }
  const hooked = await page.evaluate(() => window.__t.snaps);
  for (const a of actions) {
    if (a.do === "snapAt" && !hooked[a.name]) throw new Error(`checkpoint ${a.name} never fired`);
  }
  return { ...hooked, ...snaps };
}

const browser = await chromium.launch();
try {
  const out = {
    generatedAt: FIXED_NOW,
    reference: createHash("sha256").update(readFileSync(REF_BODY)).digest("hex"),
    cases: {},
    flows: {},
  };
  for (const c of CASES) {
    const { ctx, page } = await newPage(browser);
    out.cases[c.id] = await page.evaluate(c.build);
    await ctx.close();
  }
  for (const [name, actions] of Object.entries(FLOWS)) {
    const { ctx, page } = await newPage(browser);
    out.flows[name] = { actions, snaps: await runFlow(page, actions) };
    await ctx.close();
    console.log(`flow ${name}: ${Object.keys(out.flows[name].snaps).length} snapshots`);
  }
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(out, null, 1) + "\n");
  console.log(`wrote ${Object.keys(out.cases).length} cases and ${Object.keys(out.flows).length} flows to ${OUT}`);
} finally {
  await browser.close();
}
