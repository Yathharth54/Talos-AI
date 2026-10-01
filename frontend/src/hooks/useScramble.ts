import { useLayoutEffect, useRef, type RefObject } from "react";
import { scramble } from "../lib/motion";

export function useScramble(ref: RefObject<HTMLElement | null>, text: string, duration: number, opts: { onMount?: boolean } = {}): void {
  const mounted = useRef(false);
  useLayoutEffect(() => {
    const first = !mounted.current;
    mounted.current = true;
    if (first && !opts.onMount) return;
    return scramble(ref.current, text, duration);
    // Only a text change (or the mount, when asked) replays the decode, as in the reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
}
