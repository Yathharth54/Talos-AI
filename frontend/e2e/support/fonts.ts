import { readFileSync } from "node:fs";
import { basename } from "node:path";
import type { Page } from "@playwright/test";

/**
 * Serve the Google Fonts both pages link to from a pinned local copy.
 *
 * The Google Fonts CSS API doesn't always answer the same request with the same fonts. About one
 * request in twenty, the CSS points Instrument Sans and JetBrains Mono at a different build
 * (`/l/font?kit=…`, 32240 and 30376 bytes, instead of `/s/…`, 30092 and 31432 bytes). That build
 * rasterises every glyph a little differently, so a shot of a page that got it differs from a shot
 * of one that didn't by about a thousand pixels of text anti-aliasing. Each test loads its own copy,
 * so whichever ref or demo page drew the odd build failed a random shot.
 *
 * `fonts/google-fonts.css` is the usual response to the `css2` URL in both pages' `<head>`, and
 * `fonts/*.woff2` are the files it names (SIL Open Font License). Any other font request fails,
 * so a changed `<link>` shows up as a font difference instead of reaching the network.
 */
const dir = new URL("./fonts/", import.meta.url);
const css = readFileSync(new URL("google-fonts.css", dir), "utf8");
const cors = { "access-control-allow-origin": "*" };

export async function pinFonts(page: Page): Promise<void> {
  await page.route("https://fonts.googleapis.com/**", (route) =>
    route.fulfill({ contentType: "text/css; charset=utf-8", headers: cors, body: css }),
  );
  await page.route("https://fonts.gstatic.com/**", (route) => {
    const file = basename(new URL(route.request().url()).pathname);
    if (!css.includes(`/${file})`)) return route.fulfill({ status: 404, headers: cors });
    return route.fulfill({ contentType: "font/woff2", headers: cors, body: readFileSync(new URL(file, dir)) });
  });
}
