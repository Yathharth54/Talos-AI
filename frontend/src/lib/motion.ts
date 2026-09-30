export const GLYPHS = "ΛΣΔ01<>/#_+=*";

/** The reference reads this once at load (line 828); a function lets tests switch it. */
export const still = (): boolean =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Decodes `finalText` into `el` from random glyphs (line 864). Returns a cancel function. */
export function scramble(el: HTMLElement | null, finalText: string, duration = 900): () => void {
  if (!el) return () => {};
  if (still()) {
    el.textContent = finalText;
    return () => {};
  }
  let frame = 0;
  const start = performance.now();
  const tick = (now: number) => {
    const p = Math.min((now - start) / duration, 1);
    const settled = Math.floor(p * finalText.length);
    let out = finalText.slice(0, settled);
    for (let i = settled; i < finalText.length; i++) out += finalText[i] === " " ? " " : GLYPHS[(Math.random() * GLYPHS.length) | 0];
    el.textContent = out;
    if (p < 1) frame = requestAnimationFrame(tick);
    else el.textContent = finalText;
  };
  frame = requestAnimationFrame(tick);
  return () => {
    cancelAnimationFrame(frame);
    el.textContent = finalText;
  };
}

/** Counts `el` up to `target` over 1.2 s with an ease-out cubic (line 1079). */
export function countUp(el: HTMLElement | null, target: number): () => void {
  if (!el || still()) return () => {};
  let frame = 0;
  const start = performance.now();
  const tick = (now: number) => {
    const p = Math.min((now - start) / 1200, 1);
    el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
    if (p < 1) frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}

/**
 * The reference's wrapWords (line 972) as a string transform: every word of every text node becomes
 * <span class="wd">, and the first `onCount` get "wd on". Returns the HTML and the number of words.
 */
export function wrapWordsHtml(html: string, onCount: number): { html: string; count: number } {
  const root = document.createElement("p");
  root.innerHTML = html;
  const nodes: Text[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  let count = 0;
  for (const t of nodes) {
    const frag = document.createDocumentFragment();
    for (const part of (t.textContent ?? "").split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s+$/.test(part)) {
        frag.append(part);
        continue;
      }
      const w = document.createElement("span");
      w.className = count < onCount ? "wd on" : "wd";
      w.textContent = part;
      frag.append(w);
      count++;
    }
    t.replaceWith(frag);
  }
  return { html: root.innerHTML, count };
}
