import { expect, type Page, type TestInfo } from "@playwright/test";

/** `03-idle` on `ref-desktop` → `03-idle-desktop.png`, shared by the ref and demo projects. */
export const name = (n: string, info: TestInfo) => `${n}-${info.project.name.split("-")[1]}.png`;

/** Full-page screenshot compared against the reference's shot of the same state. */
export async function shot(page: Page, n: string, info: TestInfo): Promise<void> {
  await expect(page).toHaveScreenshot(name(n, info), { fullPage: true });
}

/** Click, then let click-started timers (a tab's `panel-in`, the indicator) settle the same way on both pages. */
export async function tap(page: Page, selector: string): Promise<void> {
  await page.locator(selector).click();
  await page.clock.runFor(50);
}

/** Open a top-level view from the header nav. */
export async function nav(page: Page, view: "workbench" | "vault" | "sessions" | "settings"): Promise<void> {
  await tap(page, `.nav a[data-view="${view}"]`);
}
