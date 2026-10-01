import type { Page } from "@playwright/test";
import { test, expect, expectCaesarForged, type LiveApp, type RunInfo } from "./fixtures";
import { Q } from "../support/queries";

async function reload(app: LiveApp): Promise<void> {
  await app.page.reload();
  await expect(app.page.locator("body")).not.toHaveClass(/booting/);
}

/** What a duplicated backlog would repeat: the conversation's messages and the run log's lines. */
type Shown = { you: number; talos: number; log: string[] };

/**
 * Open the Log tab and read the conversation and the log. A paused run's dialog covers the tabs, so the tab
 * gets a plain click event instead of a pointer click. A fresh log line decodes its text for up to 480 ms, so
 * the read waits until two reads 600 ms apart agree.
 */
async function shown(page: Page): Promise<Shown> {
  // With one tab (a run that has only its log so far) there's no tab bar, and the log is the panel.
  const tab = page.locator('[data-tab="log"]');
  if (await tab.count()) await tab.dispatchEvent("click");
  await expect(page.locator("#term")).toBeVisible();
  const read = async (): Promise<Shown> => ({
    you: await page.locator(".msg.you").count(),
    talos: await page.locator(".msg.talos").count(),
    log: await page.locator(".term-body .ln").allTextContents(),
  });
  let last = await read();
  await expect
    .poll(async () => {
      await page.waitForTimeout(600);
      const now = await read();
      const same = JSON.stringify(now) === JSON.stringify(last);
      last = now;
      return same;
    })
    .toBe(true);
  return last;
}

/** Reload, open the finished run from its "View this run" link (a replay of its event log) and read it. */
async function replayed(app: LiveApp, run: RunInfo): Promise<Shown> {
  await reload(app);
  await app.page.locator(`.run-link[data-run="${run.n}"]`).click();
  return shown(app.page);
}

/** The open session is the run's: the Sessions page marks its card "Now". */
async function expectCurrentSession(page: Page, run: RunInfo): Promise<void> {
  await page.locator('.nav a[data-view="sessions"]').click();
  const now = page.locator("article.sess", { has: page.locator(".live") });
  await expect(now).toHaveCount(1);
  await expect(now.locator("[data-open-session]")).toHaveAttribute("data-open-session", run.sessionId);
  await page.locator('.nav a[data-view="workbench"]').click();
  await expect(page.locator("#view-workbench")).toBeVisible();
}

test.describe.serial("Reload during a run", () => {
  test("the approval dialog survives a reload", async ({ app, page }) => {
    await app.setAskBeforeExec(true);
    const [you, talos] = [await page.locator(".msg.you").count(), await page.locator(".msg.talos").count()];
    const run = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    const code = await page.locator(".dialog pre").textContent();
    const before = await shown(page);
    expect([before.you, before.talos]).toEqual([you + 1, talos + 1]);
    expect(before.log.length).toBeGreaterThan(0);

    // The reload re-attaches to the run, which is waiting on the server: its backlog is applied once.
    await reload(app);
    await expect(page.locator('[data-node="executor"] .nl')).toHaveText("Executor, waiting for you");
    await expect(page.locator(".dialog")).toHaveCount(1);
    await expect(page.locator(".dialog pre")).toHaveText(code ?? "");
    // Nothing to wait for when proving the dialog doesn't open twice: 500 ms is over three times
    // the Workbench's BACKLOG_QUIET_MS (150), after which the one GET /api/runs/{id} opens it.
    await page.waitForTimeout(500);
    await expect(page.locator(".dialog")).toHaveCount(1);
    expect(await shown(page)).toEqual(before);

    await page.locator(".dialog").getByRole("button", { name: "Run code" }).click();
    expect(await app.finished(run)).toBe("done");
    await expect(page.locator("#b-panel .fig:not(.alert) .result")).toHaveText("5050");
    const after = await shown(page);
    expect([after.you, after.talos]).toEqual([you + 1, talos + 1]);
    // "paused for approval" was popped for "running", which was popped for "done".
    expect(after.log).toHaveLength(before.log.length);
    expect(after.log.at(-1)).toMatch(/execute\s*done/);
    await expectCurrentSession(page, run);

    // The re-attached run shows exactly what a replay of its event log shows.
    expect(await replayed(app, run)).toEqual(after);
  });

  test("the key dialog survives a reload", async ({ app, page }) => {
    await app.dropTool("get_current_temperature");
    const run = await app.ask(Q.weather);
    await expect(page.locator("#dlg-key")).toBeVisible();

    await reload(app);
    await expect(page.locator("#dlg-key")).toBeVisible();
    await expect(page.locator("#dlg-key")).toBeFocused();
    await expect(page.locator(".dialog")).toHaveCount(1);
    await page.locator(".dialog").getByRole("button", { name: "Skip" }).click();
    expect(await app.finished(run)).toBe("done");
    const after = await shown(page);
    await expectCurrentSession(page, run);
    expect(await replayed(app, run)).toEqual(after);
  });

  test("a reload mid-run re-attaches without duplicates", async ({ app, page }) => {
    await app.dropTool("caesar_cipher");
    const [you, talosMsgs] = [await page.locator(".msg.you").count(), await page.locator(".msg.talos").count()];
    const run = await app.ask(Q.forge);
    await expect(page.locator('.node.active[data-node="forger"]')).toBeVisible();
    // serve_backend.py paces the fake graph, so the run is still going on the server: the reload
    // re-attaches to its live stream (an EventSource), rather than replaying a finished log (a fetch).
    expect(await app.status(run)).toBe("running");
    const attached = page.waitForRequest((r) => r.url().includes(`/api/runs/${run.id}/events`) && r.resourceType() === "eventsource");

    await reload(app);
    await attached;
    expect(await app.finished(run)).toBe("done");
    // The same final state as 01-caesar's forge.
    await expectCaesarForged(page);
    expect(await app.vaultNames()).toContain("caesar_cipher");

    // One user message and one Talos message for this run.
    await expect(page.locator(".msg.you")).toHaveCount(you + 1);
    await expect(page.locator(".msg.talos")).toHaveCount(talosMsgs + 1);
    await expect(page.locator(`.run-link[data-run="${run.n}"]`)).toHaveCount(1);

    const after = await shown(page);
    expect(after.log.length).toBeGreaterThan(0);
    // The same run replayed from its event log shows the same messages and log lines.
    expect(await replayed(app, run)).toEqual(after);
  });
});
