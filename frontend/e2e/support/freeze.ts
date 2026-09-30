/** Jump every animation and transition to its end state (spec 04 §9, with prefers-reduced-motion). */
export const FREEZE_CSS = `*,*::before,*::after{animation-delay:-1ms!important;animation-duration:1ms!important;animation-iteration-count:1!important;animation-fill-mode:both!important;transition-duration:0s!important;transition-delay:0s!important}`;
