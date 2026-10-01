import { useLayoutEffect, type RefObject } from "react";
import { countUp } from "../lib/motion";

export function useCountUp(ref: RefObject<HTMLElement | null>, target: number): void {
  // renderIdle() counts up once per render of the idle bench (line 1077).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => countUp(ref.current, target), []);
}
