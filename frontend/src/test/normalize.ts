const VOID = new Set(["area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);

const escText = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escAttr = (s: string) => escText(s).replace(/"/g, "&quot;");

function normStyle(value: string): string {
  return value
    .split(";")
    .map((d) => d.trim())
    .filter(Boolean)
    .map((d) => {
      const i = d.indexOf(":");
      return `${d.slice(0, i).trim().toLowerCase()}:${d.slice(i + 1).trim().replace(/\s+/g, " ")}`;
    })
    .join(";");
}

function attrs(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const out: [string, string][] = [];
  for (const a of Array.from(el.attributes)) {
    let v = a.value;
    if (a.name === "value" && (tag === "input" || tag === "textarea")) continue;
    if (a.name === "style") {
      if (el.classList.contains("tab-ind")) continue;
      v = normStyle(v);
      if (!v) continue;
    }
    if (a.name === "class") {
      v = v.split(/\s+/).filter(Boolean).sort().join(" ");
      if (!v) continue;
    }
    out.push([a.name, v]);
  }
  out.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return out.map(([name, v]) => ` ${name}="${escAttr(v)}"`).join("");
}

function walk(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    let t = node.textContent ?? "";
    if (/^\s*$/.test(t) && t.includes("\n")) return "";
    t = t.replace(/^\s*\n\s*/, "").replace(/\s*\n\s*$/, "");
    return escText(t);
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node as Element;
  const tag = el.tagName.toLowerCase();
  const open = `<${tag}${attrs(el)}>`;
  if (VOID.has(tag)) return open;
  if (tag === "textarea") return `${open}</textarea>`;
  return open + Array.from(el.childNodes).map(walk).join("") + `</${tag}>`;
}

/** Canonical form of an HTML fragment for DOM-parity comparisons (plan ruling 15). */
export function normalizeHtml(html: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  return Array.from(t.content.childNodes).map(walk).join("");
}
