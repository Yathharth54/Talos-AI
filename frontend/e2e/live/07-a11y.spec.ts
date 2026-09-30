import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

/**
 * Findings the reference itself has, measured on 1 Oct 2026 by running axe on
 * docs/superpowers/specs/reference/workbench-demo/index.html (desktop 1440 and mobile 390, same steps: a forge run,
 * a second run, the approval and key dialogs). The UI must match the reference exactly, so they are kept for parity
 * and listed for the owner (Task 12). Each is matched by what the element is in the DOM, not by axe's selector text,
 * which changes with the page's contents.
 *  - color-contrast on the code panel's line numbers (.ln), and on anything inside a dimmed earlier message (.past).
 *  - scrollable-region-focusable on #b-strip: at 390 px the step strip scrolls sideways and isn't focusable.
 */
async function inherited(page: Page, rule: string, target: string): Promise<boolean> {
  if (rule === "scrollable-region-focusable") return target === "#b-strip";
  if (rule !== "color-contrast") return false;
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    return !!el && (el.closest(".past") !== null || el.closest(".code-body") !== null);
  }, target);
}

async function noSerious(page: Page, isMobile: boolean): Promise<void> {
  let axe = new AxeBuilder({ page });
  // Reference defect, kept for parity: at 390 px the GitHub pill hides its label, so the link has no name
  // (axe link-name, serious, present in the reference itself). See plan 04b Task 10.
  if (isMobile) axe = axe.exclude('.top-right a.pill[target="_blank"]');
  const { violations } = await axe.analyze();
  const bad: string[] = [];
  for (const v of violations) {
    if (v.impact !== "serious" && v.impact !== "critical") continue;
    for (const n of v.nodes) {
      const target = n.target.join(" ");
      if (!(await inherited(page, v.id, target))) bad.push(`${v.id}: ${target}`);
    }
  }
  expect(bad).toEqual([]);
}

const nav = (page: Page, view: string) => page.locator(`.nav a[data-view="${view}"]`).click();

async function forgeCaesar(app: LiveApp): Promise<void> {
  await app.dropTool("caesar_cipher");
  await app.finished(await app.ask(Q.forge));
}

test.describe.serial("Accessibility: no serious or critical axe violations", () => {
  test("Workbench, idle", async ({ app, page }, testInfo) => {
    void app; // the fixture opens the app
    await page.locator("#new-session").click(); // boot opens the newest session with runs, so ask for an empty one
    await expect(page.locator(".empty-convo")).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });

  test("Workbench after a forge run, every tab", async ({ app, page }, testInfo) => {
    await forgeCaesar(app);
    const mobile = testInfo.project.name === "live-mobile";
    await noSerious(page, mobile);
    const ids = await page.locator("[data-tab]").evaluateAll((els) => els.map((e) => e.getAttribute("data-tab") ?? ""));
    expect(ids).toEqual(expect.arrayContaining(["code", "tests", "attempts", "log"]));
    for (const id of ids) {
      await page.locator(`[data-tab="${id}"]`).click();
      await expect(page.locator(`[data-tab="${id}"]`)).toHaveAttribute("aria-selected", "true");
      await noSerious(page, mobile);
    }
  });

  test("Vault with a tool selected", async ({ app, page }, testInfo) => {
    await nav(page, "vault");
    await page.locator('[data-tool-btn="caesar_cipher"]').click();
    await expect(page.locator(".v-detail h2")).toHaveText("caesar_cipher");
    await noSerious(page, testInfo.project.name === "live-mobile");
    void app;
  });

  test("Sessions", async ({ app, page }, testInfo) => {
    void app;
    await nav(page, "sessions");
    await expect(page.locator("section.day").first()).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });

  test("Settings", async ({ app, page }, testInfo) => {
    void app;
    await nav(page, "settings");
    await expect(page.locator("#ask-switch")).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });

  test("an old session opened", async ({ app, page }, testInfo) => {
    const sessions = async () => (await (await app.api.get("/api/sessions")).json()) as { id: string }[];
    // Set-up: make sure two sessions have runs, so one of them is an earlier session.
    while ((await sessions()).length < 2) {
      await page.locator("#new-session").click();
      await expect(page.locator(".empty-convo")).toBeVisible();
      await app.finished(await app.ask(Q.reuse));
    }
    const list = await sessions();
    await app.open(); // boot opens the newest session with runs
    await nav(page, "sessions");
    await page.locator(`[data-open-session="${list[1]!.id}"]`).click();
    await expect(page.locator(".viewing-note")).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });

  test("approval dialog", async ({ app, page }, testInfo) => {
    await app.ask(Q.python);
    await expect(page.locator(".dialog")).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });

  test("key dialog", async ({ app, page }, testInfo) => {
    await app.dropTool("get_current_temperature");
    await app.ask(Q.weather);
    await expect(page.locator("#dlg-key")).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });

  test("reader dialog", async ({ app, page }, testInfo) => {
    void app;
    await nav(page, "vault");
    await page.locator('[data-tool-btn="caesar_cipher"]').click();
    await page.getByRole("button", { name: "Read full file" }).click();
    await expect(page.locator(".dialog.reader")).toBeVisible();
    await noSerious(page, testInfo.project.name === "live-mobile");
  });
});
