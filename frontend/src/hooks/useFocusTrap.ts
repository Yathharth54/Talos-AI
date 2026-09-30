import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = 'button, input, [href], [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(ref: RefObject<HTMLElement | null>, opts: { onEscape: () => void; initialFocus: string }): void {
  const onEscape = useRef(opts.onEscape);
  onEscape.current = opts.onEscape;
  useEffect(() => {
    const prevFocus = document.activeElement as HTMLElement | null;
    const dlg = ref.current;
    dlg?.querySelector<HTMLElement>(opts.initialFocus)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onEscape.current();
      }
      if (e.key === "Tab" && dlg) {
        const f = [...dlg.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => !(x as HTMLButtonElement).disabled);
        if (!f.length) return;
        const first = f[0]!;
        const last = f[f.length - 1]!;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prevFocus?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
