/**
 * Jump every animation and transition to its end state (spec 04 §9, with prefers-reduced-motion).
 *
 * `scroll-behavior` too: `.msgs { scroll-behavior: smooth }` animates on the compositor's real clock,
 * which Playwright's paused clock doesn't drive, so a shot could catch it mid-scroll.
 *
 * And `overflow-anchor`: once a click has scrolled a box (on mobile, Playwright scrolls `.views` to reach
 * a suggestion), Chrome's scroll anchoring shifts that box's offset at each layout by how far its anchor
 * node moved, snapped to a whole pixel. Layouts follow rendering frames, which run on the real clock, so
 * which in-between states get laid out, and how the fractional moves round, depends on frame timing. On
 * Linux the reference ends the forge's 30th code line at `.views` 574 and the app at 575, so every row of
 * that shot below the header moved by one pixel. With anchoring off, a box keeps the offset the click gave
 * it, on both pages.
 */
export const FREEZE_CSS = `*,*::before,*::after{animation-delay:-1ms!important;animation-duration:1ms!important;animation-iteration-count:1!important;animation-fill-mode:both!important;transition-duration:0s!important;transition-delay:0s!important;scroll-behavior:auto!important;overflow-anchor:none!important}`;
