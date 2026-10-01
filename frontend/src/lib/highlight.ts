import { esc } from "./format";

const KW = /\b(def|return|if|elif|else|for|in|not|or|and|is|raise|import|from|continue|None|True|False)\b/g;

/** Python-ish highlighter for code panels. Returns the reference's exact HTML strings (line 892). */
export function highlight(lines: string[]): string[] {
  let inDoc = false;
  return lines.map((raw) => {
    const e = esc(raw);
    const triple = (raw.match(/"""/g) || []).length;
    if (inDoc || raw.trim().startsWith('"""')) {
      const html = `<span class="str">${e}</span>`;
      if (inDoc && triple) inDoc = false;
      else if (!inDoc && triple === 1) inDoc = true;
      return html;
    }
    let h = e.replace(/(f?&quot;.*?&quot;|&#39;.*?&#39;)/g, "\u0000$1\u0001");
    h = h
      // eslint-disable-next-line no-control-regex -- the reference marks strings with \u0000…\u0001
      .split(/(\u0000[^\u0001]*\u0001)/)
      .map((part) =>
        part.startsWith("\u0000") ? `<span class="str">${part.slice(1, -1)}</span>` : part.replace(KW, '<span class="kw">$1</span>'),
      )
      .join("");
    return h;
  });
}
