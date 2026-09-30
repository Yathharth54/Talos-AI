import { readRef } from "../../scripts/reference.mjs";
import { esc } from "./format";
import { COPY, fill, healthText, removedSub, retryLabel } from "./copy";

function leaves(o: unknown, path = "COPY"): [string, string][] {
  if (typeof o === "string") return [[path, o]];
  if (o && typeof o === "object") return Object.entries(o).flatMap(([k, v]) => leaves(v, `${path}.${k}`));
  return [];
}

const SHORT = 40;
const reEsc = (t: string): string => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Strings the reference renders as one text node but the table splits in two; checked joined. */
const JOINED: Record<string, [string, string]> = { "COPY.key.footDemo": ["COPY.key.foot", "COPY.key.footDemo"] };

/** A short fragment must be a whole quoted literal or a whole text node in the reference, not a loose substring. */
function exactIn(ref: string, frag: string): boolean {
  for (const f of new Set([frag, esc(frag)])) {
    const t = reEsc(f.trim());
    const re = new RegExp(`(?:>|^|["'\`])\\s*${t}\\s*(?:<|\\$\\{|$|["'\`])`, "m");
    if (re.test(ref)) return true;
  }
  return false;
}

test("every copy.ts string appears in the reference, fragment by fragment", () => {
  const ref = readRef();
  const all = Object.fromEntries(leaves(COPY));
  const missing: string[] = [];
  for (const [path, s] of Object.entries(all)) {
    const hasField = /\{\w+\}/.test(s);
    const joined = JOINED[path];
    if (joined) {
      const j = (all[joined[0]] ?? "") + s;
      if (!exactIn(ref, j) && !ref.includes(j)) missing.push(`${path}: ${JSON.stringify(j)}`);
      continue;
    }
    for (const frag of s.split(/\{\w+\}/)) {
      if (!frag.trim()) continue;
      const strict = !hasField && frag.length <= SHORT;
      const ok = strict ? exactIn(ref, frag) : ref.includes(frag) || ref.includes(esc(frag));
      if (!ok) missing.push(`${path}: ${JSON.stringify(frag)}`);
    }
  }
  expect(missing).toEqual([]);
});

test("the strict matcher rejects loose substrings", () => {
  const ref = readRef();
  expect(exactIn(ref, "Work")).toBe(false);
  expect(exactIn(ref, "Uses the web")).toBe(true);
});

test("fill and the failure copy", () => {
  expect(fill(COPY.convo.hintPast, { name: "Caesar cipher" })).toBe("Viewing an old session. Go back to Caesar cipher to ask something.");
  expect(healthText("caesar_cipher", false)).toContain('If <span class="mono">caesar_cipher</span> fails again');
  expect(healthText("caesar_cipher", true)).toBe('That was 2 failures with no success in between, so Talos took <span class="mono">caesar_cipher</span> out of the vault.');
  expect(healthText("get_current_temperature", true)).toBe("Removed after two failures in a row.");
  expect(healthText("slugify", false)).toContain('<span class="mono">slugify</span>');
  expect(removedSub("caesar_cipher")).toBe("It failed 2 times in a row, so the next Caesar request will forge a fresh one. The .py file stays on disk.");
  expect(removedSub("get_current_temperature")).toBe("It failed 2 times in a row. The next weather request forges a fresh one.");
  expect(retryLabel("shift", 7)).toBe("Ask again with shift 7");
});
