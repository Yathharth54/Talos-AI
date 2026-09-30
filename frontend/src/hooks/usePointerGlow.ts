import { useEffect } from "react";

export function usePointerGlow(): void {
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const t = (e.target as Element | null)?.closest?.(".try") as HTMLElement | null;
      if (!t) return;
      const b = t.getBoundingClientRect();
      t.style.setProperty("--mx", `${e.clientX - b.left}px`);
      t.style.setProperty("--my", `${e.clientY - b.top}px`);
    };
    document.addEventListener("pointermove", onMove);
    return () => document.removeEventListener("pointermove", onMove);
  }, []);
}
