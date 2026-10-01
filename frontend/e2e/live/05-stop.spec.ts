import { test, expect } from "./fixtures";
import { Q } from "../support/queries";

test.describe.serial("Stop", () => {
  test("stop a run that is still going on the server", async ({ app, page }) => {
    // serve_backend.py paces the fake graph (TALOS_FAKE_EVENT_DELAY_MS), so a Caesar forge is still
    // running on the server while the page shows the Forger working.
    await app.dropTool("caesar_cipher");
    const run = await app.ask(Q.forge);
    await expect(page.locator('.node.active[data-node="forger"]')).toBeVisible();
    expect(await app.status(run)).toBe("running");
    await page.getByRole("button", { name: "Stop run" }).click();
    // "stopped", not "done": the Stop landed while the run was going.
    expect(await app.finished(run)).toBe("stopped");

    await expect(page.locator(".node.stopped")).not.toHaveCount(0);
    await expect(page.locator("#b-cap")).toHaveText("You stopped this run. Nothing was saved to the vault.");
    const talos = page.locator(".msg.talos").last();
    await expect(talos.locator(".note").last()).toHaveText("Stopped. Ask again whenever you're ready.");
    await expect(talos.locator(".chip")).toHaveCount(0);
    await page.locator('[data-tab="log"]').click();
    await expect(page.locator(".term-body .ln").filter({ hasText: "stopped by you" })).toHaveCount(1);
    await expect(page.locator("#send")).toHaveText("Send");
  });

  test("stop during a run paused on the server", async ({ app, page }) => {
    // The weather forge pauses on the server for its key right after the forge.
    await app.dropTool("get_current_temperature");
    const caps = await app.trackCaptions();
    const run = await app.ask(Q.weather);
    await expect(page.locator('.node.active[data-node="forger"]')).toBeVisible();
    const stopped = page.waitForRequest((r) => r.url().endsWith(`/api/runs/${run.id}/stop`) && r.method() === "POST");
    await page.getByRole("button", { name: "Stop run" }).click();
    await stopped;
    expect(await app.finished(run)).toBe("stopped");

    await expect(page.locator(".node.stopped")).not.toHaveCount(0);
    await expect(page.locator("#b-cap")).toHaveText("You stopped this run. Nothing was saved to the vault.");
    expect(await caps()).toContain("You stopped this run. Nothing was saved to the vault.");
    await expect(page.locator(".dialog")).toHaveCount(0);
    await expect(page.locator(".msg.talos").last().locator(".note").last()).toHaveText("Stopped. Ask again whenever you're ready.");
    await page.locator('[data-tab="log"]').click();
    await expect(page.locator(".term-body .ln").filter({ hasText: "stopped by you" })).toHaveCount(1);
    expect(await app.vaultNames()).not.toContain("get_current_temperature");
    await expect(page.locator("#ask")).toBeEnabled();
    await expect(page.locator("#send")).toHaveText("Send");
    await expect(page.locator("#send")).toBeEnabled();
  });

  test("Esc during a pause stops the run, never resumes it", async ({ app, page }) => {
    await app.setAskBeforeExec(true);
    const run = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    const seen = app.recordRequests();
    const stopped = page.waitForRequest((r) => r.url().endsWith(`/api/runs/${run.id}/stop`) && r.method() === "POST");
    await page.keyboard.press("Escape");
    await stopped;
    expect(await app.finished(run)).toBe("stopped");
    await expect(page.locator(".dialog")).toHaveCount(0);
    await expect(page.locator("#ask")).toBeFocused();
    expect(seen.filter((r) => r.path.endsWith("/stop"))).toHaveLength(1);
    expect(seen.filter((r) => r.path.endsWith("/resume"))).toHaveLength(0);
  });

  test("the composer is busy while a run is going", async ({ app, page }) => {
    await app.setAskBeforeExec(true);
    const run = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    await expect(page.locator("#send")).toHaveText("Working");
    await expect(page.locator("#ask")).toBeDisabled();
    await expect(page.locator("#composer-hint")).toHaveText("Stop the run to ask something else");
    await page.locator(".dialog").getByRole("button", { name: "Run code" }).click();
    expect(await app.finished(run)).toBe("done");
    await expect(page.locator("#send")).toHaveText("Send");
  });
});
