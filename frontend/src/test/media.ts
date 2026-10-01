let reduced = true;
let wide = true;

/** Parity fixtures are generated with reduced motion, so tests default to it. */
export function setReducedMotion(on: boolean): void {
  reduced = on;
}
/** `(min-width: 821px)`; the reference refocuses the composer only on wide screens. */
export function setWideScreen(on: boolean): void {
  wide = on;
}

export function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: query.includes("prefers-reduced-motion") ? reduced : query.includes("min-width: 821px") ? wide : false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as MediaQueryList,
  });
}

export function resetMedia(): void {
  reduced = true;
  wide = true;
}
