import { useLayoutEffect, useRef, type RefObject } from "react";

/** placeInd() (line 1142): slide .tab-ind from the previous tab to the selected one. `tabsKey` resets it. */
export function useTabIndicator(tabsRef: RefObject<HTMLElement | null>, selected: string, tabsKey: string): void {
  const last = useRef<{ key: string; pos: { l: number; w: number } | null }>({ key: tabsKey, pos: null });
  useLayoutEffect(() => {
    void selected; // the selection is read back from aria-selected in the DOM; re-run on every render
    const tabs = tabsRef.current;
    if (!tabs) return;
    const ind = tabs.querySelector<HTMLElement>(".tab-ind");
    const sel = tabs.querySelector<HTMLElement>('.tab[aria-selected="true"]');
    if (!ind || !sel) return;
    if (last.current.key !== tabsKey) last.current = { key: tabsKey, pos: null };
    const to = { l: sel.offsetLeft, w: sel.offsetWidth };
    const from = last.current.pos ?? to;
    ind.style.transition = "none";
    ind.style.left = `${from.l}px`;
    ind.style.width = `${from.w}px`;
    void ind.offsetWidth;
    ind.style.transition = "";
    ind.style.left = `${to.l}px`;
    ind.style.width = `${to.w}px`;
    last.current.pos = to;
  });
}
