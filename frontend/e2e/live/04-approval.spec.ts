import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

const resumeReq = (app: LiveApp, runId: string) =>
  app.page.waitForRequest((r) => r.url().endsWith(`/api/runs/${runId}/resume`) && r.method() === "POST");

test.describe.serial("Approvals and the Ask before running code switch", () => {
  test("approve: the code runs", async ({ app, page }) => {
    await app.setAskBeforeExec(true);
    const run = await app.ask(Q.python);
    const dialog = page.locator(".dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("h2")).toHaveText("Run this code on your machine?");
    await expect(dialog.locator(".eyebrow")).toHaveText("python_exec needs your approval");
    await expect(dialog.locator("pre")).toContainText("print(sum(range(1, 101)))");
    await expect(dialog.locator('[data-d="no"]')).toHaveText("Don't run");
    await expect(dialog.locator('[data-d="no"]')).toBeFocused();
    await expect(page.locator('[data-node="executor"] .nl')).toHaveText("Executor, waiting for you");

    const resumed = resumeReq(app, run.id);
    await dialog.getByRole("button", { name: "Run code" }).click();
    expect((await resumed).postDataJSON()).toEqual({ decision: "approve" });
    expect(await app.finished(run)).toBe("done");
    await expect(dialog).toHaveCount(0);
    await expect(page.locator("#b-panel .fig:not(.alert) .result")).toHaveText("5050");
    await expect(page.locator(".msg.talos").last()).toContainText("5050");
  });

  test("decline: nothing runs", async ({ app, page }) => {
    const run = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    const resumed = resumeReq(app, run.id);
    await page.locator(".dialog").getByRole("button", { name: "Don't run" }).click();
    expect((await resumed).postDataJSON()).toEqual({ decision: "decline" });
    expect(await app.finished(run)).toBe("declined");
    await expect(page.locator('[data-node="executor"] .nl')).toHaveText("Executor, declined");
    // The Earlier list leaves out the run on the bench, so the declined run is listed from the one before it.
    await page.locator(`.run-link[data-run="${run.n - 1}"]`).click();
    await page.locator('[data-tab="log"]').click();
    await expect(page.locator(`.earlier button[data-run="${run.n}"] .s`)).toHaveText("Declined, nothing ran");
  });

  test("the dialog's Settings link declines and opens Settings", async ({ app, page }) => {
    const run = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    const resumed = resumeReq(app, run.id);
    await page.locator(".dialog").getByRole("link", { name: "Ask before running code" }).click();
    expect((await resumed).postDataJSON()).toEqual({ decision: "decline" });
    await expect(page.locator("#view-settings")).toBeVisible();
    await expect(page.locator(".dialog")).toHaveCount(0);
    // The run link is on the Workbench, which Settings hides.
    await page.locator('.nav a[data-view="workbench"]').click();
    expect(await app.finished(run)).toBe("declined");
  });

  test("the switch turns approvals off and on", async ({ app, page }) => {
    await page.locator('.nav a[data-view="settings"]').click();
    const sw = page.locator("#ask-switch");
    await expect(sw).toHaveAttribute("aria-checked", "true");
    const patched = page.waitForRequest((r) => r.url().endsWith("/api/settings") && r.method() === "PATCH");
    await sw.click();
    expect((await patched).postDataJSON()).toEqual({ ask_before_exec: false });
    await expect(sw).toHaveAttribute("aria-checked", "false");

    await page.locator('.nav a[data-view="workbench"]').click();
    await expect(page.locator("#view-workbench")).toBeVisible();
    // The session has runs, so the bench isn't idle and there is no setup line to check (the brief's "if idle").
    if (await page.locator(".setup-line").count()) await expect(page.locator(".setup-line")).toContainText("Ask before running code is off.");

    const caps = await app.trackCaptions();
    const run = await app.ask(Q.python);
    expect(await app.finished(run)).toBe("done");
    await expect(page.locator(".dialog")).toHaveCount(0);
    expect(await caps()).toContain('Ran without asking, because "Ask before running code" is off in Settings.');
    await expect(page.locator("#b-panel .fig:not(.alert) .result")).toHaveText("5050");

    await page.locator('.nav a[data-view="settings"]').click();
    const on = page.waitForRequest((r) => r.url().endsWith("/api/settings") && r.method() === "PATCH");
    await sw.click();
    expect((await on).postDataJSON()).toEqual({ ask_before_exec: true });
    await expect(sw).toHaveAttribute("aria-checked", "true");
    await page.locator('.nav a[data-view="workbench"]').click();
    const again = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    await expect(page.locator(".dialog h2")).toHaveText("Run this code on your machine?");
    await page.locator(".dialog").getByRole("button", { name: "Don't run" }).click();
    expect(await app.finished(again)).toBe("declined");
  });
});
