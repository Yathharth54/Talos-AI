import { test, expect } from "@playwright/test";
import { bootFrozen } from "../support/clock";

const size = (name: string) => name.split("-")[1];

test("03 idle bench", async ({ page }, info) => {
  await bootFrozen(page);
  await expect(page).toHaveScreenshot(`03-idle-${size(info.project.name)}.png`, { fullPage: true });
});
