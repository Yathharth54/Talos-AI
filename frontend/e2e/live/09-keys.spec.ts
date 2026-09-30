import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

// The last live file: it saves a key, which the fake graph remembers until the server stops.
const KEY = "e2e-test-key";
const resumeReq = (app: LiveApp, runId: string) =>
  app.page.waitForRequest((r) => r.url().endsWith(`/api/runs/${runId}/resume`) && r.method() === "POST");

test.describe.serial("API keys", () => {
  let savedRun = "";

  test("the key dialog, an empty submit, and Skip", async ({ app, page }) => {
    await app.dropTool("get_current_temperature");
    const run = await app.ask(Q.weather);
    const dialog = page.locator(".dialog");
    await expect(page.locator("#dlg-key")).toBeVisible();
    await expect(dialog.locator("h2")).toHaveText("This tool needs an OpenWeatherMap key");
    await expect(dialog.locator('label[for="dlg-key"]')).toHaveText("OPENWEATHERMAP_API_KEY");
    await expect(dialog.locator(".d-foot")).toHaveText("If you skip, the tool is still saved to the vault, but it fails when it runs until the key is set.");

    const seen = app.recordRequests();
    await page.locator("#dlg-key").press("Enter");
    await expect(page.locator("#dlg-err")).toHaveText("Paste the key first, or choose Skip.");
    await expect(page.locator("#dlg-key")).toBeFocused();
    await page.waitForTimeout(300);
    expect(seen.filter((r) => r.path.endsWith("/resume"))).toHaveLength(0);

    const resumed = resumeReq(app, run.id);
    await dialog.getByRole("button", { name: "Skip" }).click();
    expect((await resumed).postDataJSON()).toEqual({ decision: "skip" });
    await app.finished(run);
    await expect(page.locator('[data-node="human"] .nl')).toHaveText("Human check, skipped");
    await expect(page.locator('[data-node="executor"]')).toHaveClass(/\bfail\b/);
    await expect(page.locator(".fig.alert .result")).toHaveText("RuntimeError: OPENWEATHERMAP_API_KEY is not set");
  });

  test("Save key", async ({ app, page }) => {
    await app.dropTool("get_current_temperature");
    const caps = await app.trackCaptions();
    const run = await app.ask(Q.weather);
    savedRun = run.id;
    await expect(page.locator("#dlg-key")).toBeVisible();
    await page.locator("#dlg-key").fill(KEY);
    const resumed = resumeReq(app, run.id);
    await page.locator(".dialog").getByRole("button", { name: "Save key" }).click();
    expect((await resumed).postDataJSON()).toEqual({ decision: "save", value: KEY });
    expect(await app.finished(run)).toBe("done");
    expect(await caps()).toContain("Saved OPENWEATHERMAP_API_KEY to .env. Talos won't ask again.");
    expect(await page.evaluate(() => document.body.innerHTML)).not.toContain(KEY);

    // The Earlier list leaves out the run on the bench: the next run lists this one.
    const next = await app.ask(Q.weather);
    await app.finished(next);
    await expect(page.locator(".dialog")).toHaveCount(0);
    await page.locator('[data-tab="log"]').click();
    await expect(page.locator(`.earlier button[data-run="${run.n}"] .s`)).toHaveText("1 tool forged, key saved");
  });

  test("it doesn't ask again", async ({ app, page }) => {
    const seen = app.recordRequests();
    const run = await app.ask(Q.weather);
    await app.finished(run);
    await expect(page.locator(".dialog")).toHaveCount(0);
    expect(seen.filter((r) => r.path.endsWith("/resume"))).toHaveLength(0);
    await expect(page.locator('#b-strip [data-node="vault"]')).toHaveCount(1);
    await expect(page.locator('#b-strip [data-node="forger"]')).toHaveCount(0);
  });

  test("the key goes nowhere", async ({ app, page }) => {
    expect(savedRun).not.toBe("");
    expect(await page.evaluate(() => document.body.innerHTML)).not.toContain(KEY);
    const events = await (await app.api.get(`/api/runs/${savedRun}/events?after=0`)).text();
    expect(events.length).toBeGreaterThan(0);
    expect(events).not.toContain(KEY);
    expect(app.dotenv()).toBe("");
  });
});
