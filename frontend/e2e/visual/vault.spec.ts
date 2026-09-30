import { test } from "@playwright/test";
import { advanceUntil, bootFrozen, finishRun } from "../support/clock";
import { nav, shot, tap } from "../support/shots";

test("25-28 vault table, search and filters, detail, reader", async ({ page }, info) => {
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="0"]');
  await finishRun(page, 0);
  await nav(page, "vault");
  await page.clock.runFor(1000);
  await shot(page, "25-vault-table", info);

  const search = page.locator("#v-search");
  await search.fill("cipher");
  await page.clock.runFor(50);
  await shot(page, "26-search", info);
  await search.fill("");
  await tap(page, '[data-filter="web"]');
  await shot(page, "26-filter-web", info);
  await tap(page, '[data-filter="failed"]');
  await shot(page, "26-filter-failed", info);
  await tap(page, '[data-filter="all"]');
  await search.fill("zzzz");
  await page.clock.runFor(50);
  await shot(page, "26-empty", info);

  // Clear the search again so the rows below are in the table.
  await search.fill("");
  await page.clock.runFor(50);
  await tap(page, '[data-tool-btn="nth_fibonacci"]');
  await shot(page, "27-detail", info);
  await tap(page, "[data-remove-tool]");
  await shot(page, "27-remove-confirm", info);

  await tap(page, '[data-tool-btn="caesar_cipher"]');
  await tap(page, "[data-read-src]");
  await advanceUntil(page, ".dialog.reader");
  await shot(page, "28-reader", info);
});
