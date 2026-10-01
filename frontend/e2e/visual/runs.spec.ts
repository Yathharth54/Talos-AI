import { test } from "@playwright/test";
import { advanceUntil, ask, bootFrozen, finishRun } from "../support/clock";
import { Q } from "../support/queries";
import { shot, tap } from "../support/shots";

test("14-16, 22 reuse, tool failure, pruning and earlier runs", async ({ page }, info) => {
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="0"]');
  await finishRun(page, 0);

  await ask(page, Q.reuse);
  await finishRun(page, 1);
  await shot(page, "14-reuse", info);
  await tap(page, '[data-tab="log"]');
  await shot(page, "14-reuse-log", info);

  await ask(page, Q.fail);
  await finishRun(page, 2);
  await shot(page, "15-tool-failure", info);

  await ask(page, Q.fail);
  await finishRun(page, 3);
  await advanceUntil(page, ".banner.removed");
  await shot(page, "16-pruned", info);

  await tap(page, ".run-link >> nth=0");
  await shot(page, "22-view-earlier-run", info);
  await tap(page, '[data-tab="log"]');
  await tap(page, ".earlier button >> nth=0");
  await shot(page, "22-earlier-list", info);
});

test("21 stopped mid-forge", async ({ page }, info) => {
  // Known reference defect, open for the owner (task 7 report): the reference's stopRun() clears the
  // pending wait()'s timer, so that promise never settles and the flow's `finally` never runs. The
  // reference stays on "Working" with no "View this run" forever; the app finishes the stopped run.
  // `test.fail` keeps the comparison running, so this turns red the day the two agree.
  test.fail(info.project.name.startsWith("demo-"), "reference never finishes a stopped run");
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="0"]');
  await advanceUntil(page, '.node.active[data-node="forger"]');
  await tap(page, '[data-action="stop"]');
  await advanceUntil(page, ".msg.talos .note");
  await shot(page, "21-stopped", info);
});
