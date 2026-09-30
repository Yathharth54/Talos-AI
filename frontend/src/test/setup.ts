import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { installMatchMedia, resetMedia } from "./media";

installMatchMedia();
afterEach(() => {
  resetMedia();
  document.body.className = "";
  window.location.hash = "";
});
