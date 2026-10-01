import { test } from "@playwright/test";
import { bootFrozen, finishRun } from "../support/clock";
import { nav, shot, tap } from "../support/shots";

test("23 reading an old session", async ({ page }, info) => {
  await bootFrozen(page);
  await nav(page, "sessions");
  await tap(page, '[data-open-session="seed-fib"]');
  await shot(page, "23-old-session", info);
});

test("29 sessions after one forge run", async ({ page }, info) => {
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="0"]');
  await finishRun(page, 0);
  await nav(page, "sessions");
  await shot(page, "29-sessions", info);
});

test("30 settings, then ask-before-running off", async ({ page }, info) => {
  await bootFrozen(page);
  await nav(page, "settings");
  await shot(page, "30-settings", info);
  await tap(page, "#ask-switch");
  await shot(page, "30-settings-off", info);
});
