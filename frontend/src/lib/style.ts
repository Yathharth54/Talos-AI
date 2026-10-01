/**
 * Ref callback for the few inline styles where the reference writes a zero length bare (`margin:0`,
 * `padding:0 4px`, `min-width:0`). React sets styles through the CSSOM, which serialises those as
 * `0px`; this rewrites the element's style attribute so the DOM text is the reference's. The computed
 * style is unchanged. Only for static styles: React would write `0px` again if the style prop changed.
 */
export function bareZeros(el: HTMLElement | null): void {
  const css = el?.getAttribute("style");
  if (!el || !css) return;
  const bare = css.replace(/(^|[\s:])0px\b/g, "$10");
  if (bare !== css) el.setAttribute("style", bare);
}
