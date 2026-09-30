import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const LAYOUT_EFFECT_WARNING = "useLayoutEffect does nothing on the server";

/**
 * Server-renders a component; effects don't run, which is what the reference's pure renderers match.
 * React warns once per render about layout effects on the server; that is expected here, so exactly
 * that warning is filtered out while rendering. Production code is unchanged.
 */
export function ssr(el: ReactElement): string {
  const orig = console.error;
  console.error = (...args: unknown[]) => {
    if (typeof args[0] === "string" && args[0].includes(LAYOUT_EFFECT_WARNING)) return;
    orig(...args);
  };
  try {
    return renderToStaticMarkup(el);
  } finally {
    console.error = orig;
  }
}

export function innerOf(html: string, sel?: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  const el = sel ? t.content.querySelector(sel) : t.content.firstElementChild;
  if (!el) throw new Error(`innerOf: nothing matches ${sel ?? "the first element"}`);
  return el.innerHTML;
}
