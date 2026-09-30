import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

/** Server-renders a component; effects don't run, which is what the reference's pure renderers match. */
export const ssr = (el: ReactElement): string => renderToStaticMarkup(el);

export function innerOf(html: string, sel?: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  const el = sel ? t.content.querySelector(sel) : t.content.firstElementChild;
  if (!el) throw new Error(`innerOf: nothing matches ${sel ?? "the first element"}`);
  return el.innerHTML;
}
