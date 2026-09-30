import { countUp, GLYPHS, scramble, still, wrapWordsHtml } from "./motion";
import { setReducedMotion } from "../test/media";
import { expectParity, fixtureCase } from "../test/parity";

afterEach(() => vi.useRealTimers());

test("still() follows prefers-reduced-motion", () => {
  expect(still()).toBe(true);
  setReducedMotion(false);
  expect(still()).toBe(false);
});

test("wrapWordsHtml matches the reference wrapWords with the first words on", () => {
  const c = fixtureCase("lib/wrap-words");
  const { html, on } = c.state as { html: string; on: number };
  const out = wrapWordsHtml(html, on);
  expectParity(out.html, c.value as string);
  expect(out.count).toBe(12); // the "." after the mono span is its own text node, so its own word
});

test("scramble settles on the final text, instantly under reduced motion", () => {
  const el = document.createElement("span");
  scramble(el, "caesar_cipher");
  expect(el.textContent).toBe("caesar_cipher");

  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
  const el2 = document.createElement("span");
  scramble(el2, "Session 2", 600);
  vi.advanceTimersByTime(100);
  expect(el2.textContent).toHaveLength("Session 2".length);
  expect([...el2.textContent!].some((ch, i) => ch !== "Session 2"[i] && GLYPHS.includes(ch))).toBe(true);
  vi.advanceTimersByTime(700);
  expect(el2.textContent).toBe("Session 2");
});

test("countUp does nothing under reduced motion and eases to the target otherwise", () => {
  const el = document.createElement("span");
  el.textContent = "40";
  countUp(el, 40);
  expect(el.textContent).toBe("40");

  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
  countUp(el, 40);
  vi.advanceTimersByTime(300);
  expect(Number(el.textContent)).toBeGreaterThan(0);
  expect(Number(el.textContent)).toBeLessThan(40);
  vi.advanceTimersByTime(1000);
  expect(el.textContent).toBe("40");
});
