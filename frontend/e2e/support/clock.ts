import type { Page } from "@playwright/test";
import { pinFonts } from "./fonts";
import { FREEZE_CSS } from "./freeze";

/** 30 Sep 2026, 14:20 UTC: "Today", after the seeded sessions on 28 Sep. */
export const T0 = Date.parse("2026-09-30T14:20:00Z");

/** Open the page with pinned fonts and the clock paused, let boot finish, freeze animations, wait for fonts. */
export async function bootFrozen(page: Page, settleMs = 2000): Promise<void> {
  await pinFonts(page);
  await page.clock.install({ time: T0 });
  await page.clock.pauseAt(T0 + 10);
  await page.goto("");
  await page.addStyleTag({ content: FREEZE_CSS });
  await page.clock.runFor(settleMs);
  await page.evaluate(() => document.fonts.ready);
}

/** Advance the paused clock in 10 ms steps until `selector` matches (or throw). */
export async function advanceUntil(page: Page, selector: string, maxMs = 60_000): Promise<void> {
  for (let t = 0; t <= maxMs; t += 10) {
    if ((await page.locator(selector).count()) > 0) return;
    await page.clock.runFor(10);
  }
  throw new Error(`never reached: ${selector}`);
}

/** Type into the composer and send, the way a person does. */
export async function ask(page: Page, text: string): Promise<void> {
  await page.locator("#ask").fill(text);
  await page.locator("#ask").press("Enter");
}

/** Advance until the newest Talos message has its "View this run" link (the run finished). */
export async function finishRun(page: Page, runsSoFar: number): Promise<void> {
  await advanceUntil(page, `.msg.talos .run-link >> nth=${runsSoFar}`);
}
