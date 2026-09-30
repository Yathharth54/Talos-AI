import { expect, type Page } from "@playwright/test";

/** Press Tab (or Shift+Tab) until `selector` has focus. Fails after `max` presses. */
export async function tabTo(page: Page, selector: string, opts: { back?: boolean; max?: number } = {}): Promise<void> {
  const key = opts.back ? "Shift+Tab" : "Tab";
  for (let i = 0; i < (opts.max ?? 80); i++) {
    if (await page.locator(selector).evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press(key);
  }
  await expect(page.locator(selector)).toBeFocused();
}
