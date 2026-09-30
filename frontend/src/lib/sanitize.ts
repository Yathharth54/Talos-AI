import { esc } from "./format";

/* Server HTML may hold only <span class="mono|gold"> and links to #vault / #settings (overview §4.3,
   spec 04 §2.1). The server escapes everything else; this is the browser's own guard. */
const SPAN_CLASSES = new Set(["mono", "gold"]);
const HREFS = new Set(["#vault", "#settings"]);

function walk(node: Node): string {
  let out = "";
  node.childNodes.forEach((c) => {
    if (c.nodeType === Node.TEXT_NODE) {
      out += esc(c.textContent ?? "");
      return;
    }
    if (c.nodeType !== Node.ELEMENT_NODE) return;
    const el = c as Element;
    const tag = el.tagName.toLowerCase();
    if (tag === "script" || tag === "style") {
      out += esc(el.textContent ?? "");
      return;
    }
    const inner = walk(el);
    const cls = el.getAttribute("class") ?? "";
    const href = el.getAttribute("href") ?? "";
    if (tag === "span" && el.attributes.length === 1 && SPAN_CLASSES.has(cls)) out += `<span class="${cls}">${inner}</span>`;
    else if (tag === "a" && el.attributes.length === 1 && HREFS.has(href)) out += `<a href="${href}">${inner}</a>`;
    else out += inner;
  });
  return out;
}

/** Reduces server HTML to the contract's allowlist; everything else becomes escaped text. */
export function sanitize(html: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  return walk(t.content);
}
