export type Mode = "demo" | "live";

/** `/?demo` or a build with VITE_DEMO=1 runs the scripted demo (spec 04 §8.3). */
export function resolveMode(search: string = window.location.search, flag: string | undefined = import.meta.env.VITE_DEMO): Mode {
  return flag === "1" || new URLSearchParams(search).has("demo") ? "demo" : "live";
}
