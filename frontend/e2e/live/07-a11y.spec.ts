import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

/**
 * Findings the reference itself has, measured on 1 Oct 2026 by running axe on
 * docs/superpowers/specs/reference/workbench-demo/index.html (desktop 1440 and mobile 390, same steps: a forge run with
 * the Code tab, a second run, the approval and key dialogs). The UI must match the reference exactly, so they are kept
 * for parity and listed for the owner (Task 12). Every allowance is an exact element kind plus the exact text colour
 * and contrast ratio the reference measures, so any other contrast failure, in the same panel or not, still fails.
 *  - .ln: the code panel's line numbers.
 *  - Inside a dimmed earlier message (.past): .who, .note, .chip.forged and .run-link (grey, or amber when it is the run on the bench).
 *  - scrollable-region-focusable on #b-strip: at 390 px the step strip scrolls sideways and isn't focusable.
 */
const CONTRAST: Record<string, { fg: string; ratio: number }> = {
  ln: { fg: "#5e5953", ratio: 2.94 },
  "past who": { fg: "#5c5853", ratio: 2.97 },
  "past note": { fg: "#5c5853", ratio: 2.97 },
  "past chip forged": { fg: "#806b49", ratio: 4.11 },
  "past run-link": { fg: "#5c5853", ratio: 2.97 },
  "past run-link current": { fg: "#806b49", ratio: 4.11 }, // the amber of the run link that is on the bench
};

/**
 * What kind of element an axe node is, or null. A selector like ".run-link" can match several elements, so the node is
 * picked out of the matches by its own outerHTML (axe may cut a long one in the middle with " ... ").
 */
function elementKind(target: string, html: string): string | null {
  const kindOf = (el: Element): string | null => {
    if (el.matches(".code-body .ln")) return "ln";
    if (!el.closest(".past")) return null;
    if (el.matches(".who")) return "past who";
    if (el.matches(".note")) return "past note";
    if (el.matches(".chip.forged")) return "past chip forged";
    if (el.matches('.run-link[aria-current="true"]')) return "past run-link current";
    if (el.matches(".run-link")) return "past run-link";
    return null;
  };
  const [head = "", tail] = html.split(" ... ");
  const same = (el: Element): boolean => (tail === undefined ? el.outerHTML === html : el.outerHTML.startsWith(head) && el.outerHTML.endsWith(tail));
  const hits = [...document.querySelectorAll(target)].filter(same);
  return hits.length === 1 ? (kindOf(hits[0] as Element) ?? null) : null;
}

type AxeNode = { target: (string | string[])[]; html: string; any: { data?: { fgColor?: string; contrastRatio?: number } }[] };

async function inherited(page: Page, rule: string, n: AxeNode): Promise<boolean> {
  const target = n.target.join(" ");
  if (rule === "scrollable-region-focusable") return target === "#b-strip";
  if (rule !== "color-contrast") return false;
  const kind = await page.evaluate(`(${elementKind.toString()})(${JSON.stringify(target)}, ${JSON.stringify(n.html)})`).catch(() => null);
  const want = typeof kind === "string" ? CONTRAST[kind] : undefined;
  const data = n.any[0]?.data;
  return !!want && data?.fgColor === want.fg && data.contrastRatio === want.ratio;
}

/** Serious and critical violations that aren't in the inherited list, one line per node. */
async function seriousNodes(page: Page, isMobile: boolean): Promise<string[]> {
  let axe = new AxeBuilder({ page });
  // Reference defect, kept for parity: at 390 px the GitHub pill hides its label, so the link has no name
  // (axe link-name, serious, present in the reference itself). See plan 04b Task 10.
  if (isMobile) axe = axe.exclude('.top-right a.pill[target="_blank"]');
  const { violations } = await axe.analyze();
  const bad: string[] = [];
  for (const v of violations) {
    if (v.impact !== "serious" && v.impact !== "critical") continue;
    for (const n of v.nodes) {
      if (!(await inherited(page, v.id, n as unknown as AxeNode))) bad.push(`${v.id}: ${n.target.join(" ")}`);
    }
  }
  return bad;
}

async function noSerious(page: Page, isMobile: boolean): Promise<void> {
  expect(await seriousNodes(page, isMobile)).toEqual([]);
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

  test("the inherited-findings list is narrow", async ({ app, page }, testInfo) => {
    // Set-up: the reference's own elements stay allowed, but a different low-contrast element in the same panels fails.
    void app;
    await page.locator(".run-link").last().click();
    await page.locator('[data-tab="code"]').click();
    await page.evaluate(() => {
      const body = document.querySelector('.code-body[aria-label="Source code"]');
      body?.insertAdjacentHTML("afterbegin", '<span id="neg-code" style="color:#3a3a3a">low contrast code</span>');
      document.querySelector(".msgs")?.insertAdjacentHTML("beforeend", '<div class="msg talos past"><p class="note" id="neg-past" style="color:#3a3a3a">low contrast note</p></div>');
      document.getElementById("neg-past")?.scrollIntoView(); // axe skips elements clipped by a scroll container
    });
    const bad = await seriousNodes(page, testInfo.project.name === "live-mobile");
    expect(bad.some((b) => b.includes("neg-code"))).toBe(true);
    expect(bad.some((b) => b.includes("neg-past"))).toBe(true);
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
    for (let i = 0; i < 2 && (await sessions()).length < 2; i++) {
      await page.locator("#new-session").click();
      await expect(page.locator(".empty-convo")).toBeVisible();
      await app.finished(await app.ask(Q.reuse));
    }
    const list = await sessions();
    expect(list.length).toBeGreaterThanOrEqual(2);
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
