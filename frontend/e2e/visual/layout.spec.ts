import { expect, test } from "@playwright/test";
import { bootFrozen } from "../support/clock";

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
