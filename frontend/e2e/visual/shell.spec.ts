import { test, expect } from "@playwright/test";
import { bootFrozen } from "../support/clock";
import { name, shot } from "../support/shots";

test("02 mid-boot", async ({ page }, info) => {
  await bootFrozen(page, 300);
  await expect(page.locator("body.booting")).toHaveCount(1);
  await shot(page, "02-boot", info);
});

test("03 idle bench", async ({ page }, info) => {
  await bootFrozen(page);
  await shot(page, "03-idle", info);
});

test("04 empty conversation", async ({ page }, info) => {
  await bootFrozen(page);
  await expect(page.locator(".convo")).toHaveScreenshot(name("04-empty-convo", info));
});
