import { test } from "@playwright/test";
import { advanceUntil, bootFrozen, finishRun } from "../support/clock";
import { shot, tap } from "../support/shots";

test("17-18 approval dialog, then declined", async ({ page }, info) => {
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="2"]');
  await advanceUntil(page, ".dialog");
  await shot(page, "17-approval", info);

  await tap(page, '[data-d="no"]');
  await finishRun(page, 0);
  await shot(page, "18-declined", info);
});

test("19-20 key dialog, empty-key error, then skipped", async ({ page }, info) => {
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="3"]');
  await advanceUntil(page, "#dlg-key");
  await shot(page, "19-key-dialog", info);

  await page.locator("#dlg-key").press("Enter");
  await advanceUntil(page, "#dlg-err:not(:empty)");
  await shot(page, "19-key-empty-error", info);

  await tap(page, '[data-d="skip"]');
  await finishRun(page, 0);
  await shot(page, "20-key-skipped-failing", info);
});
