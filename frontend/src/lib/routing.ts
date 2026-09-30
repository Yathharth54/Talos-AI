import type { Variant } from "../transport/types";

export const PRUNE_AT = 2;
export const NUM_WORDS: Record<string, number> = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13,
};

export type QueryKind = "chat" | "caesar" | "python" | "weather" | "vaultlist" | "unknown";
export interface CaesarParams {
  text: string;
  shift: number;
  shiftWord: string | null;
  mode: "encrypt" | "decrypt";
}

export function caesar(text: string, shift: number, mode: string): string {
  let k = mode === "decrypt" ? -shift : shift;
  k = ((k % 26) + 26) % 26;
  return [...text]
    .map((c) => {
      const code = c.charCodeAt(0);
      if (code >= 65 && code <= 90) return String.fromCharCode(((code - 65 + k) % 26) + 65);
      if (code >= 97 && code <= 122) return String.fromCharCode(((code - 97 + k) % 26) + 97);
      return c;
    })
    .join("");
}

export function parseCaesar(text: string): CaesarParams {
  const quoted = text.match(/["“]([^"”]+)["”]/);
  const before = quoted ? text.slice(0, quoted.index) : text;
  const verbs = [...before.matchAll(/\b(en|de)(?:crypt|code)/gi)];
  const last = verbs[verbs.length - 1];
  const mode = last ? ((last[1] ?? "").toLowerCase() === "de" ? "decrypt" : "encrypt") : "encrypt";
  let shift = 7;
  let shiftWord: string | null = null;
  const num = text.match(/shift(?:\s+of)?\s*(?:=|:)?\s*(-?\d+)/i);
  const word = text.match(/shift(?:\s+of)?\s+([a-z]+)/i);
  if (num) shift = parseInt(num[1] ?? "7", 10);
  else if (word && !/^(of|to|by)$/i.test(word[1] ?? "")) shiftWord = (word[1] ?? "").toLowerCase();
  const input = quoted ? (quoted[1] ?? "") : mode === "decrypt" ? "AHSVZ HNLUA" : "TALOS AGENT";
  return { text: input, shift, shiftWord, mode };
}

export function classify(q: string): QueryKind {
  if (/\b(what can you do|who are you|help me understand|how do you work)\b/i.test(q)) return "chat";
  if (/(caesar|cipher|\bencrypt|\bdecrypt)/i.test(q)) return "caesar";
  if (/(python|print\s*\(|run this code|run the code)/i.test(q)) return "python";
  if (/(openweather|weather|temperature)/i.test(q)) return "weather";
  if (/(how many tools|list (all )?(your|the) tools|in (your|the) (skill )?vault)/i.test(q)) return "vaultlist";
  return "unknown";
}

export function runPython(code: string): string | null {
  const m = code.trim().match(/^print\((.*)\)$/s);
  if (!m) return null;
  const inner = (m[1] ?? "").trim();
  const sr = inner.match(/^sum\(range\((-?\d+)\s*,\s*(-?\d+)\)\)$/);
  if (sr) {
    let s = 0;
    for (let i = Number(sr[1]); i < Number(sr[2]); i++) s += i;
    return String(s);
  }
  const lit = inner.match(/^(["'])(.*)\1$/);
  if (lit) return lit[2] ?? "";
  if (/^[\d\s+\-*/().%]+$/.test(inner)) {
    try {
      const v: unknown = Function(`"use strict"; return (${inner});`)();
      if (typeof v === "number" && Number.isFinite(v)) return String(v);
    } catch {
      return null;
    }
  }
  return null;
}

export function sessionName(kind: QueryKind, q: string): string {
  if (kind === "caesar") return "Caesar cipher";
  if (kind === "python") return "Running Python";
  if (kind === "weather") {
    const m = q.match(/\bin ([A-Z][A-Za-z .'-]+?)(?:[.?!]|$)/);
    return `Weather in ${m ? (m[1] ?? "").trim() : "Mumbai"}`;
  }
  if (kind === "chat") return "Getting to know Talos";
  if (kind === "vaultlist") return "What's in the vault";
  const w = q.split(/\s+/).slice(0, 4).join(" ");
  return w.charAt(0).toUpperCase() + w.slice(1);
}

/** The strip the reference shows before planning finishes (lines 1464, 1655–1677, 1843–1860). Ruling 3. */
export function provisionalVariant(query: string, vaultNames: string[]): Variant {
  const kind = classify(query);
  if (kind === "caesar") return vaultNames.includes("caesar_cipher") ? "vault" : "forge";
  if (kind === "weather") return vaultNames.includes("get_current_temperature") ? "vault" : "forge";
  if (kind === "python" || kind === "vaultlist") return "primitive";
  return "chat";
}
