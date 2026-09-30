import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

async function reload(app: LiveApp): Promise<void> {
  await app.page.reload();
  await expect(app.page.locator("body")).not.toHaveClass(/booting/);
}

test.describe.serial("Reload during a run", () => {
  test("the approval dialog survives a reload", async ({ app, page }) => {
    await app.setAskBeforeExec(true);
    const run = await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    const code = await page.locator(".dialog pre").textContent();
    const title = await page.locator("#session-title").textContent();

    await reload(app);
    await expect(page.locator("#session-title")).toHaveText(title ?? "");
    await expect(page.locator('[data-node="executor"] .nl')).toHaveText("Executor, waiting for you");
    await expect(page.locator(".dialog")).toHaveCount(1);
    await expect(page.locator(".dialog pre")).toHaveText(code ?? "");
    // The dialog came back once, and stays the only one (it isn't opened again by the replayed interrupt).
    await page.waitForTimeout(500);
    await expect(page.locator(".dialog")).toHaveCount(1);

    await page.locator(".dialog").getByRole("button", { name: "Run code" }).click();
    expect(await app.finished(run)).toBe("done");
    await expect(page.locator("#b-panel .fig:not(.alert) .result")).toHaveText("5050");
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
  });

  test("a reload mid-run re-attaches without duplicates", async ({ app, page }) => {
    await app.dropTool("caesar_cipher");
    const [you, talosMsgs] = [await page.locator(".msg.you").count(), await page.locator(".msg.talos").count()];
    const run = await app.ask(Q.forge);
    await expect(page.locator('.node.active[data-node="forger"]')).toBeVisible();

    await reload(app);
    await app.finished(run);
    // The same final state as 01-caesar's forge.
    for (const [k, s] of Object.entries({ planner: "done", forger: "forge", tester: "forge", human: "skip", learn: "done", executor: "done", answer: "answer" }))
      await expect(page.locator(`[data-node="${k}"]`)).toHaveClass(new RegExp(`\\b${s}\\b`));
    const talos = page.locator(".msg.talos").last();
    await expect(talos).toContainText('"TALOS AGENT" encrypted with a shift of 7 is AHSVZ HNLUA.');
    await expect(talos.locator(".chip.forged")).toHaveText("Forged caesar_cipher");
    expect(await app.vaultNames()).toContain("caesar_cipher");

    // One user message and one Talos message for this run.
    await expect(page.locator(".msg.you")).toHaveCount(you + 1);
    await expect(page.locator(".msg.talos")).toHaveCount(talosMsgs + 1);
    await expect(page.locator(`.run-link[data-run="${run.n}"]`)).toHaveCount(1);

    await page.locator('[data-tab="log"]').click();
    const lines = page.locator(".term-body .ln");
    const live = await lines.count();
    expect(live).toBeGreaterThan(0);
    // The same run replayed from its event log has exactly as many log lines.
    await reload(app);
    await page.locator(`.run-link[data-run="${run.n}"]`).click();
    await page.locator('[data-tab="log"]').click();
    await expect(lines).toHaveCount(live);
  });
});
