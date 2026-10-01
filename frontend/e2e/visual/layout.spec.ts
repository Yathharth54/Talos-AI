import { expect, test, type Page } from "@playwright/test";
import { advanceUntil, bootFrozen, finishRun } from "../support/clock";
import { nav, tap } from "../support/shots";

// Geometry checks, not screenshots: they hold on the reference and on the app alike.
const LAPTOPS = [
  { width: 1512, height: 780 },
  { width: 1440, height: 900 },
] as const;

test.beforeEach(() => {
  test.skip(test.info().project.name.endsWith("mobile"), "the sizes are set per test");
});

test("idle hero: the orbits sit whole inside the bench and every suggestion card shows", async ({ page }) => {
  for (const size of LAPTOPS) {
    await page.setViewportSize(size);
    await bootFrozen(page);
    const m = await page.evaluate(() => {
      const top = (s: string) => document.querySelector(s)!.getBoundingClientRect().top;
      const bench = document.querySelector(".bench")!.getBoundingClientRect();
      const cards = [...document.querySelectorAll(".try")].map((c) => c.getBoundingClientRect().bottom);
      return { bench: bench.top, idle: top(".idle"), o1: top(".orbit.o1"), o2: top(".orbit.o2"), cards, view: innerHeight };
    });
    expect(m.o1, `outer orbit clipped at ${size.width}x${size.height}`).toBeGreaterThanOrEqual(m.idle);
    expect(m.o2).toBeGreaterThanOrEqual(m.idle);
    expect(m.o1 - m.bench, "room above the hero").toBeGreaterThanOrEqual(24);
    expect(m.cards).toHaveLength(4);
    for (const b of m.cards) expect(b, `card cut at ${size.width}x${size.height}`).toBeLessThanOrEqual(m.view);
  }
});

/** Make the selected tool long: many keywords and a long description, so the detail panel must scroll. */
async function lengthen(page: Page): Promise<void> {
  await page.evaluate(() => {
    const kws = document.querySelector(".v-detail .kws")!;
    for (let i = 0; i < 24; i++) kws.insertAdjacentHTML("beforeend", `<li>keyword-${i}</li>`);
    const desc = document.querySelector(".v-detail .desc")!;
    desc.textContent = `${desc.textContent} `.repeat(4);
  });
}

async function expectReadable(page: Page, label: string): Promise<void> {
  const btn = page.locator("[data-read-src]");
  await btn.scrollIntoViewIfNeeded();
  const m = await page.evaluate(() => {
    const b = document.querySelector("[data-read-src]")!;
    const r = b.getBoundingClientRect();
    const fig = b.closest("figure")!;
    const f = fig.getBoundingClientRect();
    const acts = document.querySelector(".v-detail .actions")!.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { figH: f.height, figFull: fig.scrollHeight, figBottom: f.bottom, actsTop: acts.top, hit: !!hit && b.contains(hit), top: r.top, bottom: r.bottom, view: innerHeight };
  });
  expect(m.figH, `source preview squashed (${label})`).toBeGreaterThanOrEqual(m.figFull - 1);
  expect(m.figBottom, `preview runs under the actions (${label})`).toBeLessThanOrEqual(m.actsTop);
  expect(m.top).toBeGreaterThanOrEqual(0);
  expect(m.bottom).toBeLessThanOrEqual(m.view);
  expect(m.hit, `"Read full file" covered (${label})`).toBe(true);
}

test("vault detail: a long tool scrolls whole, and Read full file is visible and clickable", async ({ page }) => {
  await page.setViewportSize(LAPTOPS[0]);
  await bootFrozen(page);
  await tap(page, '.try[data-suggest="0"]');
  await finishRun(page, 0);
  await nav(page, "vault");
  await page.clock.runFor(1000);

  for (const size of [...LAPTOPS, { width: 390, height: 844 }]) {
    await page.setViewportSize(size);
    await tap(page, '[data-tool-btn="caesar_cipher"]');
    const label = `${size.width}x${size.height}`;
    await expectReadable(page, label);
    await lengthen(page);
    await expectReadable(page, `${label}, long`);
  }

  await tap(page, "[data-read-src]");
  await advanceUntil(page, ".dialog.reader");
});
