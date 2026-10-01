import { useLayoutEffect, useRef, type RefObject } from "react";

export function useRestartAnimation(ref: RefObject<HTMLElement | null>, className: string, trigger: unknown, opts: { initial?: boolean } = {}): void {
  const prev = useRef<unknown>(trigger);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    const el = ref.current;
    const first = !mounted.current;
    mounted.current = true;
    if (!el) return;
    if (first ? !opts.initial : Object.is(prev.current, trigger)) return;
    prev.current = trigger;
    el.classList.remove(className);
    void el.offsetWidth;
    el.classList.add(className);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);
}
