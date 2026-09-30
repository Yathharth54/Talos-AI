import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { installMatchMedia, resetMedia } from "./media";

installMatchMedia();

// jsdom has no PointerEvent, so fireEvent.pointerMove would drop clientX/clientY.
if (typeof window.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {}
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent;
}
afterEach(() => {
  resetMedia();
  document.body.className = "";
  window.location.hash = "";
});
