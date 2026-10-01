import { useLayoutEffect, useRef, type RefObject } from "react";

/**
 * showView() (line 2078) hides the old view and forces a reflow (`void cur.offsetWidth`) before
 * renderVault/renderSessions/renderSettings fill the new one. At that reflow the new view still holds
 * its previous render (nothing, on a first visit), so the scrolling `.views` (below 820 px) clamps its
 * scrollTop to that height, and the fresh render keeps the clamped position. React renders the new
 * content before any reflow, so this replays the clamp against the height of the view's last render.
 *
 * `trigger` changes on every view change (`viewEnter`). The workbench is live in the reference while
 * hidden, so it passes `enabled: false` and gets the browser's own clamp.
 */
export function useStaleViewScroll(ref: RefObject<HTMLElement | null>, shown: boolean, trigger: unknown, enabled: boolean): void {
  // The height of the view's last render while shown; 0 until the first visit (the empty markup).
  const lastHeight = useRef(0);

  useLayoutEffect(() => {
    const el = ref.current;
    const views = el?.parentElement;
    if (!enabled || !el || !views || !shown || trigger === 0) return;
    const max = Math.max(0, lastHeight.current - views.clientHeight);
    if (views.scrollTop > max) views.scrollTop = max;
    lastHeight.current = el.offsetHeight;
    // Only a view change replays the reflow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);

  // Later renders while shown (a filter, a search, a toggle) become the next visit's stale height.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!enabled || !el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (!el.hidden && el.offsetHeight > 0) lastHeight.current = el.offsetHeight;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, enabled]);
}
