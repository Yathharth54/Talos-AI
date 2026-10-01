import { test } from "@playwright/test";
import { advanceUntil, bootFrozen, finishRun } from "../support/clock";
import { shot, tap } from "../support/shots";

test("05-13 the forge run, stage by stage", async ({ page }, info) => {
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="0"]');

  await advanceUntil(page, '.node.active[data-node="planner"]');
  await advanceUntil(page, ".term-body .cmd:not(:has(.caret))");
  await shot(page, "05-planning", info);

  await advanceUntil(page, '.node.active[data-node="forger"]');
  await advanceUntil(page, '.code-row[data-ln="30"]');
  await shot(page, "06-forging", info);

  await advanceUntil(page, ".tests li.failed");
  await shot(page, "07-testing-fail", info);

  await advanceUntil(page, ".code-row.changed");
  await shot(page, "08-retry", info);

  await advanceUntil(page, ".smoke-body .gold");
  await shot(page, "09-smoke-running", info);
  await advanceUntil(page, ".smoke-body:not(:has(.gold))");
  await shot(page, "09-smoke-done", info);

  await advanceUntil(page, '.node.skip[data-node="human"]');
  await shot(page, "10-human-skip", info);

  await advanceUntil(page, ".banner:not(.removed)");
  await shot(page, "11-saved-banner", info);

  await advanceUntil(page, ".args dt:nth-of-type(2)");
  await shot(page, "12-executing", info);

  await finishRun(page, 0);
  await shot(page, "13-answer", info);
});
