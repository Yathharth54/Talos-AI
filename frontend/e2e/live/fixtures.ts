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
