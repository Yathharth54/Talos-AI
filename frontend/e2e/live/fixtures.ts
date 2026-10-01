import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// frontend/ is an ES module package, so there is no __dirname. npm scripts run in frontend/ (part A's convention).
export const DOTENV = resolve(process.cwd(), ".e2e-tmp/.env");

export type RunInfo = { id: string; n: number; status: string; sessionId: string };

export class LiveApp {
  runs: RunInfo[] = [];
  constructor(readonly page: Page, readonly api: APIRequestContext) {}

  /** Load the app and wait until boot has picked or created a session. */
  async open(): Promise<void> {
    await this.page.goto("/");
    await expect(this.page.locator("body")).not.toHaveClass(/booting/);
    await expect(this.page.locator("#session-title")).not.toHaveText("");
  }

  /** Send a question through the composer and remember its run. */
  async ask(text: string): Promise<RunInfo> {
    const posted = this.page.waitForResponse((r) => /\/api\/sessions\/[^/]+\/messages$/.test(r.url()) && r.request().method() === "POST");
    await this.page.locator("#ask").fill(text);
    await this.page.locator("#ask").press("Enter");
    const res = await posted;
    const body = (await res.json()) as { run: Omit<RunInfo, "sessionId"> };
    const sessionId = /\/api\/sessions\/([^/]+)\/messages$/.exec(res.url())?.[1] ?? "";
    const run = { ...body.run, sessionId };
    this.runs.push(run);
    return run;
  }

  /** The run's status on the server. */
  async status(run: RunInfo): Promise<string> {
    return (await (await this.api.get(`/api/runs/${run.id}`)).json()).status as string;
  }

  /** Wait until the run is finished on the server and its "View this run" link is on the page. */
  async finished(run: RunInfo): Promise<string> {
    await expect.poll(async () => (await (await this.api.get(`/api/runs/${run.id}`)).json()).status, { timeout: 60_000 })
      .toMatch(/^(done|failed|stopped|declined)$/);
    await expect(this.page.locator(`.run-link[data-run="${run.n}"]`)).toBeVisible();
    return (await (await this.api.get(`/api/runs/${run.id}`)).json()).status as string;
  }

  /**
   * Record every class a strip node takes from now on. In reduced motion a node can be active for about 40 ms,
   * which is shorter than an expect() poll, so a live state is asserted from this record instead.
   */
  async trackNodes(): Promise<() => Promise<Record<string, string[]>>> {
    await this.page.evaluate(() => {
      const w = window as unknown as { __nodes: Record<string, string[]> };
      w.__nodes = {};
      const push = (k: string, cls: string) => {
        const seen = (w.__nodes[k] ??= []);
        if (seen[seen.length - 1] !== cls) seen.push(cls);
      };
      const scan = () => {
        for (const el of document.querySelectorAll("#b-strip [data-node]")) push(el.getAttribute("data-node") ?? "", el.className);
      };
      // A class can change twice between two callbacks: each mutation's oldValue keeps the one in between.
      new MutationObserver((ms) => {
        for (const m of ms) {
          const el = m.target as Element;
          if (m.type === "attributes" && m.oldValue != null && el.matches?.("#b-strip [data-node]")) push(el.getAttribute("data-node") ?? "", m.oldValue);
        }
        scan();
      }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"], attributeOldValue: true });
      scan();
    });
    return () => this.page.evaluate(() => (window as unknown as { __nodes: Record<string, string[]> }).__nodes);
  }

  /**
   * Record every caption `#b-cap` shows from now on. A caption is replaced by the next step's within a few
   * dwells, so one that isn't the run's last is asserted from this record. The caption already on the bench
   * (the previous run's) isn't recorded, also when the new run's bench shows it again before its first caption.
   */
  async trackCaptions(): Promise<() => Promise<string[]>> {
    await this.page.evaluate(() => {
      const w = window as unknown as { __caps: string[] };
      w.__caps = [];
      const t0 = document.querySelector("#b-cap")?.textContent ?? "";
      const scan = () => {
        const el = document.querySelector("#b-cap");
        const t = el?.textContent ?? "";
        if (!t || (t === t0 && w.__caps.length === 0)) return;
        if (w.__caps[w.__caps.length - 1] !== t) w.__caps.push(t);
      };
      new MutationObserver(scan).observe(document.body, { subtree: true, childList: true, characterData: true });
    });
    return () => this.page.evaluate(() => (window as unknown as { __caps: string[] }).__caps);
  }

  /** Record the method, path and body of every API request the page sends from now on. */
  recordRequests(): { method: string; path: string; body: unknown }[] {
    const seen: { method: string; path: string; body: unknown }[] = [];
    this.page.on("request", (r) => {
      const url = new URL(r.url());
      if (!url.pathname.startsWith("/api/")) return;
      let body: unknown = null;
      try {
        body = r.postDataJSON();
      } catch {
        body = r.postData();
      }
      seen.push({ method: r.method(), path: url.pathname, body });
    });
    return seen;
  }

  async vaultNames(): Promise<string[]> {
    const v = (await (await this.api.get("/api/vault")).json()) as { tools: { name: string }[] };
    return v.tools.map((t) => t.name);
  }

  /** Remove a tool if present (set-up only). */
  async dropTool(name: string): Promise<void> {
    const r = await this.api.delete(`/api/vault/${name}`);
    expect([204, 404]).toContain(r.status());
  }

  async setAskBeforeExec(on: boolean): Promise<void> {
    await this.api.patch("/api/settings", { data: { ask_before_exec: on } });
  }

  dotenv(): string {
    return readFileSync(DOTENV, "utf-8");
  }

  /**
   * Stop any run left going, so the next test isn't blocked by 409 run_active. Every session's runs are
   * read from the API, so a run this test didn't start through ask() (a retry chip, a 409 re-attach) is
   * stopped too.
   */
  async cleanup(): Promise<void> {
    const sessions = (await (await this.api.get("/api/sessions")).json()) as { id: string }[];
    for (const s of sessions) {
      const { runs } = (await (await this.api.get(`/api/sessions/${s.id}`)).json()) as { runs: { id: string; status: string }[] };
      for (const r of runs) if (r.status === "running" || r.status === "waiting") await this.api.post(`/api/runs/${r.id}/stop`);
    }
    await this.setAskBeforeExec(true);
  }
}

/** The final state of a Caesar forge with one retry (01-caesar's forge test, and 06's reload into one). */
export async function expectCaesarForged(page: Page): Promise<void> {
  for (const [k, s] of Object.entries({ planner: "done", forger: "forge", tester: "forge", human: "skip", learn: "done", executor: "done", answer: "answer" }))
    await expect(page.locator(`[data-node="${k}"]`)).toHaveClass(new RegExp(`\\b${s}\\b`));
  const talos = page.locator(".msg.talos").last();
  await expect(talos).toContainText('"TALOS AGENT" encrypted with a shift of 7 is AHSVZ HNLUA.');
  await expect(talos.locator(".chip.forged")).toHaveText("Forged caesar_cipher");
}

export const test = base.extend<{ app: LiveApp }>({
  app: async ({ page, request }, use) => {
    const app = new LiveApp(page, request);
    await app.open();
    await use(app);
    await app.cleanup();
  },
});
export { expect };
