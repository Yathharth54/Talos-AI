import { test, expect, expectCaesarForged } from "./fixtures";
import { Q } from "../support/queries";
import { tabTo } from "../support/keyboard";

// Desktop only, and no mouse calls at all: only page.keyboard and tabTo.
test.describe.serial("Keyboard only", () => {
  test("Caesar by keyboard", async ({ app, page }) => {
    await app.dropTool("caesar_cipher");
    // Boot opens the newest session with runs; the suggestions only show in an empty one, so open one by keyboard.
    if ((await page.locator(".try").count()) === 0) {
      await tabTo(page, "#new-session");
      await page.keyboard.press("Enter");
      await expect(page.locator(".empty-convo")).toBeVisible();
    }
    await tabTo(page, '.try[data-suggest="0"]');
    const before = await page.locator(".run-link").count();
    await page.keyboard.press("Enter");
    await expect(page.locator(".run-link")).toHaveCount(before + 1);
    // The run is finished when the strip is in its final state and the composer is free again.
    await expectCaesarForged(page);
    await expect(page.locator("#ask")).toBeEnabled();
    const link = page.locator(".run-link").last();
    const n = (await link.getAttribute("data-run")) ?? "";
    await tabTo(page, `.run-link[data-run="${n}"]`);
    await page.keyboard.press("Enter");
    await expect(page.locator(`.run-link[data-run="${n}"]`)).toHaveAttribute("aria-current", "true");
    await tabTo(page, '[data-tab="code"]');
    await page.keyboard.press("Enter");
    await expect(page.locator('[data-tab="code"]')).toHaveAttribute("aria-selected", "true");
    // The bench's code panel; the chat's forged-tool preview is a second .code-body ("Source code preview").
    const code = '.code-body[aria-label="Source code"]';
    await tabTo(page, code);
    await expect(page.locator(code)).toHaveAttribute("tabindex", "0");
    await tabTo(page, "#ask");
    await page.keyboard.type(Q.reuse);
    await page.keyboard.press("Enter");
    await expect(page.locator(".run-link")).toHaveCount(before + 2);
    await expect(page.locator(".msg.talos").last()).toContainText("It decrypts to TALOS AGENT.");
    await expect(page.locator("#ask")).toBeEnabled();
  });

  test("approval dialog by keyboard", async ({ app, page }) => {
    void app; // the fixture opens the app
    await tabTo(page, "#ask");
    await page.keyboard.type(Q.python);
    await page.keyboard.press("Enter");
    const dlg = page.locator(".dialog");
    await expect(page.locator('[data-d="no"]')).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dlg.locator('[data-d="yes"]')).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dlg.locator('[data-d="settings"]')).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dlg.locator('[data-d="no"]')).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(dlg.locator('[data-d="settings"]')).toBeFocused();
    // The brief says Shift+Tab twice here; the order is Don't run, Run code, Settings link, so once is Run code.
    await page.keyboard.press("Shift+Tab");
    await expect(dlg.locator('[data-d="yes"]')).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(dlg).toHaveCount(0);
    await expect(page.locator("#b-panel .fig:not(.alert) .result")).toHaveText("5050");
    await expect(page.locator("#ask")).toBeFocused();
  });

  test("key dialog by keyboard", async ({ app, page }) => {
    await app.dropTool("get_current_temperature");
    await tabTo(page, "#ask");
    await page.keyboard.type(Q.weather);
    await page.keyboard.press("Enter");
    await expect(page.locator("#dlg-key")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#dlg-err")).toHaveText("Paste the key first, or choose Skip.");
    await expect(page.locator("#dlg-key")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.locator('[data-d="skip"]')).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator(".dialog")).toHaveCount(0);
    await expect(page.locator(".fig.alert .result")).toHaveText("RuntimeError: OPENWEATHERMAP_API_KEY is not set");
    await expect(page.locator('[data-node="executor"]')).toHaveClass(/\bfail\b/);
  });

  test("Esc cancels the approval", async ({ app, page }) => {
    void app;
    await tabTo(page, "#ask");
    await page.keyboard.type(Q.python);
    await page.keyboard.press("Enter");
    await expect(page.locator(".dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".dialog")).toHaveCount(0);
    await expect(page.locator(".node.stopped")).not.toHaveCount(0);
    await expect(page.locator("#ask")).toBeEnabled();
  });

  test("reader by keyboard", async ({ app, page }) => {
    void app;
    await tabTo(page, 'a[data-view="vault"]');
    await page.keyboard.press("Enter");
    await expect(page.locator("#view-vault")).toBeVisible();
    await tabTo(page, '[data-tool-btn="caesar_cipher"]');
    await page.keyboard.press("Enter");
    await expect(page.locator(".v-detail h2")).toHaveText("caesar_cipher");
    await expect(page.locator(".v-detail figure.code-read")).toBeVisible();
    await tabTo(page, "[data-read-src]");
    await page.keyboard.press("Enter");
    await expect(page.locator(".dialog.reader")).toBeVisible();
    await expect(page.locator('.dialog.reader [data-r="close"]')).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.locator(".dialog")).toHaveCount(0);
    await expect(page.locator("[data-read-src]")).toBeFocused();
  });
});
