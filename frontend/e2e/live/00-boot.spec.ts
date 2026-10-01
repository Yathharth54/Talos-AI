import { test, expect } from "./fixtures";

test("live mode boots into a session with no Demo controls", async ({ app }) => {
  const { page } = app;
  await expect(page.locator("#demo-toggle")).toHaveCount(0);
  await expect(page.locator(".top-right .model")).not.toHaveText("");
  await expect(page.locator("#view-workbench")).toBeVisible();
});
