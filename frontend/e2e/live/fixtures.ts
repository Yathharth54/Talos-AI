import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// frontend/ is an ES module package, so there is no __dirname. npm scripts run in frontend/ (part A's convention).
export const DOTENV = resolve(process.cwd(), ".e2e-tmp/.env");

type RunInfo = { id: string; n: number; status: string };

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
    const body = (await (await posted).json()) as { run: RunInfo };
    this.runs.push(body.run);
    return body.run;
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
      const scan = () => {
        for (const el of document.querySelectorAll("#b-strip [data-node]")) {
          const k = el.getAttribute("data-node") ?? "";
          const seen = (w.__nodes[k] ??= []);
          if (seen[seen.length - 1] !== el.className) seen.push(el.className);
        }
      };
      new MutationObserver(scan).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
      scan();
    });
    return () => this.page.evaluate(() => (window as unknown as { __nodes: Record<string, string[]> }).__nodes);
  }

  /**
   * Record every caption `#b-cap` shows from now on. A caption is replaced by the next step's within a few
   * dwells, so one that isn't the run's last is asserted from this record.
   */
  async trackCaptions(): Promise<() => Promise<string[]>> {
    await this.page.evaluate(() => {
      const w = window as unknown as { __caps: string[] };
      w.__caps = [];
      const scan = () => {
        const t = document.querySelector("#b-cap")?.textContent ?? "";
        if (t && w.__caps[w.__caps.length - 1] !== t) w.__caps.push(t);
      };
      new MutationObserver(scan).observe(document.body, { subtree: true, childList: true, characterData: true });
      scan();
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

  /** Stop any run this test left going, so the next test isn't blocked by 409 run_active. */
  async cleanup(): Promise<void> {
    for (const run of this.runs) {
      const s = (await (await this.api.get(`/api/runs/${run.id}`)).json()).status as string;
      if (s === "running" || s === "waiting") await this.api.post(`/api/runs/${run.id}/stop`);
    }
    await this.setAskBeforeExec(true);
  }
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
