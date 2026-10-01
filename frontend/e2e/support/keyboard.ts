import type { Page } from "@playwright/test";

/** Press Tab (or Shift+Tab) until `selector` has focus. Fails after `max` presses. */
export async function tabTo(page: Page, selector: string, opts: { back?: boolean; max?: number } = {}): Promise<void> {
  const key = opts.back ? "Shift+Tab" : "Tab";
  for (let i = 0; i < (opts.max ?? 80); i++) {
    if (await page.locator(selector).evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press(key);
  }
  // Checked once: toBeFocused() would auto-wait the whole expect timeout for a focus no key press moves.
  if (!(await page.locator(selector).evaluate((el) => el === document.activeElement).catch(() => false)))
    throw new Error(`${selector} wasn't focused after ${opts.max ?? 80} ${key} presses`);
}
