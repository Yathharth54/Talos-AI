import { test, expect, expectCaesarForged } from "./fixtures";
import { Q } from "../support/queries";

test.describe.serial("Caesar: forge, reuse, failure and prune", () => {
  test("forge with one retry", async ({ app, page }) => {
    await app.dropTool("caesar_cipher");
    const nodes = await app.trackNodes();
    const run = await app.ask(Q.forge);
    await app.finished(run);
    expect((await nodes()).planner?.some((c) => /\bactive\b/.test(c))).toBe(true);
    await expectCaesarForged(page);
    await expect(page.locator(".banner:not(.removed)")).toContainText("caesar_cipher is in the vault");
    await expect(page.locator("#vault-badge")).toBeVisible();
    await page.locator('[data-tab="attempts"]').click();
    await expect(page.locator(".attempts li")).toHaveCount(2);
    await expect(page.locator(".attempts li").nth(1)).toContainText("Passed every test");
    expect(await app.vaultNames()).toContain("caesar_cipher");
  });

  test("reuse from the vault", async ({ app, page }) => {
    const run = await app.ask(Q.reuse);
    await app.finished(run);
    await expect(page.locator('[data-node="vault"]')).toHaveClass(/\bdone\b/);
    await expect(page.locator('[data-node="skip"]')).toHaveClass(/\bskip\b/);
    const talos = page.locator(".msg.talos").last();
    await expect(talos).toContainText("It decrypts to TALOS AGENT.");
    await expect(talos.locator(".chip.reused")).toHaveText("Reused caesar_cipher from the vault");
    // The reference's reuse Call tab (inventory item 14): a full-size result and the tool's record row.
    await page.locator('[data-tab="call"]').click();
    await expect(page.locator("#b-panel .fig:not(.alert) .result")).toHaveText("'TALOS AGENT'");
    await expect(page.locator("#b-panel .result.small")).toHaveCount(0);
    await expect(page.locator("#b-panel .record")).toBeVisible();
    await expect(page.locator("#b-panel .record")).toContainText("including this one");
    await page.locator('[data-tab="log"]').click();
    await expect(page.locator("#term")).toHaveClass(/\bwarm\b/);
    await expect(page.locator("#term-status")).toHaveText("0 tools forged");
  });

  test("a word shift fails once, then the second failure prunes the tool", async ({ app, page }) => {
    let run = await app.ask(Q.fail);
    await app.finished(run);
    await expect(page.locator('[data-node="executor"]')).toHaveClass(/\bfail\b/);
    await expect(page.locator(".fig.alert .result")).toHaveText("TypeError: shift must be an int, got str");
    await expect(page.locator(".args .bad")).toHaveText('"seven"');
    await expect(page.getByRole("button", { name: "Ask again with shift 7" })).toBeVisible();
    await expect(page.locator(".msg.talos").last().locator(".chip.failed")).toHaveText("caesar_cipher raised a TypeError");

    run = await app.ask(Q.fail);
    await app.finished(run);
    await expect(page.locator(".banner.removed")).toContainText("caesar_cipher was removed from the vault");
    expect(await app.vaultNames()).not.toContain("caesar_cipher");
  });
});
