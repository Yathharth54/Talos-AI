# Talos Web App Stage 04 Part A (Frontend, demo mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `frontend/`, the React 18 + TypeScript port of the approved Workbench demo, fully working in demo mode (`/?demo` or `VITE_DEMO=1`) with DOM, style and copy parity against the reference file, and with clean seams (transport interface, event player, data-source interface) for part B's live mode.

**Architecture:** The reference file is mined, never re-typed. A Node script copies its `<style>` block, the two bundled tool sources and the vault data into the app verbatim. A Playwright script runs the reference itself in headless Chromium and writes DOM fixtures: pure renderer outputs for hand-built states, and live DOM snapshots at checkpoints of scripted flows. Components are transcribed from the named demo functions and compared with those fixtures after normalisation. Every run goes through one path: a `Transport` emits contract events (overview §4), `transport/player.ts` animates and applies them to five small reducer stores, and components render the stores. In part A the only transport is `DemoTransport`: the demo's scripted flows, rewritten to emit events.

**Tech Stack:** React 18.3.1, TypeScript 5.9.3 (strict), Vite 5.4.21 with `@vitejs/plugin-react` 4.7.0, Vitest 3.2.7 + jsdom 26.1.0 + Testing Library (React 16.3.3, DOM 10.4.1, jest-dom 6.10.0, user-event 14.6.7), ESLint 9.39.5 + typescript-eslint 8.71.0, `@playwright/test` 1.63.0 (fixture generator only in part A). Node 22 or newer. All versions were installed together and exercised (lint, typecheck, test, build, a Playwright run against the reference) in a scratch project on 30 Sep 2026.

**Specs, in order of authority:**

1. `docs/superpowers/specs/reference/workbench-demo/artifact-body.html` (below: "the reference"; line numbers in this plan refer to it). **It wins over everything else.**
2. `docs/superpowers/specs/2026-09-30-talos-web-04-frontend-design.md` (below: "spec 04").
3. `docs/superpowers/specs/2026-09-30-talos-web-app-overview-design.md` §4, the event contract (below: "the contract").
4. `docs/superpowers/specs/2026-09-30-talos-web-02-api-design.md` §4 (API shapes, typed in `transport/types.ts` for part B).

Sibling plan: part B, `docs/superpowers/plans/2026-09-30-talos-web-04b-frontend-live.md`, builds live mode on the seams named in this plan's Interfaces blocks.

## Global Constraints

- **The reference file wins.** `frontend/src/styles.css` equals the reference's `<style>` block byte for byte (generated, never hand-edited). Every UI string is word for word from the reference. The DOM is the reference's DOM: same elements, nesting, class names, attributes (including `aria-*`, `data-*`, `role`, `hidden`) and text. In JSX, `class` becomes `className`, `for` becomes `htmlFor`, `tabindex` becomes `tabIndex`, SVG `stroke-width` becomes `strokeWidth`, and nothing else changes. The only allowed differences are spec 04 §8 (Demo controls only in demo mode; live copy is part B).
- Never edit anything under `docs/superpowers/specs/reference/`.
- Frontend-owned strings live in `src/lib/copy.ts`. Strings that the server owns in live mode (captions, log lines, answers, chips, summaries, banner subs) live in `src/transport/demo.ts`, because in demo mode `DemoTransport` is the server.
- No component library, CSS framework or CSS-in-JS. No Redux or Zustand. Runtime dependencies are exactly `react` and `react-dom`.
- TypeScript `strict` plus `noUncheckedIndexedAccess`. No `any` (use `unknown` and narrow). `npm run lint` reports zero errors.
- Pinned versions, exactly (no `^`): see Task 1's `package.json`. Use `npm install` once to create `package-lock.json`, then commit it.
- Tests run with `TZ=UTC`. Parity fixtures are generated at the fixed time `2026-09-30T12:00:00Z` with `prefers-reduced-motion: reduce`, at 1440×900. Tests that compare with fixtures use the same clock and reduced motion.
- All frontend commands run in `frontend/`. Scripts and tests find files relative to `process.cwd()` (which is `frontend/` for npm scripts and Vitest). Don't use `import.meta.url` for file paths in code that Vitest loads: under jsdom it isn't a `file:` URL.
- Python stays green: at the end `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass unchanged.
- Commit messages: prefix `[Feat]:`, `[Fix]:`, `[Docs]:` or `[Chore]:`, then a short sentence. **No `Co-Authored-By` trailer and no Claude attribution line.**
- Branch `feat/web-04-frontend`, created from the tip of stage 03's branch (`git switch -c feat/web-04-frontend <stage-03-branch>`). Part B continues on the same branch.
- Seams for part B, and nothing else touches them: `Transport` and the contract types in `src/transport/types.ts`, `Player` in `src/transport/player.ts`, `DataSource` in `src/data/source.ts`, `createServices(mode)` in `src/services.ts`. Components never import a transport or a data source; they read stores and call the `Workbench` controller.

## Rulings on ambiguities (read before starting)

1. **Tests count while forging.** The reference shows `Tests 5` in the tab bar as soon as the code starts revealing, but the contract's `forge.code` has no test count. `ForgeCodeData` gets an optional `tests?: number` (the number of tests the Forger wrote). `DemoTransport` always sends it. The player falls back to the previous attempt's count. Stage 2 should send it too; this is reported to the controller.
2. **Two demo-only optional fields**, typed and commented as such: `StripSetData.title` (the unknown-query flow's "Not in this demo") and `AnswerDoneData.suggest` (the inline suggestion buttons after that answer). The live server never sends them.
3. **Provisional strip.** `run.started` has no variant, so the player picks one with `provisionalVariant(query, vaultNames)` (the reference's `classify` plus its "is the tool already in the vault" check, lines 1464, 1655 and 1843). A later `strip.set` with the same variant only sets label, signature and title; a different variant re-initialises the strip but keeps the states of steps present in both.
4. **Pacing split.** The player always animates facts that arrive whole: command typing, code reveal, test ticking, the smoke test's running state, argument reveal and answer words, with the reference's timings. The reference's other `wait()` calls are "moment dwells". `DemoTransport` performs those itself, with the reference's exact values, between emissions, and its players run with `momentDwell: false`. The spec 04 §6 minimum-dwell table is implemented in `player.ts` behind `momentDwell: true` and unit-tested; part B turns it on for live runs.
5. **Argument reveal** is 260 ms per argument, or 350 ms when there is exactly one, and nothing when `call.args` has a caption (the reference's python and `vault_list` calls show their arguments at once). This reproduces lines 1706 and 1876 exactly.
6. **Stores** are pure reducers behind a tiny external store (`useSyncExternalStore`), exposed through one context. The player and `DemoTransport` need synchronous `getState()`, which `useReducer` can't give them. It is still one reducer per concern (`runs`, `session`, `vault`, `settings`, `ui`).
7. **Run numbers** in demo mode are the reference's global counter (the seeded runs are 1 to 5, so the first new run is 6), because `data-run` and "Run n" show it.
8. **Record row** (the reuse run's Forged / Uses / Failures) is derived by the player when a vault-variant run gets a result that isn't `small`. This reproduces the reference, where the Caesar reuse shows it and the weather placeholder result doesn't.
9. **Failure copy** (the health text, the retry button and the removed banner's second line) is frontend copy keyed by tool name for the reference's two tools, with generic templates whose every fragment appears in the reference for other tools. Part B may revisit the generic ones with the owner.
10. **Reference inconsistency — controller ruling (binding):** the weather reuse's Code tab caption is hard-coded `34 lines` in the reference (line 1869) though the bundled file has 36. The user's rule is that the reference file wins, so in **demo mode** the port must show exactly `34 lines` for that caption (special-case it to match the reference). In live mode the caption is computed from the real file (`{n} lines`).
11. **Dead code not ported:** `renderSideIdle()` (empty) and `oldSideIdle()` (never called).
12. **Part A without live mode.** `resolveMode()` returns `"demo"` or `"live"`. Until part B lands, `createServices("live")` returns the demo services, so `/` runs the demo flows with the live chrome (no Demo controls). Part B replaces that branch.
13. **`@playwright/test@1.63.0`** is added in part A for the fixture generator. Part B reuses it and must not add it again.
14. **Stage 2's fake-graph sequences** weren't written when this plan was made. `DemoTransport` follows the contract, and Task 14 commits golden event logs (`src/transport/__golden__/*.json`) for the five fake-graph flows so stage 2 and part B can diff against them.
15. **Parity normalisation** (Task 2): attributes sorted; class tokens sorted; style declarations normalised (`gap: 16px;` equals `gap:16px`); empty `class`/`style` dropped; whitespace-only text containing a newline dropped (template indentation); `value` on inputs and textarea content dropped (React mirrors control values into the DOM, the reference doesn't); the `.tab-ind` inline style dropped (layout-dependent). Nothing else is normalised.

## Review Focus

1. **Stop pressed mid-run** (during the code reveal or while a test is running). Expected: everything already on screen stays exactly as it was (partially revealed code, the running test), the active steps become dashed "…, stopped", the stop note and "View this run" appear, and the composer unlocks. Pinned by the `stop-during-tests` flow parity (Task 16) and `player.test.ts › a normal-speed code reveal takes 24 ms per tick and stops where it was on abort` (Task 13).
2. **Esc in the approval or key dialog.** Expected: the run stops (it never resumes), the dialog closes, and focus returns to what had it before. Pinned by the `python-escape` flow parity (Task 16) and `dialogs.test.tsx › Escape cancels and restores focus` (Task 10).
3. **Submitting while busy, while reading an old session, or with only whitespace.** Expected: ignored, nothing is added. Pinned by `workbench.test.ts › submit guards: whitespace, busy, reading an old session` (Task 15).
4. **Reset while a run is going.** Expected: the run stops without its late events leaking into the new session, and everything returns to the boot state, including the seeded sessions and the run counter. Pinned by the `reset-mid-run` flow parity (Task 16) and `workbench.test.ts › reset drops the old run's late events` (Task 15).
5. **A query with HTML characters** (`<b>this</b> & "that"`). Expected: shown as text everywhere (message, log command, Earlier list, session card, session title), never as markup. Pinned by the `unknown-html` flow parity (Task 16) and `sessions.test.tsx › escapes queries (unknown-html flow)` (Task 12).

---

## File map

All paths are under `frontend/` unless they start with a repo-root path.

| File | Task | Responsibility |
|---|---|---|
| `.gitignore` (repo root) | 1 | ignore `frontend/node_modules/`, `frontend/dist/` |
| `package.json`, `package-lock.json`, `tsconfig*.json`, `vite.config.ts`, `eslint.config.js`, `index.html` | 1 | toolchain |
| `public/assets/apple-touch-icon.png`, `public/assets/hero-mark.webp` | 1 | copied from the reference's `assets/` |
| `scripts/reference.mjs`, `scripts/reference.d.mts` | 1 | read the reference; extract `<style>`, sources, vault data |
| `scripts/extract-reference.mjs` | 1 | writes `src/styles.css`, `src/demo/reference-data.json` |
| `src/styles.css`, `src/demo/reference-data.json` | 1 | generated verbatim copies |
| `src/test/setup.ts`, `src/test/media.ts` | 1 | jest-dom, `matchMedia` stub with a reduced-motion switch |
| `src/test/normalize.ts` | 2 | DOM normaliser for parity |
| `scripts/parity-cases.mjs`, `scripts/parity-flows.mjs`, `scripts/gen-parity-fixtures.mjs` | 2 | fixture generator (Playwright over the reference) |
| `src/test/parity/fixtures.json`, `src/test/parity/index.ts` | 2 | generated fixtures and their typed accessor |
| `src/lib/format.ts`, `highlight.ts`, `motion.ts`, `routing.ts` | 3 | the reference's helpers, ported |
| `src/lib/copy.ts`, `src/demo/data.ts` | 4 | frontend copy; demo constants and suggestions |
| `src/transport/types.ts` | 5 | the contract and API shapes, `Transport` |
| `src/store/*` | 5 | Run/message/vault types, pure ops, reducers, stores, context |
| `src/data/source.ts`, `src/demo/source.ts`, `src/demo/seeds.ts` | 5 | `DataSource` interface, demo implementation, seeded sessions |
| `src/hooks/*`, `src/test/ssr.ts` | 6 | scramble, count-up, restart animation, tab indicator, focus trap, pointer glow; server-render test helpers |
| `src/components/icons.tsx`, `Header.tsx`, `DemoControls.tsx` | 7 | shell header, shared icons |
| `src/components/workbench/Strip.tsx`, `Banner.tsx`, `Tabs.tsx`, `Bench.tsx`, `Idle.tsx` | 8 | bench frame |
| `src/components/workbench/panels/*` | 9 | Code, Tests, Attempts, Call, History, Log (+ Earlier) panels |
| `src/components/workbench/Conversation.tsx`, `Message.tsx`, `Composer.tsx` | 10 | conversation column |
| `src/components/dialogs/*` | 10 | ModalRoot, Approval, Key, Reader dialogs |
| `src/components/vault/*` | 11 | Vault view, table, detail |
| `src/components/sessions/*`, `src/components/settings/SettingsView.tsx` | 12 | Sessions and Settings views |
| `src/transport/player.ts` | 13 | event queue, pacing, event → store ops |
| `src/transport/demo.ts`, `src/transport/__golden__/*.json` | 14 | `DemoTransport` (the scripted flows) and golden event logs |
| `src/app/workbench.ts`, `src/services.ts`, `src/mode.ts`, `src/vite-env.d.ts`, `src/App.tsx`, `src/main.tsx` | 15 | controller, services, mode, app shell, boot |
| `src/test/flowHarness.tsx`, `src/app/flows.test.tsx` | 16 | end-to-end flow parity in jsdom |
| `PROGRESS.md` (repo root) | 17 | stage 04a note |

---

### Task 1: Scaffold, verbatim stylesheet and reference extraction

**Files:**
- Modify: `.gitignore` (repo root)
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/eslint.config.js`, `frontend/index.html`
- Create: `frontend/public/assets/apple-touch-icon.png`, `frontend/public/assets/hero-mark.webp` (copies)
- Create: `frontend/scripts/reference.mjs`, `frontend/scripts/reference.d.mts`, `frontend/scripts/extract-reference.mjs`
- Create (generated): `frontend/src/styles.css`, `frontend/src/demo/reference-data.json`
- Create: `frontend/src/main.tsx`, `frontend/src/test/setup.ts`, `frontend/src/test/media.ts`
- Test: `frontend/src/styles.test.ts`

**Interfaces:**
- Produces: `readRef(): string`, `extractStyle(ref): string`, `extractTextScript(ref, id): string`, `extractVaultData(ref): VaultRow[]`, `REF_BODY`, `REF_INDEX`, `REF_ASSETS` (from `scripts/reference.mjs`); `src/demo/reference-data.json` = `{ "vaultData": VaultRow[], "sources": { "src-caesar": string, "src-weather": string } }`; `setReducedMotion(on: boolean)` from `src/test/media.ts`.

- [ ] **Step 1: Create the branch and the folder**

```bash
git switch -c feat/web-04-frontend <stage-03-branch>
mkdir -p frontend/public/assets frontend/scripts frontend/src/test frontend/src/demo
cp docs/superpowers/specs/reference/workbench-demo/assets/apple-touch-icon.png docs/superpowers/specs/reference/workbench-demo/assets/hero-mark.webp frontend/public/assets/
```

- [ ] **Step 2: Add the ignores to the repo-root `.gitignore`**

Append:

```gitignore

# Frontend (frontend/)
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 3: Write `frontend/package.json`**

```json
{
  "name": "talos-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "extract": "node scripts/extract-reference.mjs",
    "fixtures": "node scripts/gen-parity-fixtures.mjs",
    "e2e": "node -e \"console.log('The e2e suite lands in stage 04b.')\""
  },
  "dependencies": {
    "react": "18.3.1",
    "react-dom": "18.3.1"
  },
  "devDependencies": {
    "@eslint/js": "9.39.5",
    "@playwright/test": "1.63.0",
    "@testing-library/dom": "10.4.1",
    "@testing-library/jest-dom": "6.10.0",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.7",
    "@types/node": "22.20.4",
    "@types/react": "18.3.31",
    "@types/react-dom": "18.3.7",
    "@vitejs/plugin-react": "4.7.0",
    "eslint": "9.39.5",
    "eslint-plugin-react-hooks": "7.1.1",
    "globals": "16.5.0",
    "jsdom": "26.1.0",
    "typescript": "5.9.3",
    "typescript-eslint": "8.71.0",
    "vite": "5.4.21",
    "vitest": "3.2.7"
  }
}
```

Run: `cd frontend && npm install --no-audit --no-fund`
Expected: `added … packages`. npm 11 may warn that esbuild's install script isn't in `allowScripts`; that's harmless (esbuild ships its binary in an optional platform package). Then `npx playwright install chromium` (downloads the headless shell once per machine).

- [ ] **Step 4: Write the TypeScript, Vite and ESLint configs**

`frontend/tsconfig.json`:

```json
{
  "files": [],
  "references": [{ "path": "./tsconfig.app.json" }, { "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.app.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom", "node"]
  },
  "include": ["src", "scripts/*.d.mts"]
}
```

`frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["node"]
  },
  "include": ["vite.config.ts"]
}
```

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    env: { TZ: "UTC" },
    testTimeout: 30000,
  },
});
```

`frontend/eslint.config.js` (the generator scripts evaluate functions inside the reference page, so `no-undef` is off for `scripts/`):

```js
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/test/parity/fixtures.json"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: { "no-undef": "off", "no-global-assign": "off" },
  },
);
```

- [ ] **Step 5: Write `frontend/index.html`** (the three font lines are lines 2–4 of the reference, verbatim)

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Talos Workbench</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Michroma&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
</head>
<body>
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

- [ ] **Step 6: Write the reference helpers**

`frontend/scripts/reference.mjs`:

```js
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// npm scripts and Vitest both run with frontend/ as the working directory.
export const REF_DIR = resolve(process.cwd(), "../docs/superpowers/specs/reference/workbench-demo");
export const REF_BODY = resolve(REF_DIR, "artifact-body.html");
export const REF_INDEX = resolve(REF_DIR, "index.html");
export const REF_ASSETS = resolve(REF_DIR, "assets");

export function readRef() {
  return readFileSync(REF_BODY, "utf8").replace(/\r\n/g, "\n");
}

export function extractStyle(ref) {
  const m = ref.match(/<style>\n([\s\S]*?)<\/style>/);
  if (!m) throw new Error("no <style> block in the reference");
  return m[1];
}

export function extractTextScript(ref, id) {
  const m = ref.match(new RegExp(`<script type="text/plain" id="${id}">([\\s\\S]*?)</script>`));
  if (!m) throw new Error(`no text script #${id} in the reference`);
  return m[1];
}

export function extractVaultData(ref) {
  const m = ref.match(/const VAULT_DATA = (\[[\s\S]*?\]);\n/);
  if (!m) throw new Error("no VAULT_DATA in the reference");
  return JSON.parse(m[1]);
}
```

`frontend/scripts/reference.d.mts`:

```ts
export type VaultRow = [
  name: string, args: string, ret: string, desc: string, kw: string[],
  uses: number, fails: number, streak: number, created: string, last: string, lastFail: string,
];
export declare const REF_DIR: string;
export declare const REF_BODY: string;
export declare const REF_INDEX: string;
export declare const REF_ASSETS: string;
export declare function readRef(): string;
export declare function extractStyle(ref: string): string;
export declare function extractTextScript(ref: string, id: string): string;
export declare function extractVaultData(ref: string): VaultRow[];
```

`frontend/scripts/extract-reference.mjs`:

```js
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { extractStyle, extractTextScript, extractVaultData, readRef } from "./reference.mjs";

const ref = readRef();
writeFileSync(resolve(process.cwd(), "src/styles.css"), extractStyle(ref));
const data = {
  vaultData: extractVaultData(ref),
  sources: {
    "src-caesar": extractTextScript(ref, "src-caesar"),
    "src-weather": extractTextScript(ref, "src-weather"),
  },
};
writeFileSync(resolve(process.cwd(), "src/demo/reference-data.json"), JSON.stringify(data, null, 1) + "\n");
console.log("wrote src/styles.css and src/demo/reference-data.json");
```

- [ ] **Step 7: Write the test setup**

`frontend/src/test/media.ts`:

```ts
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
```

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { installMatchMedia, resetMedia } from "./media";

installMatchMedia();
afterEach(() => {
  resetMedia();
  document.body.className = "";
  window.location.hash = "";
});
```

- [ ] **Step 8: Write the failing test** `frontend/src/styles.test.ts`

```ts
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { extractStyle, extractTextScript, extractVaultData, readRef, REF_ASSETS } from "../scripts/reference.mjs";

const read = (p: string) => readFileSync(resolve(process.cwd(), p), "utf8").replace(/\r\n/g, "\n");

describe("verbatim copies of the reference", () => {
  const ref = readRef();

  test("styles.css equals the reference <style> block", () => {
    expect(read("src/styles.css")).toBe(extractStyle(ref));
  });

  test("reference-data.json holds the vault rows and the two tool sources verbatim", () => {
    const data = JSON.parse(read("src/demo/reference-data.json")) as {
      vaultData: unknown[];
      sources: Record<string, string>;
    };
    expect(data.vaultData).toEqual(extractVaultData(ref));
    expect(data.vaultData).toHaveLength(40);
    expect(data.sources["src-caesar"]).toBe(extractTextScript(ref, "src-caesar"));
    expect(data.sources["src-caesar"]!.split("\n")).toHaveLength(63);
    expect(data.sources["src-weather"]).toBe(extractTextScript(ref, "src-weather"));
  });

  test("the two images are byte-identical copies", () => {
    for (const f of ["apple-touch-icon.png", "hero-mark.webp"]) {
      const mine = resolve(process.cwd(), "public/assets", f);
      expect(existsSync(mine)).toBe(true);
      expect(readFileSync(mine).equals(readFileSync(resolve(REF_ASSETS, f)))).toBe(true);
    }
  });

  test("index.html carries the reference's font links and title", () => {
    const html = read("index.html");
    for (const line of ref.split("\n").slice(0, 4)) expect(html).toContain(line);
  });
});
```

- [ ] **Step 9: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/styles.test.ts`
Expected: FAIL (`ENOENT … src/styles.css`).

- [ ] **Step 10: Generate the copies and write a minimal `main.tsx`**

Run: `npm run extract`
Expected: `wrote src/styles.css and src/demo/reference-data.json`.

`frontend/src/main.tsx` (Task 15 replaces the body):

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div className="app" />
  </StrictMode>,
);
```

- [ ] **Step 11: Run the checks**

Run: `npx vitest run src/styles.test.ts && npm run lint && npm run typecheck && npm run build`
Expected: 4 tests PASS; lint and typecheck print nothing; build prints `✓ built`.

- [ ] **Step 12: Commit**

```bash
git add .gitignore frontend
git commit -m "[Chore]: Scaffold the frontend with the reference stylesheet copied verbatim"
```

---

### Task 2: Parity toolkit: normaliser and fixture generator

**Files:**
- Create: `frontend/src/test/normalize.ts`, `frontend/src/test/normalize.test.ts`
- Create: `frontend/scripts/parity-cases.mjs`, `frontend/scripts/parity-flows.mjs`, `frontend/scripts/gen-parity-fixtures.mjs`
- Create (generated): `frontend/src/test/parity/fixtures.json`
- Create: `frontend/src/test/parity/index.ts`, `frontend/src/test/parity/fixtures.test.ts`

**Interfaces:**
- Consumes: `REF_INDEX`, `REF_BODY` from `scripts/reference.mjs`.
- Produces:
  - `normalizeHtml(html: string): string` (from `src/test/normalize.ts`).
  - `fixtureCase(id): { state: unknown; html?: string; value?: unknown }`, `flow(name): FlowFixture`, `snap(flowName, snapName): Snap`, `expectParity(actualHtml: string, expectedHtml: string): void`, `FIXED_NOW = "2026-09-30T12:00:00Z"` (from `src/test/parity/index.ts`).
  - Types: `FlowAction`, `FlowFixture = { actions: FlowAction[]; snaps: Record<string, Snap> }`, `Snap = { regions: Record<string, string | null>; run: unknown | null; pure: { strip: string; banner: string; tabs: string; panel: string } | null; vault: unknown[]; env: Record<string, string>; askExec: boolean; sessionRuns: unknown[]; viewSession: boolean; isCurrent: boolean }`.
  - `FlowAction` (JSON, shared by the generator and Task 16's harness): `{do:"submit",text}`, `{do:"click",sel}`, `{do:"fill",sel,value}`, `{do:"key",key}`, `{do:"hash",value}`, `{do:"until",cond}`, `{do:"snap",name,regions?}`, `{do:"snapAt",cond,name,regions?}`, `{do:"at",cond,click:string[]}`. `cond` is a JavaScript expression over `document`; `snapAt`/`at` fire once, at the first moment the reference is about to wait (Task 16: the first timer boundary) with `cond` true.

- [ ] **Step 1: Write the failing normaliser test** `frontend/src/test/normalize.test.ts`

```ts
import { normalizeHtml as n } from "./normalize";

describe("normalizeHtml", () => {
  test("sorts attributes and class tokens", () => {
    expect(n('<li data-node="x" class="node active">a</li>')).toBe(n('<li class="active node" data-node="x">a</li>'));
  });
  test("normalises inline styles", () => {
    expect(n('<div class="stack" style="gap:16px"></div>')).toBe(n('<div style="gap: 16px;" class="stack"></div>'));
    expect(n('<tr style=""></tr>'.replace("tr", "p"))).toBe(n("<p></p>"));
  });
  test("drops empty class", () => {
    expect(n('<tr class=""><td>x</td></tr>'.replace(/tr|td/g, "span"))).toBe(n("<span><span>x</span></span>"));
  });
  test("drops template indentation but keeps real spaces", () => {
    expect(n('<div>\n    <p>a</p>\n  </div>')).toBe(n("<div><p>a</p></div>"));
    expect(n('<span class="tx"> </span>')).not.toBe(n('<span class="tx"></span>'));
    expect(n("<button>All <span>3</span></button>")).not.toBe(n("<button>All<span>3</span></button>"));
  });
  test("keeps newlines inside text", () => {
    expect(n("<span>a\nb</span>")).not.toBe(n("<span>ab</span>"));
  });
  test("ignores control values and the tab indicator's position", () => {
    expect(n('<input id="k" value="secret">')).toBe(n('<input id="k">'));
    expect(n('<textarea id="ask">typed</textarea>')).toBe(n('<textarea id="ask"></textarea>'));
    expect(n('<span class="tab-ind" style="left: 12px; width: 40px;"></span>')).toBe(n('<span class="tab-ind"></span>'));
  });
  test("drops comments and treats boolean attributes the same", () => {
    expect(n("<p hidden><!-- x -->a</p>")).toBe(n('<p hidden="">a</p>'));
  });
  test("parses table rows outside a table", () => {
    expect(n('<tr data-tool="a"><td class="num">1</td></tr>')).toContain('<td class="num">1</td>');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/test/normalize.test.ts`
Expected: FAIL (`Failed to resolve import "./normalize"`).

- [ ] **Step 3: Write `frontend/src/test/normalize.ts`**

```ts
const VOID = new Set(["area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);

const escText = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escAttr = (s: string) => escText(s).replace(/"/g, "&quot;");

function normStyle(value: string): string {
  return value
    .split(";")
    .map((d) => d.trim())
    .filter(Boolean)
    .map((d) => {
      const i = d.indexOf(":");
      return `${d.slice(0, i).trim().toLowerCase()}:${d.slice(i + 1).trim().replace(/\s+/g, " ")}`;
    })
    .join(";");
}

function attrs(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const out: [string, string][] = [];
  for (const a of Array.from(el.attributes)) {
    let v = a.value;
    if (a.name === "value" && (tag === "input" || tag === "textarea")) continue;
    if (a.name === "style") {
      if (el.classList.contains("tab-ind")) continue;
      v = normStyle(v);
      if (!v) continue;
    }
    if (a.name === "class") {
      v = v.split(/\s+/).filter(Boolean).sort().join(" ");
      if (!v) continue;
    }
    out.push([a.name, v]);
  }
  out.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return out.map(([name, v]) => ` ${name}="${escAttr(v)}"`).join("");
}

function walk(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    let t = node.textContent ?? "";
    if (/^\s*$/.test(t) && t.includes("\n")) return "";
    t = t.replace(/^\s*\n\s*/, "").replace(/\s*\n\s*$/, "");
    return escText(t);
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node as Element;
  const tag = el.tagName.toLowerCase();
  const open = `<${tag}${attrs(el)}>`;
  if (VOID.has(tag)) return open;
  if (tag === "textarea") return `${open}</textarea>`;
  return open + Array.from(el.childNodes).map(walk).join("") + `</${tag}>`;
}

/** Canonical form of an HTML fragment for DOM-parity comparisons (plan ruling 15). */
export function normalizeHtml(html: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  return Array.from(t.content.childNodes).map(walk).join("");
}
```

- [ ] **Step 4: Run the normaliser test**

Run: `npx vitest run src/test/normalize.test.ts`
Expected: PASS (8 tests).

- [ ] **Step 5: Write `frontend/scripts/parity-cases.mjs`**

Each case's `build` runs **inside the reference page** (Playwright serialises the function), so it may only use the reference's globals and `window.__t` (installed by the generator, Step 7). It returns `{ state, html }` or `{ state, value }`.

```js
// Build cases: pure renderer outputs of the reference for hand-built states.
// Each build() runs inside the reference page and may only use its globals and window.__t.
export const CASES = [
  // lib (Task 3)
  { id: "lib/highlight-caesar", build: () => ({ state: {}, value: highlight(getSource("src-caesar")) }) },
  { id: "lib/highlight-weather", build: () => ({ state: {}, value: highlight(getSource("src-weather")) }) },
  { id: "lib/wrap-words", build: () => {
    const html = '"TALOS AGENT" encrypted with a shift of 7 is <span class="mono">AHSVZ HNLUA</span>.';
    const p = document.createElement("p"); p.innerHTML = html; const w = wrapWords(p); w.slice(0, 3).forEach((x) => x.classList.add("on"));
    return { state: { html, on: 3 }, value: p.innerHTML };
  } },
  // strip (Task 8)
  { id: "strip/forge-pending", build: () => { const run = __t.mk("forge"); return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/forge-planner-active", build: () => { const run = __t.mk("forge", { planner: "active" }); return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/forge-retry", build: () => { const run = __t.mk("forge", { planner: "done", forger: "active", tester: "forge" }, { links: { "planner-forger": true, "forger-tester": true } }); return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/forge-failed", build: () => { const run = __t.mk("forge", { planner: "done", forger: "forge", tester: "forge", human: "skip", learn: "done", executor: "fail", answer: "answer" }, { links: { "planner-forger": true, "forger-tester": true, "tester-human": true, "human-learn": true, "learn-executor": true, "executor-answer": true } }); run.nodes.executor.label = "Executor failed"; return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/vault", build: () => { const run = __t.mk("vault", { planner: "done", vault: "done" }, { links: { "planner-vault": true } }); return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/primitive-waiting", build: () => { const run = __t.mk("primitive", { planner: "done", primitive: "done", executor: "active" }); run.nodes.executor.label = "Executor, waiting for you"; return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/chat", build: () => { const run = __t.mk("chat", { planner: "done", answer: "answer" }, { links: { "planner-answer": true } }); return { state: { run }, html: stripHtml(run) }; } },
  { id: "strip/stopped", build: () => { const run = __t.mk("forge", { planner: "done", forger: "forge", tester: "stopped" }); run.nodes.tester.label = "Tester, stopped"; return { state: { run }, html: stripHtml(run) }; } },
  // banner, tabs (Task 8)
  { id: "banner/saved", build: () => { const run = __t.mk("forge", {}, { banner: { kind: "saved", name: "caesar_cipher", sub: "Next time a request needs a Caesar cipher, Talos skips forging and goes straight to Execute." } }); return { state: { run }, html: bannerHtml(run) }; } },
  { id: "banner/removed", build: () => { const run = __t.mk("vault", {}, { banner: { kind: "removed", name: "caesar_cipher", sub: "It failed 2 times in a row, so the next Caesar request will forge a fresh one. The .py file stays on disk." } }); return { state: { run }, html: bannerHtml(run) }; } },
  { id: "banner/none", build: () => { const run = __t.mk("forge"); return { state: { run }, html: bannerHtml(run) }; } },
  { id: "tabs/log-only", build: () => { const run = __t.mk("forge"); return { state: { run }, html: tabsHtml(run) }; } },
  { id: "tabs/forge", build: () => { const run = __t.mk("forge", {}, { tab: "tests", tabs: [{ id: "code", label: "Code" }, { id: "tests", label: "Tests", count: 5 }, { id: "attempts", label: "Attempts", count: 2 }, { id: "call", label: "Call" }] }); return { state: { run }, html: tabsHtml(run) }; } },
  // bench and idle (Task 8)
  { id: "bench/planning", build: () => { const run = newRun("Encrypt <b>x</b>"); initStrip(run, "forge"); run.label = "Planning"; S.cur.runs.push(run); S.current = run; S.viewing = run; S.busy = true; renderBench(run); return { state: { run: __t.clone(run), live: true, isCurrent: true }, html: bench.innerHTML }; } },
  { id: "bench/chat-done", build: () => { const run = newRun("What can you do?"); initStrip(run, "chat"); run.title = "No tools needed"; run.label = "Conversational"; run.status = "done"; run.nodes.planner.state = "done"; run.nodes.answer.state = "answer"; run.links["planner-answer"] = true; run.caption = "The Planner returned an empty plan. There's nothing to run, so Talos answers directly."; S.cur.runs.push(run); S.viewing = run; renderBench(run); return { state: { run: __t.clone(run), live: false, isCurrent: false }, html: bench.innerHTML }; } },
  { id: "idle/default", build: () => { renderIdle(); return { state: { count: S.vault.length, env: {}, askExec: true }, html: bench.innerHTML }; } },
  { id: "idle/key-set-ask-off", build: () => { S.env.OPENWEATHERMAP_API_KEY = "k"; S.askExec = false; S.vault = S.vault.slice(0, 12); renderIdle(); return { state: { count: 12, env: { OPENWEATHERMAP_API_KEY: "k" }, askExec: false }, html: bench.innerHTML }; } },
  // panels (Task 9)
  { id: "panel/code-typing", build: () => { const lines = getSource("src-caesar"); const run = __t.mk("forge", {}, { tab: "code", code: { file: "caesar_cipher.py", cap: "63 lines, attempt 1", lines, shown: 20, changed: null, note: "" } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/code-changed", build: () => { const lines = getSource("src-caesar"); const run = __t.mk("forge", {}, { tab: "code", code: { file: "caesar_cipher.py", cap: "63 lines, attempt 2", lines, shown: 63, changed: 48, flash: true, note: "Line 48 is new in attempt 2. Decrypt now shifts backwards instead of forwards." } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/tests-none", build: () => { const run = __t.mk("forge", {}, { tab: "tests" }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/tests-mixed", build: () => { const run = __t.mk("forge", {}, { tab: "tests", tests: { attempt: 1, list: [{ name: "test_encrypt_shifts_forward", state: "passed", why: "", drawn: true }, { name: "test_decrypt_reverses_encrypt", state: "failed", why: "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'" }, { name: "test_preserves_case_and_spaces", state: "running", why: "" }, { name: "test_wraps_past_z", state: "waiting", why: "" }] } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/tests-smoke-prev", build: () => { const run = __t.mk("forge", {}, { tab: "tests", tests: { attempt: 2, list: [{ name: "test_a", state: "passed", why: "" }, { name: "test_b", state: "passed", why: "", drawn: true }] }, smoke: { call: 'caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")', result: null }, attempts: [{ n: 1, ok: false, detail: "test_b\nAssertionError: x" }, { n: 2, ok: true, detail: "2 of 2 tests passed" }] }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/attempts-none", build: () => { const run = __t.mk("forge", {}, { tab: "attempts" }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/attempts", build: () => { const run = __t.mk("forge", {}, { tab: "attempts", attempts: [{ n: 1, ok: false, detail: "test_decrypt_reverses_encrypt\nAssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'" }, { n: 2, ok: null, detail: "" }] }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/call-resolving", build: () => { const run = __t.mk("forge", {}, { tab: "call", call: { args: [["text", '"TALOS AGENT"'], ["shift", "7"], ["mode", '"encrypt"']], shownArgs: 0 } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/call-result-record", build: () => { const run = __t.mk("vault", {}, { tab: "call", call: { args: [["text", '"AHSVZ HNLUA"'], ["shift", "7"], ["mode", '"decrypt"']], shownArgs: 3, result: "'TALOS AGENT'", resultType: "str", record: { forged: "30 Sep 2026, 12:00", uses: "2, including this one", fails: "None yet" } } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/call-error-health", build: () => { const run = __t.mk("vault", {}, { tab: "call", call: { args: [["text", '"AHSVZ HNLUA"'], ["shift", '"seven"', true], ["mode", '"decrypt"']], shownArgs: 3, error: "TypeError: shift must be an int, got str", when: "30 Sep 2026, 12:00", health: { streak: 1, tool: "caesar_cipher", text: 'If <span class="mono">caesar_cipher</span> fails again before it next succeeds, Talos takes it out of the vault and forges a fresh one next time. One success resets the count. The .py file stays on disk either way.', retry: { q: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"', label: "Ask again with shift 7" } } } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/call-no-args", build: () => { const run = __t.mk("primitive", {}, { tab: "call", call: { args: [], noArgs: true, argsCap: "Takes no arguments", resultCap: "Output" } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/call-pending-approval", build: () => { const run = __t.mk("primitive", {}, { tab: "call", call: { args: [["code", '"print(1)"']], argsCap: "Written by the Executor", shownArgs: 1, resultCap: "Output", pending: "Waiting for your approval" } }); return { state: { run }, html: panelHtml(run) }; } },
  { id: "panel/history", build: () => { const run = __t.mk("vault", {}, { tab: "history", toolName: "prime_factorization" }); return { state: { run, tool: __t.clone(findTool("prime_factorization")) }, html: panelHtml(run) }; } },
  { id: "panel/history-gone", build: () => { const run = __t.mk("vault", {}, { tab: "history", toolName: "nope" }); return { state: { run, tool: null }, html: panelHtml(run) }; } },
  // conversation (Task 10)
  { id: "convo/empty", build: () => { renderEmptyConvo(); return { state: {}, html: msgs.innerHTML }; } },
  { id: "convo/you", build: () => { msgs.innerHTML = ""; addYou('Encrypt "<b>x</b>" & more'); return { state: { text: 'Encrypt "<b>x</b>" & more' }, html: msgs.innerHTML }; } },
  { id: "convo/talos-thinking", build: () => { msgs.innerHTML = ""; const t = addTalos(); t.status("Planning"); return { state: { status: "Planning" }, html: msgs.innerHTML }; } },
  { id: "convo/seeded-fib", build: () => { const s = S.sessions.find((x) => x.id === "seed-fib"); return { state: { runs: s.runs.map(__t.clone) }, html: sessionHtml(s.runs) }; } },
  // dialogs (Task 10)
  { id: "dialog/approval-python", build: () => { approvalDialog("python_exec", "print(sum(range(1, 101)))"); const html = document.querySelector("#modal-root").innerHTML; S.dialog.close({ action: "cancel" }); return { state: { tool: "python_exec", code: "print(sum(range(1, 101)))" }, html }; } },
  { id: "dialog/approval-shell", build: () => { approvalDialog("shell_exec", "ls -la <dir>"); const html = document.querySelector("#modal-root").innerHTML; S.dialog.close({ action: "cancel" }); return { state: { tool: "shell_exec", code: "ls -la <dir>" }, html }; } },
  { id: "dialog/key", build: () => { keyDialog("get_current_temperature", "OPENWEATHERMAP_API_KEY", "OpenWeatherMap"); const html = document.querySelector("#modal-root").innerHTML; S.dialog.close({ action: "cancel" }); return { state: { toolName: "get_current_temperature", envVar: "OPENWEATHERMAP_API_KEY", service: "OpenWeatherMap" }, html }; } },
  { id: "dialog/reader-caesar", build: () => { readerDialog({ name: "caesar_cipher", src: "src-caesar" }); const html = document.querySelector("#modal-root").innerHTML; S.dialog.close({ action: "close" }); return { state: { name: "caesar_cipher", lines: getSource("src-caesar") }, html }; } },
  // vault (Task 11)
  { id: "vault/default", build: () => { S.selected = "caesar_cipher"; renderVault({ stagger: true }); return { state: { tools: __t.clone(S.vault), filter: "all", query: "", selected: null, stagger: true }, html: document.querySelector("#view-vault").innerHTML }; } },
  { id: "vault/fresh-selected", build: () => { S.vault.push({ name: "caesar_cipher", args: CAESAR.args, ret: CAESAR.ret, desc: CAESAR.desc, kw: CAESAR.kw, uses: 1, fails: 0, streak: 0, created: "2026-09-30T12:00", last: "2026-09-30T12:00", lastFail: "", lastFailAt: "", web: false, fresh: true, src: "src-caesar" }); S.selected = "caesar_cipher"; renderVault(); return { state: { tools: __t.clone(S.vault), filter: "all", query: "", selected: "caesar_cipher", stagger: false, source: getSource("src-caesar") }, html: document.querySelector("#view-vault").innerHTML }; } },
  { id: "vault/web", build: () => { S.filter = "web"; S.selected = "fetch_btc_price_usd"; renderVault({ stagger: true }); return { state: { tools: __t.clone(S.vault), filter: "web", query: "", selected: "fetch_btc_price_usd", stagger: true }, html: document.querySelector("#view-vault").innerHTML }; } },
  { id: "vault/failed-query", build: () => { S.filter = "failed"; S.query = "date"; S.selected = "normalize_date_strings"; renderVault(); return { state: { tools: __t.clone(S.vault), filter: "failed", query: "date", selected: "normalize_date_strings", stagger: false }, html: document.querySelector("#view-vault").innerHTML }; } },
  { id: "vault/empty", build: () => { S.query = "zzzz"; S.selected = null; renderVault(); return { state: { tools: __t.clone(S.vault), filter: "all", query: "zzzz", selected: null, stagger: false }, html: document.querySelector("#view-vault").innerHTML }; } },
  // sessions, settings (Task 12)
  { id: "sessions/boot", build: () => { renderSessions(); return { state: { sessions: S.sessions.map(__t.cloneSession), curId: S.cur.id }, html: document.querySelector("#sessions-in").innerHTML }; } },
  { id: "settings/default", build: () => { renderSettings(); return { state: { askExec: true, env: {} }, html: document.querySelector("#settings-in").innerHTML }; } },
  { id: "settings/off-key", build: () => { S.askExec = false; S.env.OPENWEATHERMAP_API_KEY = "k"; renderSettings(); return { state: { askExec: false, env: { OPENWEATHERMAP_API_KEY: "k" } }, html: document.querySelector("#settings-in").innerHTML }; } },
  // header (Task 7)
  { id: "header/default", build: () => ({ state: { busy: false, badge: false, popOpen: false, speed: 1, view: "workbench" }, html: document.querySelector("header.top").outerHTML }) },
  { id: "header/busy-badge-pop", build: () => { document.querySelector("#brand").classList.add("busy"); document.querySelector("#vault-badge").hidden = false; togglePop(true); document.querySelector('[data-speed="2"]').click(); location.hash = ""; showView("vault"); document.querySelector("#vault-badge").hidden = false; return { state: { busy: true, badge: true, popOpen: true, speed: 2, view: "vault" }, html: document.querySelector("header.top").outerHTML }; } },
  // seeds (Task 5)
  { id: "seeds/sessions", build: () => ({ state: {}, value: S.sessions.map(__t.cloneSession) }) },
];
```

- [ ] **Step 6: Write `frontend/scripts/parity-flows.mjs`**

```js
// Scripted flows over the real reference. Task 16 replays the same actions against the React app.
export const DEFAULT_REGIONS = ["header.top", "#msgs", "#live", "#bench", ".composer", "#modal-root"];

const SEND_READY = `document.querySelector("#send").textContent === "Send" && !document.querySelector("#brand").classList.contains("busy")`;
export const DONE = `(${SEND_READY}) && !document.querySelector("#modal-root .dialog")`;
export const DIALOG = `!!document.querySelector("#modal-root .dialog")`;

export const Q = {
  forge: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.',
  reuse: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  wordShift: 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"',
  python: "Run this Python code and give me the output: print(sum(range(1, 101)))",
  weather: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
  chat: "What can you do?",
  vaultlist: "How many tools are in your vault?",
  unknown: 'Summarise <b>this</b> PDF & "that" one',
};

const forge = [{ do: "click", sel: '[data-suggest="0"]' }, { do: "until", cond: DONE }];
const vaultRegions = ["#view-vault", "header.top"];

export const FLOWS = {
  boot: [{ do: "snap", name: "idle" }],
  "caesar-forge": [
    { do: "snapAt", name: "planning", cond: `!!document.querySelector('[data-node="planner"].active')` },
    { do: "snapAt", name: "forging", cond: `!!document.querySelector('.code-row[data-ln="30"]') && !!document.querySelector('[data-node="forger"].active')` },
    { do: "snapAt", name: "test-failed", cond: `!!document.querySelector(".tests li.failed")` },
    { do: "snapAt", name: "retry", cond: `!!document.querySelector('[data-node="forger"].active') && !!document.querySelector(".code-row.changed")` },
    { do: "snapAt", name: "smoke", cond: `!!document.querySelector(".smoke-body .caret")` },
    { do: "snapAt", name: "saved", cond: `!!document.querySelector(".banner:not(.removed)") && !document.querySelector('[data-node="executor"].active')` },
    { do: "snapAt", name: "args", cond: `document.querySelectorAll(".args dd").length === 2` },
    ...forge,
    { do: "snap", name: "end" },
    { do: "hash", value: "#vault" },
    { do: "snap", name: "vault", regions: vaultRegions },
    { do: "click", sel: '[data-read-src="caesar_cipher"]' },
    { do: "snap", name: "reader", regions: ["#modal-root"] },
    { do: "key", key: "Escape" },
    { do: "hash", value: "#sessions" },
    { do: "snap", name: "sessions", regions: ["#view-sessions"] },
    { do: "hash", value: "#settings" },
    { do: "snap", name: "settings", regions: ["#view-settings"] },
  ],
  "caesar-reuse": [
    ...forge,
    { do: "snapAt", name: "vault-step", cond: `!!document.querySelector('[data-node="vault"].done') && !document.querySelector('[data-node="executor"].active')` },
    { do: "submit", text: Q.reuse },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
    { do: "click", sel: '[data-tab="code"]' },
    { do: "snap", name: "code-tab" },
    { do: "click", sel: '[data-tab="history"]' },
    { do: "snap", name: "history-tab" },
    { do: "click", sel: '[data-tab="log"]' },
    { do: "snap", name: "log-tab" },
    { do: "click", sel: '.earlier button[data-run="6"]' },
    { do: "snap", name: "earlier-run" },
  ],
  "caesar-fail": [
    ...forge,
    { do: "submit", text: Q.wordShift },
    { do: "until", cond: DONE },
    { do: "snap", name: "fail-1" },
    { do: "submit", text: Q.wordShift },
    { do: "until", cond: DONE },
    { do: "snap", name: "fail-2" },
    { do: "hash", value: "#vault" },
    { do: "snap", name: "vault", regions: vaultRegions },
  ],
  "python-approve": [
    { do: "click", sel: '[data-suggest="2"]' },
    { do: "until", cond: DIALOG },
    { do: "snap", name: "dialog" },
    { do: "click", sel: '[data-d="yes"]' },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
  ],
  "python-decline": [
    { do: "click", sel: '[data-suggest="2"]' },
    { do: "until", cond: DIALOG },
    { do: "click", sel: '[data-d="no"]' },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
  ],
  "python-escape": [
    { do: "click", sel: '[data-suggest="2"]' },
    { do: "until", cond: DIALOG },
    { do: "key", key: "Escape" },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
  ],
  "python-no-ask": [
    { do: "hash", value: "#settings" },
    { do: "click", sel: "#ask-switch" },
    { do: "snap", name: "settings-off", regions: ["#view-settings"] },
    { do: "hash", value: "#workbench" },
    { do: "snap", name: "idle-off" },
    { do: "submit", text: Q.python },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
  ],
  "weather-save": [
    { do: "click", sel: '[data-suggest="3"]' },
    { do: "until", cond: DIALOG },
    { do: "snap", name: "dialog" },
    { do: "click", sel: '#modal-root button[type="submit"]' },
    { do: "snap", name: "dialog-error", regions: ["#modal-root"] },
    { do: "fill", sel: "#dlg-key", value: "owm-test-key" },
    { do: "click", sel: '#modal-root button[type="submit"]' },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
    { do: "hash", value: "#settings" },
    { do: "snap", name: "settings-key", regions: ["#view-settings"] },
    { do: "hash", value: "#workbench" },
    { do: "submit", text: Q.weather },
    { do: "until", cond: DONE },
    { do: "snap", name: "reuse-end" },
  ],
  "weather-skip": [
    { do: "click", sel: '[data-suggest="3"]' },
    { do: "until", cond: DIALOG },
    { do: "click", sel: '[data-d="skip"]' },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" },
    { do: "submit", text: Q.weather },
    { do: "until", cond: DONE },
    { do: "snap", name: "reuse-fail" },
  ],
  chat: [{ do: "submit", text: Q.chat }, { do: "until", cond: DONE }, { do: "snap", name: "end" }],
  vaultlist: [{ do: "submit", text: Q.vaultlist }, { do: "until", cond: DONE }, { do: "snap", name: "end" }],
  "unknown-html": [
    { do: "submit", text: Q.unknown },
    { do: "until", cond: DONE },
    { do: "snap", name: "end" }, // one-tab runs show the run log without a tab bar
    { do: "hash", value: "#sessions" },
    { do: "snap", name: "sessions", regions: ["#view-sessions"] },
  ],
  "stop-during-tests": [
    { do: "at", cond: `!!document.querySelector(".tests li.running")`, click: ['[data-action="stop"]'] },
    ...forge,
    { do: "snap", name: "end" },
  ],
  "reset-mid-run": [
    { do: "at", cond: `!!document.querySelector('.code-row[data-ln="10"]')`, click: ["#demo-toggle", "#demo-reset"] },
    { do: "click", sel: '[data-suggest="0"]' },
    { do: "until", cond: `(${SEND_READY}) && !!document.querySelector("#bench .idle")` },
    { do: "snap", name: "end" },
    { do: "hash", value: "#sessions" },
    { do: "snap", name: "sessions", regions: ["#view-sessions"] },
  ],
  sessions: [
    ...forge,
    { do: "click", sel: "#new-session" },
    { do: "snap", name: "new-session" },
    { do: "hash", value: "#sessions" },
    { do: "snap", name: "list", regions: ["#view-sessions"] },
    { do: "click", sel: '[data-open-session="seed-fib"]' },
    { do: "until", cond: `!!document.querySelector(".viewing-note")` },
    { do: "snap", name: "old-session" },
    { do: "click", sel: '.run-link[data-run="1"]' },
    { do: "snap", name: "old-run" },
    { do: "click", sel: "#back-session" },
    { do: "snap", name: "back-to-now" },
  ],
  "vault-browse": [
    { do: "hash", value: "#vault" },
    { do: "snap", name: "default", regions: vaultRegions },
    { do: "fill", sel: "#v-search", value: "hex" },
    { do: "snap", name: "search", regions: vaultRegions },
    { do: "fill", sel: "#v-search", value: "zzzz" },
    { do: "snap", name: "empty", regions: vaultRegions },
    { do: "fill", sel: "#v-search", value: "" },
    { do: "click", sel: '[data-filter="web"]' },
    { do: "snap", name: "web", regions: vaultRegions },
    { do: "click", sel: '[data-filter="failed"]' },
    { do: "snap", name: "failed", regions: vaultRegions },
    { do: "click", sel: '[data-tool="flatten_json"]' },
    { do: "snap", name: "detail", regions: vaultRegions },
    { do: "click", sel: '[data-remove-tool="flatten_json"]' },
    { do: "snap", name: "confirm", regions: vaultRegions },
    { do: "click", sel: '[data-remove-tool="flatten_json"]' },
    { do: "snap", name: "removed", regions: vaultRegions },
  ],
  "demo-controls": [
    { do: "click", sel: "#demo-toggle" },
    { do: "snap", name: "open", regions: ["header.top"] },
    { do: "click", sel: '[data-speed="2"]' },
    { do: "snap", name: "fast", regions: ["header.top"] },
    { do: "key", key: "Escape" },
    { do: "snap", name: "closed", regions: ["header.top"] },
  ],
};
```

- [ ] **Step 7: Write `frontend/scripts/gen-parity-fixtures.mjs`**

```js
// Runs the reference in headless Chromium and writes src/test/parity/fixtures.json.
// Regenerate with `npm run fixtures` whenever a case or flow changes. Never edit the output by hand.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";
import { CASES } from "./parity-cases.mjs";
import { DEFAULT_REGIONS, FLOWS } from "./parity-flows.mjs";
import { REF_BODY, REF_INDEX } from "./reference.mjs";

export const FIXED_NOW = "2026-09-30T12:00:00Z";
const OUT = resolve(process.cwd(), "src/test/parity/fixtures.json");

/** Installed in the page: clone helpers, state builders, snapshots and checkpoint hooks. */
function installHarness(defaultRegions) {
  const clone = (run) => {
    if (!run) return null;
    return JSON.parse(JSON.stringify(run, (k, v) => (k === "talos" || k === "timers" ? undefined : v)));
  };
  const cloneSession = (s) => ({ id: s.id, name: s.name, started: s.started, live: s.live, runs: s.runs.map(clone) });
  const pure = (run) => {
    const c = clone(run);
    const list = (S.viewSession || S.cur).runs;
    const i = list.indexOf(run);
    const cur = S.current;
    if (i >= 0) list[i] = c;
    if (cur === run) S.current = c;
    try {
      return { strip: stripHtml(c), banner: bannerHtml(c), tabs: tabsHtml(c), panel: panelHtml(c) };
    } finally {
      if (i >= 0) list[i] = run;
      S.current = cur;
    }
  };
  const snap = (regions) => {
    const out = {};
    for (const sel of regions || defaultRegions) {
      const el = document.querySelector(sel);
      out[sel] = el ? el.outerHTML : null;
    }
    return {
      regions: out,
      run: clone(S.viewing),
      pure: S.viewing ? pure(S.viewing) : null,
      vault: JSON.parse(JSON.stringify(S.vault)),
      env: { ...S.env },
      askExec: S.askExec,
      sessionRuns: (S.viewSession || S.cur).runs.map(clone),
      viewSession: !!S.viewSession,
      isCurrent: !!S.viewing && S.viewing === S.current,
    };
  };
  window.__t = {
    clone, cloneSession, snap, snaps: {}, hooks: [],
    mk(variant, states = {}, extra = {}) {
      const run = newRun(extra.query || "q");
      initStrip(run, variant);
      for (const [k, v] of Object.entries(states)) run.nodes[k].state = v;
      Object.assign(run, extra);
      return run;
    },
  };
  const orig = wait;
  wait = (run, ms) => {
    for (const h of window.__t.hooks) {
      if (h.done || !new Function(`return (${h.cond});`)()) continue;
      h.done = true;
      if (h.kind === "snapAt") window.__t.snaps[h.name] = snap(h.regions);
      else for (const sel of h.click) document.querySelector(sel).click();
    }
    return orig(run, ms);
  };
}

async function newPage(browser) {
  const ctx = await browser.newContext({ reducedMotion: "reduce", timezoneId: "UTC", viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.route(/^https?:/, (r) => r.abort());
  await page.clock.setFixedTime(new Date(FIXED_NOW));
  await page.goto(pathToFileURL(REF_INDEX).href);
  await page.evaluate(installHarness, DEFAULT_REGIONS);
  return { ctx, page };
}

async function runFlow(page, actions) {
  const snaps = {};
  for (const a of actions) {
    switch (a.do) {
      case "submit":
        await page.fill("#ask", a.text);
        // Don't return the promise: submit() only settles when the run ends.
        await page.evaluate(() => { document.querySelector("#composer").requestSubmit(); });
        break;
      case "click":
        await page.evaluate((sel) => { document.querySelector(sel).click(); }, a.sel);
        break;
      case "fill":
        await page.fill(a.sel, a.value);
        break;
      case "key":
        await page.keyboard.press(a.key);
        break;
      case "hash":
        await page.evaluate((h) => { location.hash = h; }, a.value);
        await page.waitForFunction((h) => location.hash === h && S.view === h.slice(1), a.value);
        break;
      case "until":
        await page.waitForFunction(a.cond, null, { timeout: 60000 });
        break;
      case "snap":
        snaps[a.name] = await page.evaluate((r) => window.__t.snap(r), a.regions ?? null);
        break;
      case "snapAt":
      case "at":
        await page.evaluate((h) => { window.__t.hooks.push({ ...h, kind: h.do, done: false }); }, a);
        break;
      default:
        throw new Error(`unknown action ${a.do}`);
    }
  }
  const hooked = await page.evaluate(() => window.__t.snaps);
  for (const a of actions) {
    if (a.do === "snapAt" && !hooked[a.name]) throw new Error(`checkpoint ${a.name} never fired`);
  }
  return { ...hooked, ...snaps };
}

const browser = await chromium.launch();
try {
  const out = {
    generatedAt: FIXED_NOW,
    reference: createHash("sha256").update(readFileSync(REF_BODY)).digest("hex"),
    cases: {},
    flows: {},
  };
  for (const c of CASES) {
    const { ctx, page } = await newPage(browser);
    out.cases[c.id] = await page.evaluate(c.build);
    await ctx.close();
  }
  for (const [name, actions] of Object.entries(FLOWS)) {
    const { ctx, page } = await newPage(browser);
    out.flows[name] = { actions, snaps: await runFlow(page, actions) };
    await ctx.close();
    console.log(`flow ${name}: ${Object.keys(out.flows[name].snaps).length} snapshots`);
  }
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(out, null, 1) + "\n");
  console.log(`wrote ${Object.keys(out.cases).length} cases and ${Object.keys(out.flows).length} flows to ${OUT}`);
} finally {
  await browser.close();
}
```

Note for the implementer: the hash action waits for `S.view` to change, except that `location.hash = "#workbench"` when the view is already `workbench` is a no-op for `hashchange` but `S.view` already matches, so the wait still passes.

- [ ] **Step 8: Generate the fixtures**

Run: `npm run fixtures`
Expected: one `flow …: N snapshots` line per flow, then `wrote 53 cases and 18 flows to …/fixtures.json` (about 3 MB; it takes under a minute). If a `checkpoint … never fired` error appears, the checkpoint's `cond` is wrong: fix the condition, never the reference.

- [ ] **Step 9: Write the typed accessor** `frontend/src/test/parity/index.ts`

```ts
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect } from "vitest";
import raw from "./fixtures.json";
import { normalizeHtml } from "../normalize";

export const FIXED_NOW = "2026-09-30T12:00:00Z";

export type FlowAction =
  | { do: "submit"; text: string }
  | { do: "click"; sel: string }
  | { do: "fill"; sel: string; value: string }
  | { do: "key"; key: string }
  | { do: "hash"; value: string }
  | { do: "until"; cond: string }
  | { do: "snap"; name: string; regions?: string[] }
  | { do: "snapAt"; name: string; cond: string; regions?: string[] }
  | { do: "at"; cond: string; click: string[] };

export interface Snap {
  regions: Record<string, string | null>;
  run: unknown;
  pure: { strip: string; banner: string; tabs: string; panel: string } | null;
  vault: unknown[];
  env: Record<string, string>;
  askExec: boolean;
  sessionRuns: unknown[];
  viewSession: boolean;
  isCurrent: boolean;
}
export interface FlowFixture {
  actions: FlowAction[];
  snaps: Record<string, Snap>;
}
export interface CaseFixture {
  state: Record<string, unknown>;
  html?: string;
  value?: unknown;
}

const data = raw as unknown as {
  generatedAt: string;
  reference: string;
  cases: Record<string, CaseFixture>;
  flows: Record<string, FlowFixture>;
};

export const fixtureSha = data.reference;
export const referenceSha = () =>
  createHash("sha256")
    .update(readFileSync(resolve(process.cwd(), "../docs/superpowers/specs/reference/workbench-demo/artifact-body.html")))
    .digest("hex");

export function fixtureCase(id: string): CaseFixture {
  const c = data.cases[id];
  if (!c) throw new Error(`no parity case ${id}; add it to scripts/parity-cases.mjs and run npm run fixtures`);
  return c;
}
export function flow(name: string): FlowFixture {
  const f = data.flows[name];
  if (!f) throw new Error(`no parity flow ${name}`);
  return f;
}
export function snap(flowName: string, snapName: string): Snap {
  const s = flow(flowName).snaps[snapName];
  if (!s) throw new Error(`no snapshot ${flowName}/${snapName}`);
  return s;
}
export const allFlows = () => Object.keys(data.flows);

/** Asserts DOM parity after normalisation. */
export function expectParity(actualHtml: string, expectedHtml: string): void {
  expect(normalizeHtml(actualHtml)).toBe(normalizeHtml(expectedHtml));
}
```

- [ ] **Step 10: Write the fixture sanity test** `frontend/src/test/parity/fixtures.test.ts`

```ts
import { allFlows, fixtureCase, fixtureSha, flow, referenceSha } from ".";

test("fixtures were generated from the current reference", () => {
  expect(fixtureSha).toBe(referenceSha());
});

test("every flow has its snapshots", () => {
  expect(allFlows()).toHaveLength(18);
  expect(Object.keys(flow("caesar-forge").snaps).sort()).toEqual(
    ["args", "end", "forging", "planning", "reader", "retry", "saved", "sessions", "settings", "smoke", "test-failed", "vault"].sort(),
  );
  expect(flow("stop-during-tests").snaps.end!.regions["#bench"]).toContain("Tester, stopped");
});

test("cases carry html or a value", () => {
  expect(fixtureCase("strip/forge-pending").html).toContain('data-node="planner"');
  expect(fixtureCase("lib/highlight-caesar").value).toHaveLength(63);
});
```

- [ ] **Step 11: Run all tests, lint and typecheck**

Run: `npx vitest run && npm run lint && npm run typecheck`
Expected: PASS; no lint or type errors.

- [ ] **Step 12: Commit**

```bash
git add frontend
git commit -m "[Feat]: Add the DOM-parity normaliser and the reference fixture generator"
```

---

### Task 3: The reference's helpers (format, highlight, motion, routing)

**Files:**
- Create: `frontend/src/lib/format.ts`, `frontend/src/lib/highlight.ts`, `frontend/src/lib/motion.ts`, `frontend/src/lib/routing.ts`
- Test: `frontend/src/lib/format.test.ts`, `frontend/src/lib/highlight.test.ts`, `frontend/src/lib/motion.test.ts`, `frontend/src/lib/routing.test.ts`

**Interfaces:**
- Consumes: `fixtureCase`, `expectParity` (Task 2); `src/demo/reference-data.json` (Task 1).
- Produces (exact names; later tasks import them):
  - `format.ts`: `MONTHS`, `esc(s: unknown): string`, `fmtTime(iso?: string | null): string`, `fmtClock(iso: string): string`, `fmtShort(iso: string): string`, `fmtDay(iso: string): string`, `sameDay(iso: string): boolean`, `nowIso(): string`, `splitArgs(args: string): string[]`, `argNames(args: string): string`, `pyRepr(v: unknown): string`, `pyStr(v: unknown): string`.
  - `highlight.ts`: `highlight(lines: string[]): string[]`.
  - `motion.ts`: `GLYPHS`, `still(): boolean`, `scramble(el: HTMLElement | null, finalText: string, duration?: number): () => void`, `countUp(el: HTMLElement | null, target: number): () => void`, `wrapWordsHtml(html: string, onCount: number): { html: string; count: number }`.
  - `routing.ts`: `PRUNE_AT = 2`, `NUM_WORDS`, `QueryKind = "chat" | "caesar" | "python" | "weather" | "vaultlist" | "unknown"`, `caesar(text, shift, mode): string`, `parseCaesar(text): CaesarParams`, `classify(q): QueryKind`, `runPython(code): string | null`, `sessionName(kind, q): string`, `provisionalVariant(query: string, vaultNames: string[]): Variant`, `CaesarParams = { text: string; shift: number; shiftWord: string | null; mode: "encrypt" | "decrypt" }`.

Each function is the reference's code with types added and nothing else changed. Line numbers: `esc` 827, `fmtTime` 834–840, `fmtClock` 841–844, `nowIso` 845–849, `splitArgs` 850–859, `argNames` 860, `pyRepr` 861, `pyStr` 862, `scramble` 864–877, `caesar` 879–888, `KW`/`highlight` 891–909, `wrapWords` 972–986, `countUp` 1079–1084, `sameDay` 1982, `fmtShort` 1983, `fmtDay` 2256, `parseCaesar` 1423–1435, `classify` 1436–1443, `runPython` 1766–1778, `sessionName` 2169–2177.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/format.test.ts`:

```ts
import { argNames, esc, fmtClock, fmtDay, fmtShort, fmtTime, nowIso, pyRepr, pyStr, sameDay, splitArgs } from "./format";
import { FIXED_NOW } from "../test/parity";

afterEach(() => vi.useRealTimers());

test("fmtTime, fmtClock, fmtShort, fmtDay", () => {
  expect(fmtTime("")).toBe("Never");
  expect(fmtTime(null)).toBe("Never");
  expect(fmtTime("2026-09-28T14:20")).toBe("28 Sep 2026, 14:20");
  expect(fmtClock("2026-09-28T09:05")).toBe("09:05");
  expect(fmtShort("2026-09-28T14:44")).toBe("28 Sep, 14:44");
  expect(fmtDay("2026-09-28T14:20")).toBe("28 Sep 2026");
});

test("nowIso and sameDay use the local clock", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
  expect(nowIso()).toBe("2026-09-30T12:00");
  expect(sameDay("2026-09-30T08:00")).toBe(true);
  expect(sameDay("2026-09-28T14:20")).toBe(false);
});

test("splitArgs keeps brackets together and argNames keeps only names", () => {
  expect(splitArgs("headers: list[str], rows: list[list[str]]")).toEqual(["headers: list[str]", "rows: list[list[str]]"]);
  expect(splitArgs("a: tuple[int, int], b: dict")).toEqual(["a: tuple[int, int]", "b: dict"]);
  expect(splitArgs("")).toEqual([]);
  expect(argNames("lat1: float, lon1: float, lat2: float, lon2: float")).toBe("lat1, lon1, lat2, lon2");
  expect(argNames("code: str, timeout: int | None = None")).toBe("code, timeout");
});

test("esc, pyRepr, pyStr", () => {
  expect(esc(`<a href="x">it's & </a>`)).toBe("&lt;a href=&quot;x&quot;&gt;it&#39;s &amp; &lt;/a&gt;");
  expect(pyRepr("TALOS")).toBe('"TALOS"');
  expect(pyRepr(7)).toBe("7");
  expect(pyStr("AHSVZ HNLUA")).toBe("'AHSVZ HNLUA'");
  expect(pyStr("it's")).toBe("'it\\'s'");
});
```

`frontend/src/lib/highlight.test.ts`:

```ts
import data from "../demo/reference-data.json";
import { fixtureCase } from "../test/parity";
import { highlight } from "./highlight";

test("highlight() matches the reference function on caesar_cipher.py", () => {
  const lines = data.sources["src-caesar"].split("\n");
  expect(highlight(lines)).toEqual(fixtureCase("lib/highlight-caesar").value);
});

test("highlight() matches the reference function on get_current_temperature.py", () => {
  const lines = data.sources["src-weather"].split("\n");
  expect(highlight(lines)).toEqual(fixtureCase("lib/highlight-weather").value);
});

test("docstrings are one string span per line and keywords are marked", () => {
  const out = highlight(['def f(x):', '    """Doc', '    more"""', '    return None']);
  expect(out[0]).toBe('<span class="kw">def</span> f(x):');
  expect(out[1]).toBe('<span class="str">    &quot;&quot;&quot;Doc</span>');
  expect(out[2]).toBe('<span class="str">    more&quot;&quot;&quot;</span>');
  expect(out[3]).toBe('    <span class="kw">return</span> <span class="kw">None</span>');
});
```

`frontend/src/lib/motion.test.ts`:

```ts
import { countUp, GLYPHS, scramble, still, wrapWordsHtml } from "./motion";
import { setReducedMotion } from "../test/media";
import { expectParity, fixtureCase } from "../test/parity";

afterEach(() => vi.useRealTimers());

test("still() follows prefers-reduced-motion", () => {
  expect(still()).toBe(true);
  setReducedMotion(false);
  expect(still()).toBe(false);
});

test("wrapWordsHtml matches the reference wrapWords with the first words on", () => {
  const c = fixtureCase("lib/wrap-words");
  const { html, on } = c.state as { html: string; on: number };
  const out = wrapWordsHtml(html, on);
  expectParity(out.html, c.value as string);
  expect(out.count).toBe(12); // the "." after the mono span is its own text node, so its own word
});

test("scramble settles on the final text, instantly under reduced motion", () => {
  const el = document.createElement("span");
  scramble(el, "caesar_cipher");
  expect(el.textContent).toBe("caesar_cipher");

  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
  const el2 = document.createElement("span");
  scramble(el2, "Session 2", 600);
  vi.advanceTimersByTime(100);
  expect(el2.textContent).toHaveLength("Session 2".length);
  expect([...el2.textContent!].some((ch, i) => ch !== "Session 2"[i] && GLYPHS.includes(ch))).toBe(true);
  vi.advanceTimersByTime(700);
  expect(el2.textContent).toBe("Session 2");
});

test("countUp does nothing under reduced motion and eases to the target otherwise", () => {
  const el = document.createElement("span");
  el.textContent = "40";
  countUp(el, 40);
  expect(el.textContent).toBe("40");

  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
  countUp(el, 40);
  vi.advanceTimersByTime(300);
  expect(Number(el.textContent)).toBeGreaterThan(0);
  expect(Number(el.textContent)).toBeLessThan(40);
  vi.advanceTimersByTime(1000);
  expect(el.textContent).toBe("40");
});
```

`frontend/src/lib/routing.test.ts`:

```ts
import { caesar, classify, parseCaesar, provisionalVariant, runPython, sessionName } from "./routing";

const Q = {
  forge: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.',
  reuse: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  wordShift: 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"',
  python: "Run this Python code and give me the output: print(sum(range(1, 101)))",
  weather: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};

test("caesar", () => {
  expect(caesar("TALOS AGENT", 7, "encrypt")).toBe("AHSVZ HNLUA");
  expect(caesar("AHSVZ HNLUA", 7, "decrypt")).toBe("TALOS AGENT");
  expect(caesar("xyz, XYZ!", 3, "encrypt")).toBe("abc, ABC!");
  expect(caesar("abc", -1, "encrypt")).toBe("zab");
  expect(caesar("abc", 27, "encrypt")).toBe("bcd");
});

test("parseCaesar", () => {
  expect(parseCaesar(Q.forge)).toEqual({ text: "TALOS AGENT", shift: 7, shiftWord: null, mode: "encrypt" });
  expect(parseCaesar(Q.reuse)).toEqual({ text: "AHSVZ HNLUA", shift: 7, shiftWord: null, mode: "decrypt" });
  expect(parseCaesar(Q.wordShift)).toEqual({ text: "AHSVZ HNLUA", shift: 7, shiftWord: "seven", mode: "decrypt" });
  expect(parseCaesar("Encrypt “hi there” with shift of 3")).toEqual({ text: "hi there", shift: 3, shiftWord: null, mode: "encrypt" });
  expect(parseCaesar("decrypt with a caesar cipher")).toEqual({ text: "AHSVZ HNLUA", shift: 7, shiftWord: null, mode: "decrypt" });
  expect(parseCaesar("shift to the right, caesar")).toMatchObject({ shift: 7, shiftWord: null });
});

test("classify", () => {
  expect(classify("What can you do?")).toBe("chat");
  expect(classify(Q.forge)).toBe("caesar");
  expect(classify(Q.python)).toBe("python");
  expect(classify(Q.weather)).toBe("weather");
  expect(classify("How many tools are in your vault?")).toBe("vaultlist");
  expect(classify("Summarise this PDF")).toBe("unknown");
});

test("runPython", () => {
  expect(runPython("print(sum(range(1, 101)))")).toBe("5050");
  expect(runPython('print("hi")')).toBe("hi");
  expect(runPython("print(2 * (3 + 4))")).toBe("14");
  expect(runPython("print(open('x'))")).toBeNull();
  expect(runPython("import os")).toBeNull();
});

test("sessionName", () => {
  expect(sessionName("caesar", Q.forge)).toBe("Caesar cipher");
  expect(sessionName("python", Q.python)).toBe("Running Python");
  expect(sessionName("weather", Q.weather)).toBe("Weather in Mumbai");
  expect(sessionName("weather", "What's the temperature in New York?")).toBe("Weather in New York");
  expect(sessionName("chat", "What can you do?")).toBe("Getting to know Talos");
  expect(sessionName("vaultlist", "How many tools")).toBe("What's in the vault");
  expect(sessionName("unknown", "summarise <b>this</b> PDF & more")).toBe("Summarise <b>this</b> PDF &");
});

test("provisionalVariant mirrors the reference's first strip", () => {
  expect(provisionalVariant(Q.forge, [])).toBe("forge");
  expect(provisionalVariant(Q.reuse, ["caesar_cipher"])).toBe("vault");
  expect(provisionalVariant(Q.weather, [])).toBe("forge");
  expect(provisionalVariant(Q.weather, ["get_current_temperature"])).toBe("vault");
  expect(provisionalVariant(Q.python, [])).toBe("primitive");
  expect(provisionalVariant("How many tools are in your vault?", [])).toBe("primitive");
  expect(provisionalVariant("What can you do?", [])).toBe("chat");
  expect(provisionalVariant("Summarise this", [])).toBe("chat");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/lib`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write `frontend/src/lib/format.ts`**

```ts
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s: unknown): string => String(s).replace(/[&<>"']/g, (c) => ESC[c] ?? c);

export function fmtTime(iso?: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`;
}
export function fmtClock(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
export function nowIso(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function splitArgs(args: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of args) {
    if (ch === "[" || ch === "(") depth++;
    if (ch === "]" || ch === ")") depth--;
    if (ch === "," && depth === 0) {
      out.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}
export const argNames = (args: string): string =>
  splitArgs(args)
    .map((a) => (a.split(":")[0] ?? "").trim())
    .join(", ");
export const pyRepr = (v: unknown): string => (typeof v === "string" ? JSON.stringify(v) : String(v));
export const pyStr = (v: unknown): string => `'${String(v).replace(/'/g, "\\'")}'`;
export const sameDay = (iso: string): boolean => new Date(iso).toDateString() === new Date().toDateString();
export const fmtShort = (iso: string): string => {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${fmtClock(iso)}`;
};
export const fmtDay = (iso: string): string => {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};
```

- [ ] **Step 4: Write `frontend/src/lib/highlight.ts`**

```ts
import { esc } from "./format";

const KW = /\b(def|return|if|elif|else|for|in|not|or|and|is|raise|import|from|continue|None|True|False)\b/g;

/** Python-ish highlighter for code panels. Returns the reference's exact HTML strings (line 892). */
export function highlight(lines: string[]): string[] {
  let inDoc = false;
  return lines.map((raw) => {
    const e = esc(raw);
    const triple = (raw.match(/"""/g) || []).length;
    if (inDoc || raw.trim().startsWith('"""')) {
      const html = `<span class="str">${e}</span>`;
      if (inDoc && triple) inDoc = false;
      else if (!inDoc && triple === 1) inDoc = true;
      return html;
    }
    let h = e.replace(/(f?&quot;.*?&quot;|&#39;.*?&#39;)/g, "\u0000$1\u0001");
    h = h
      // eslint-disable-next-line no-control-regex -- the reference marks strings with \u0000…\u0001
      .split(/(\u0000[^\u0001]*\u0001)/)
      .map((part) =>
        part.startsWith("\u0000") ? `<span class="str">${part.slice(1, -1)}</span>` : part.replace(KW, '<span class="kw">$1</span>'),
      )
      .join("");
    return h;
  });
}
```

- [ ] **Step 5: Write `frontend/src/lib/motion.ts`**

```ts
export const GLYPHS = "ΛΣΔ01<>/#_+=*";

/** The reference reads this once at load (line 828); a function lets tests switch it. */
export const still = (): boolean =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Decodes `finalText` into `el` from random glyphs (line 864). Returns a cancel function. */
export function scramble(el: HTMLElement | null, finalText: string, duration = 900): () => void {
  if (!el) return () => {};
  if (still()) {
    el.textContent = finalText;
    return () => {};
  }
  let frame = 0;
  const start = performance.now();
  const tick = (now: number) => {
    const p = Math.min((now - start) / duration, 1);
    const settled = Math.floor(p * finalText.length);
    let out = finalText.slice(0, settled);
    for (let i = settled; i < finalText.length; i++) out += finalText[i] === " " ? " " : GLYPHS[(Math.random() * GLYPHS.length) | 0];
    el.textContent = out;
    if (p < 1) frame = requestAnimationFrame(tick);
    else el.textContent = finalText;
  };
  frame = requestAnimationFrame(tick);
  return () => {
    cancelAnimationFrame(frame);
    el.textContent = finalText;
  };
}

/** Counts `el` up to `target` over 1.2 s with an ease-out cubic (line 1079). */
export function countUp(el: HTMLElement | null, target: number): () => void {
  if (!el || still()) return () => {};
  let frame = 0;
  const start = performance.now();
  const tick = (now: number) => {
    const p = Math.min((now - start) / 1200, 1);
    el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
    if (p < 1) frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}

/**
 * The reference's wrapWords (line 972) as a string transform: every word of every text node becomes
 * <span class="wd">, and the first `onCount` get "wd on". Returns the HTML and the number of words.
 */
export function wrapWordsHtml(html: string, onCount: number): { html: string; count: number } {
  const root = document.createElement("p");
  root.innerHTML = html;
  const nodes: Text[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  let count = 0;
  for (const t of nodes) {
    const frag = document.createDocumentFragment();
    for (const part of (t.textContent ?? "").split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s+$/.test(part)) {
        frag.append(part);
        continue;
      }
      const w = document.createElement("span");
      w.className = count < onCount ? "wd on" : "wd";
      w.textContent = part;
      frag.append(w);
      count++;
    }
    t.replaceWith(frag);
  }
  return { html: root.innerHTML, count };
}
```

- [ ] **Step 6: Write `frontend/src/lib/routing.ts`**

```ts
import type { Variant } from "../transport/types";

export const PRUNE_AT = 2;
export const NUM_WORDS: Record<string, number> = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13,
};

export type QueryKind = "chat" | "caesar" | "python" | "weather" | "vaultlist" | "unknown";
export interface CaesarParams {
  text: string;
  shift: number;
  shiftWord: string | null;
  mode: "encrypt" | "decrypt";
}

export function caesar(text: string, shift: number, mode: string): string {
  let k = mode === "decrypt" ? -shift : shift;
  k = ((k % 26) + 26) % 26;
  return [...text]
    .map((c) => {
      const code = c.charCodeAt(0);
      if (code >= 65 && code <= 90) return String.fromCharCode(((code - 65 + k) % 26) + 65);
      if (code >= 97 && code <= 122) return String.fromCharCode(((code - 97 + k) % 26) + 97);
      return c;
    })
    .join("");
}

export function parseCaesar(text: string): CaesarParams {
  const quoted = text.match(/["“]([^"”]+)["”]/);
  const before = quoted ? text.slice(0, quoted.index) : text;
  const verbs = [...before.matchAll(/\b(en|de)(?:crypt|code)/gi)];
  const last = verbs[verbs.length - 1];
  const mode = last ? ((last[1] ?? "").toLowerCase() === "de" ? "decrypt" : "encrypt") : "encrypt";
  let shift = 7;
  let shiftWord: string | null = null;
  const num = text.match(/shift(?:\s+of)?\s*(?:=|:)?\s*(-?\d+)/i);
  const word = text.match(/shift(?:\s+of)?\s+([a-z]+)/i);
  if (num) shift = parseInt(num[1] ?? "7", 10);
  else if (word && !/^(of|to|by)$/i.test(word[1] ?? "")) shiftWord = (word[1] ?? "").toLowerCase();
  const input = quoted ? (quoted[1] ?? "") : mode === "decrypt" ? "AHSVZ HNLUA" : "TALOS AGENT";
  return { text: input, shift, shiftWord, mode };
}

export function classify(q: string): QueryKind {
  if (/\b(what can you do|who are you|help me understand|how do you work)\b/i.test(q)) return "chat";
  if (/(caesar|cipher|\bencrypt|\bdecrypt)/i.test(q)) return "caesar";
  if (/(python|print\s*\(|run this code|run the code)/i.test(q)) return "python";
  if (/(openweather|weather|temperature)/i.test(q)) return "weather";
  if (/(how many tools|list (all )?(your|the) tools|in (your|the) (skill )?vault)/i.test(q)) return "vaultlist";
  return "unknown";
}

export function runPython(code: string): string | null {
  const m = code.trim().match(/^print\((.*)\)$/s);
  if (!m) return null;
  const inner = (m[1] ?? "").trim();
  const sr = inner.match(/^sum\(range\((-?\d+)\s*,\s*(-?\d+)\)\)$/);
  if (sr) {
    let s = 0;
    for (let i = Number(sr[1]); i < Number(sr[2]); i++) s += i;
    return String(s);
  }
  const lit = inner.match(/^(["'])(.*)\1$/);
  if (lit) return lit[2] ?? "";
  if (/^[\d\s+\-*/().%]+$/.test(inner)) {
    try {
      const v: unknown = Function(`"use strict"; return (${inner});`)();
      if (typeof v === "number" && Number.isFinite(v)) return String(v);
    } catch {
      return null;
    }
  }
  return null;
}

export function sessionName(kind: QueryKind, q: string): string {
  if (kind === "caesar") return "Caesar cipher";
  if (kind === "python") return "Running Python";
  if (kind === "weather") {
    const m = q.match(/\bin ([A-Z][A-Za-z .'-]+?)(?:[.?!]|$)/);
    return `Weather in ${m ? (m[1] ?? "").trim() : "Mumbai"}`;
  }
  if (kind === "chat") return "Getting to know Talos";
  if (kind === "vaultlist") return "What's in the vault";
  const w = q.split(/\s+/).slice(0, 4).join(" ");
  return w.charAt(0).toUpperCase() + w.slice(1);
}

/** The strip the reference shows before planning finishes (lines 1464, 1655–1677, 1843–1860). Ruling 3. */
export function provisionalVariant(query: string, vaultNames: string[]): Variant {
  const kind = classify(query);
  if (kind === "caesar") return vaultNames.includes("caesar_cipher") ? "vault" : "forge";
  if (kind === "weather") return vaultNames.includes("get_current_temperature") ? "vault" : "forge";
  if (kind === "python" || kind === "vaultlist") return "primitive";
  return "chat";
}
```

`routing.ts` imports `Variant` from `transport/types.ts`, which Task 5 creates. For this task, create the file with just the step types (Task 5 appends the rest):

```ts
// frontend/src/transport/types.ts (Task 5 extends this file)
export type StepKey = "planner" | "forger" | "tester" | "human" | "learn" | "executor" | "answer" | "vault" | "primitive" | "skip";
export type Variant = "forge" | "vault" | "primitive" | "chat";
```

- [ ] **Step 7: Run the tests**

Run: `npx vitest run src/lib && npm run lint && npm run typecheck`
Expected: PASS (4 files); no lint or type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib frontend/src/transport/types.ts
git commit -m "[Feat]: Port the reference's format, highlight, motion and routing helpers"
```

---

### Task 4: Frontend copy and demo data

**Files:**
- Create: `frontend/src/lib/copy.ts`, `frontend/src/demo/data.ts`
- Test: `frontend/src/lib/copy.test.ts`, `frontend/src/demo/data.test.ts`

**Interfaces:**
- Consumes: `esc` (Task 3); `reference-data.json` (Task 1).
- Produces:
  - `COPY` (nested `as const` object below), `fill(template: string, vars: Record<string, string | number>): string`, `healthText(tool: string, pruned: boolean): string`, `removedSub(tool: string): string`, `retryLabel(arg: string, digit: number): string`.
  - `demo/data.ts`: `MODEL`, `CAESAR`, `WEATHER` (`ToolMeta = { name; args; ret; desc; kw: string[]; env?: string; web?: boolean }`), `SUGGESTIONS: { q: string; what: string; forge?: boolean }[]`, `USE_PRESETS: Record<string, string>`, `SOURCES: Record<string, string[]>` (tool name → lines), `VAULT_ROWS` (typed `reference-data.json` rows).

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/copy.test.ts`:

```ts
import { readRef } from "../../scripts/reference.mjs";
import { esc } from "./format";
import { COPY, fill, healthText, removedSub, retryLabel } from "./copy";

function leaves(o: unknown, path = "COPY"): [string, string][] {
  if (typeof o === "string") return [[path, o]];
  if (o && typeof o === "object") return Object.entries(o).flatMap(([k, v]) => leaves(v, `${path}.${k}`));
  return [];
}

test("every copy.ts string appears in the reference, fragment by fragment", () => {
  const ref = readRef();
  const missing: string[] = [];
  for (const [path, s] of leaves(COPY)) {
    for (const frag of s.split(/\{\w+\}/)) {
      if (!frag.trim()) continue;
      if (!ref.includes(frag) && !ref.includes(esc(frag))) missing.push(`${path}: ${JSON.stringify(frag)}`);
    }
  }
  expect(missing).toEqual([]);
});

test("fill and the failure copy", () => {
  expect(fill(COPY.convo.hintPast, { name: "Caesar cipher" })).toBe("Viewing an old session. Go back to Caesar cipher to ask something.");
  expect(healthText("caesar_cipher", false)).toContain('If <span class="mono">caesar_cipher</span> fails again');
  expect(healthText("caesar_cipher", true)).toBe('That was 2 failures with no success in between, so Talos took <span class="mono">caesar_cipher</span> out of the vault.');
  expect(healthText("get_current_temperature", true)).toBe("Removed after two failures in a row.");
  expect(healthText("slugify", false)).toContain('<span class="mono">slugify</span>');
  expect(removedSub("caesar_cipher")).toBe("It failed 2 times in a row, so the next Caesar request will forge a fresh one. The .py file stays on disk.");
  expect(removedSub("get_current_temperature")).toBe("It failed 2 times in a row. The next weather request forges a fresh one.");
  expect(retryLabel("shift", 7)).toBe("Ask again with shift 7");
});
```

`frontend/src/demo/data.test.ts`:

```ts
import { readRef } from "../../scripts/reference.mjs";
import { CAESAR, MODEL, SOURCES, SUGGESTIONS, USE_PRESETS, VAULT_ROWS, WEATHER } from "./data";

test("demo data is the reference's, verbatim", () => {
  const ref = readRef();
  for (const s of SUGGESTIONS) {
    expect(ref).toContain(s.q);
    expect(ref).toContain(s.what);
  }
  expect(SUGGESTIONS.map((s) => !!s.forge)).toEqual([true, false, false, true]);
  for (const m of [CAESAR, WEATHER]) {
    expect(ref).toContain(`name: "${m.name}", args: "${m.args}"`);
    expect(ref).toContain(`desc: "${m.desc}"`);
    expect(ref).toContain(`kw: ${JSON.stringify(m.kw).replace(/","/g, '", "')}`);
  }
  for (const v of Object.values(USE_PRESETS)) expect(ref).toContain(v);
  expect(ref).toContain(MODEL);
  expect(SOURCES.caesar_cipher).toHaveLength(63);
  expect(SOURCES.get_current_temperature).toHaveLength(36);
  expect(VAULT_ROWS).toHaveLength(40);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/lib/copy.test.ts src/demo/data.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write `frontend/src/lib/copy.ts`**

```ts
import { PRUNE_AT } from "./routing";

/** Every user-facing string the frontend owns, verbatim from the reference. `{name}` marks a value. */
export const COPY = {
  brand: { aria: "Talos, open the workbench", word: "TALOS" },
  nav: { aria: "Main", workbench: "Workbench", vault: "Vault", sessions: "Sessions", settings: "Settings" },
  demo: {
    toggle: "Demo controls",
    blurb: "Scripted runs over the real Talos vault. Nothing calls a model or leaves your browser.",
    speed: "Run speed",
    slow: "Slow",
    normal: "Normal",
    fast: "Fast",
    reset: "Reset the demo",
  },
  github: { label: "GitHub", href: "https://github.com/Yathharth54/Talos-AI" },
  convo: {
    aria: "Conversation",
    sessionName: "Session {n}",
    newSession: "New session",
    backToNow: "Back to now",
    askLabel: "Ask Talos",
    placeholder: "Ask for something it can't do yet",
    hintIdle: "Enter to send, Shift+Enter for a new line",
    hintBusy: "Stop the run to ask something else",
    hintPast: "Viewing an old session. Go back to {name} to ask something.",
    send: "Send",
    working: "Working",
    you: "You",
    talos: "Talos",
    thinking: "Working on it",
    viewRun: "View this run",
    empty: "Messages from this session show up here. Talos keeps the conversation until you close it; the vault stays on disk.",
    readOnly: "{name}, {time}. Read only.",
    livePrefix: "Talos: ",
    stopped: "Stopped. Ask again whenever you're ready.",
  },
  idle: {
    heading: "Ask for something it can't do yet",
    lede: " tools are already in the vault. Anything missing, Talos writes, tests, and keeps, so the next similar request skips straight to the answer.",
    tryHeading: "Try one of these",
    setup: "{keys} keys set in .env. Ask before running code is {state}. ",
    keysWithWeather: "3 of 5",
    keysWithout: "2 of 4",
    on: "on",
    off: "off",
    settings: "Settings",
  },
  bench: {
    aria: "Bench",
    stop: "Stop run",
    graph: "Graph progress",
    reading: "Reading your request",
    planning: "Planning",
    noTools: "No tools needed",
    details: "Details",
    tabs: { code: "Code", tests: "Tests", attempts: "Attempts", call: "Call", history: "History", log: "Run log" },
  },
  banner: {
    savedAria: "Saved to the vault",
    saved: " is in the vault",
    openInVault: "Open in vault",
    removedAria: "Removed from the vault",
    removed: " was removed from the vault",
  },
  code: { aria: "Source code", cap: "{n} lines, attempt {a}", lines: "{n} lines" },
  tests: {
    none: "Tests appear here once the Forger has written them.",
    passedOf: "{p} of {k} passed",
    running: "Attempt {n}, running",
    unit: "Unit tests",
    smoke: "Smoke test",
    smokeCap: "Real input, run once",
    smokeRunning: "running",
    passed: "passed",
    failed: "failed",
    prevFailed: "Attempt {n} failed one test",
    note: "Tests run in a fresh subprocess inside a temporary folder, with a {s}-second limit. They can't touch the network or your files.",
  },
  attempts: {
    none: "No attempts yet.",
    n: "Attempt {n}",
    underTest: "Under test",
    passed: "Passed every test",
    failed: "Failed",
    note: "The Forger gets up to 3 attempts. Each failure goes back to it with the failing test and its traceback.",
  },
  call: {
    none: "None",
    args: "Arguments",
    argsCap: "Filled in by the Executor",
    resolving: "resolving",
    errorCap: "The tool raised an error",
    result: "Result",
    waiting: "Waiting for the Executor",
    output: "Output",
    awaitingApproval: "Waiting for your approval",
    running: "running",
    record: "Tool record",
    forged: "Forged",
    uses: "Uses",
    failures: "Failures",
    recordUses: "{n}, including this one",
    recordFails: "{n} in total",
    recordNone: "None yet",
    health: "What this means for the vault",
    meter: "{s} of {p} failures in a row",
    streakOne: "{s} failure in a row",
    streakMany: "{s} failures in a row",
    openInVault: "Open in vault",
    retry: "Ask again with {arg} {digit}",
  },
  health: {
    caesar_cipher: {
      pruned: 'That was {p} failures with no success in between, so Talos took <span class="mono">caesar_cipher</span> out of the vault.',
      streak:
        'If <span class="mono">caesar_cipher</span> fails again before it next succeeds, Talos takes it out of the vault and forges a fresh one next time. One success resets the count. The .py file stays on disk either way.',
    },
    get_current_temperature: {
      pruned: "Removed after two failures in a row.",
      streak: "Set the key and ask again. One success resets the count.",
    },
    generic: {
      pruned: 'That was {p} failures with no success in between, so Talos took <span class="mono">{tool}</span> out of the vault.',
      streak:
        'If <span class="mono">{tool}</span> fails again before it next succeeds, Talos takes it out of the vault and forges a fresh one next time. One success resets the count. The .py file stays on disk either way.',
    },
  },
  removedSub: {
    caesar_cipher: "It failed {p} times in a row, so the next Caesar request will forge a fresh one. The .py file stays on disk.",
    get_current_temperature: "It failed {p} times in a row. The next weather request forges a fresh one.",
    generic: "It failed {p} times in a row, so the next {tool} request will forge a fresh one. The .py file stays on disk.",
  },
  history: {
    gone: "This tool is no longer in the vault.",
    forged: "Forged",
    lastUsed: "Last used",
    uses: "Uses",
    failures: "Failures",
    failuresValue: "{f} in total, {s} in a row",
    lastFailure: "Last failure",
  },
  log: {
    thisRun: "This run",
    runN: "Run {n}",
    note: "Each line is a node in the graph. With LangSmith set up, the whole run is traced there too.",
    inSession: "In this session",
    earlier: "Earlier in this session",
    prompt: "talos › ",
  },
  approval: {
    eyebrow: "{tool} needs your approval",
    titleCode: "Run this code on your machine?",
    titleShell: "Run this command on your machine?",
    body: "Talos wrote it to answer your question. It runs as you, with your file access, and stops after 10 seconds.",
    no: "Don't run",
    yesCode: "Run code",
    yesShell: "Run command",
    footA: "To stop asking, turn off ",
    footLink: "Ask before running code",
    footB: " in Settings, or set ",
    footVar: "TALOS_AUTO_APPROVE_EXEC=true",
    footC: " in .env.",
  },
  key: {
    eyebrow: "Human check",
    title: "This tool needs an {service} key",
    body: " reads its key from an environment variable. Talos saves what you paste to .env, so it only asks once.",
    placeholder: "Paste the key",
    skip: "Skip",
    save: "Save key",
    foot: "If you skip, the tool is still saved to the vault, but it fails when it runs until the key is set.",
    footDemo: " This demo keeps the key in memory only.",
    error: "Paste the key first, or choose Skip.",
  },
  reader: {
    title: "talos/vault/tools/{name}.py",
    sub: "{n} lines. Forged, tested and saved by Talos.",
    copy: "Copy",
    close: "Close",
    copied: "Copied",
    selected: "Selected, press Ctrl+C",
    aria: "Full source",
  },
  vault: {
    title: "Vault",
    lede: "{n} tools, every one written and tested by Talos. Stored as .py files and a manifest.json.",
    searchLabel: "Search the vault",
    searchPlaceholder: "Search by name or keyword",
    filterAria: "Filter",
    all: "All",
    web: "Uses the web",
    failed: "Has failed",
    colTool: "Tool",
    colUses: "Uses",
    colFailures: "Failures",
    colLast: "Last used",
    legend: "Gold names reach the web through a free API Talos found itself",
    showing: "Showing {r} of {n}",
    newTag: "New this session",
    notYet: "Not yet",
    empty: "No tools match. Try another word, or clear the filter.",
    detailAria: "Tool details",
    pick: "Pick a tool to see its record.",
    keywords: "Keywords",
    forged: "Forged",
    lastUsed: "Last used",
    uses: "Uses",
    failures: "Failures",
    none: "None",
    failuresValue: "{f} in total, {s} in a row",
    lastFailure: "Last failure",
    file: "File",
    filePath: "talos/vault/tools/{name}.py",
    reachesWeb: "Reaches the web",
    webYes: "Yes, through a free API it found itself",
    webNo: "No",
    healthAria: "Vault health",
    healthOne: "One more failure in a row removes it",
    healthOk: "Healthy. No failures in a row",
    healthNote: "A success resets the count. Removing a tool only drops it from manifest.json; the .py file stays for you to read.",
    previewName: "{name}.py",
    previewSub: "{n} lines, written by the Forger",
    read: "Read full file",
    previewAria: "Source code preview",
    noSource: "Source lives at talos/vault/tools/{name}.py. This demo only bundles the source of tools it forges.",
    use: "Use in a question",
    remove: "Remove from vault",
    confirm: "Remove {name}?",
    usePrefill: "Use {name} on ",
  },
  sessions: {
    title: "Sessions",
    lede: "Every conversation, and what it forged or reused. Sessions end; the vault they build is shared by all of them.",
    today: "Today",
    run: "run",
    runs: "runs",
    forgedCount: ", {n} forged",
    now: "Now",
    empty: "Nothing asked yet.",
    more: "and {n} more",
    cont: "Continue",
    open: "Open",
  },
  settings: {
    title: "Settings",
    safety: "Safety",
    ask: "Ask before running code",
    askA: "Talos shows you every ",
    askPython: "python_exec",
    askB: " and ",
    askShell: "shell_exec",
    askC: " call and waits for you. Turning this off is the same as ",
    askVar: "TALOS_AUTO_APPROVE_EXEC=true",
    keys: "Keys",
    set: "Set",
    notSet: "Not set",
    forging: "Forging",
    model: "Model",
    retries: "Forge retries",
    testLimit: "Test time limit",
    testLimitValue: "10 seconds",
    modelLimit: "Model call time limit",
    modelLimitValue: "120 seconds",
    pruneAfter: "Removed from the vault after",
    pruneValue: "{n} failures in a row",
    note: "These come from .env. Change them there and restart Talos.",
    keyDesc: {
      OPENROUTER_API_KEY: "Required. Every model call goes through OpenRouter.",
      TAVILY_API_KEY: "Needed for web search.",
      JINA_API_KEY: "Optional. Raises web-reading limits.",
      LANGSMITH_API_KEY: "Optional. Traces every node in LangSmith.",
      savedByHuman: "Saved by Human check this session.",
      askedWhenNeeded: "Asked for when a tool needs it.",
    },
  },
} as const;

export function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

type Keyed = { pruned: string; streak: string };
const keyed = (table: Record<string, Keyed>, tool: string): Keyed => table[tool] ?? (table.generic as Keyed);

/** The health panel's paragraph after a vault/forged tool failed (lines 1728–1730, 1884). Ruling 9. */
export function healthText(tool: string, pruned: boolean): string {
  const t = keyed(COPY.health as unknown as Record<string, Keyed>, tool);
  return fill(pruned ? t.pruned : t.streak, { p: PRUNE_AT, tool });
}
/** The removed banner's second line (lines 1722, 1883). */
export function removedSub(tool: string): string {
  const table = COPY.removedSub as unknown as Record<string, string>;
  return fill(table[tool] ?? COPY.removedSub.generic, { p: PRUNE_AT, tool });
}
export const retryLabel = (arg: string, digit: number): string => fill(COPY.call.retry, { arg, digit });
```

- [ ] **Step 4: Write `frontend/src/demo/data.ts`**

```ts
import ref from "./reference-data.json";

export interface ToolMeta {
  name: string;
  args: string;
  ret: string;
  desc: string;
  kw: string[];
  env?: string;
  web?: boolean;
}
export type VaultRow = [string, string, string, string, string[], number, number, number, string, string, string];

export const MODEL = "deepseek/deepseek-v4.1-flash";
export const VAULT_ROWS = ref.vaultData as VaultRow[];

export const CAESAR: ToolMeta = {
  name: "caesar_cipher",
  args: "text: str, shift: int, mode: str",
  ret: "str",
  desc: "Encrypts or decrypts a text string using a Caesar cipher with a given shift, preserving case and non-alphabetic characters.",
  kw: ["caesar", "cipher", "encrypt", "decrypt", "shift", "text", "cryptography"],
};
export const WEATHER: ToolMeta = {
  name: "get_current_temperature",
  args: "city: str",
  ret: "float",
  desc: "Returns the current temperature in Celsius for a city from OpenWeatherMap.",
  kw: ["weather", "temperature", "openweathermap", "city", "celsius", "mumbai"],
  env: "OPENWEATHERMAP_API_KEY",
  web: true,
};

/** Bundled sources, by tool name. The reference's getSource() splits on "\n" (line 1309). */
export const SOURCES: Record<string, string[]> = {
  caesar_cipher: ref.sources["src-caesar"].split("\n"),
  get_current_temperature: ref.sources["src-weather"].split("\n"),
};

export const SUGGESTIONS: { q: string; what: string; forge?: boolean }[] = [
  { q: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.', what: "Forges a new tool", forge: true },
  { q: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"', what: "Reuses it once it's in the vault" },
  { q: "Run this Python code and give me the output: print(sum(range(1, 101)))", what: "Built in, asks before it runs code" },
  { q: "Use the OpenWeatherMap API to get the current temperature in Mumbai.", what: "Forges a tool that needs an API key", forge: true },
];

/** "Use in a question" prefills (line 2119); other tools get COPY.vault.usePrefill. */
export const USE_PRESETS: Record<string, string> = {
  caesar_cipher: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  get_current_temperature: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};
```

- [ ] **Step 5: Run the tests**

Run: `npx vitest run src/lib/copy.test.ts src/demo/data.test.ts && npm run lint && npm run typecheck`
Expected: PASS. If the copy test lists a fragment, the string in `copy.ts` isn't verbatim: fix `copy.ts`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/copy.ts frontend/src/lib/copy.test.ts frontend/src/demo/data.ts frontend/src/demo/data.test.ts
git commit -m "[Feat]: Add the frontend copy table and demo data, checked against the reference"
```

---

### Task 5: Contract types, stores, data source and seeded sessions

**Files:**
- Modify: `frontend/src/transport/types.ts` (replace the Task 3 stub with the full file)
- Create: `frontend/src/store/types.ts`, `frontend/src/store/createStore.ts`, `frontend/src/store/runOps.ts`, `frontend/src/store/sessionOps.ts`, `frontend/src/store/vaultOps.ts`, `frontend/src/store/stores.tsx`
- Create: `frontend/src/data/source.ts`, `frontend/src/demo/seeds.ts`, `frontend/src/demo/source.ts`, `frontend/src/test/parity/runs.ts`
- Test: `frontend/src/store/runOps.test.ts`, `frontend/src/store/vaultOps.test.ts`, `frontend/src/store/sessionOps.test.ts`, `frontend/src/demo/seeds.test.ts`, `frontend/src/store/stores.test.tsx`

**Interfaces:**
- Consumes: `COPY` (Task 4), `VAULT_ROWS`, `SOURCES`, `MODEL` (Task 4), `nowIso`, `fmtTime` (Task 3), `fixtureCase` (Task 2).
- Produces (part B builds on these names):
  - `transport/types.ts`: every contract type below, `RunEvent`, `EventType`, `ResumeDecision`, `EventSink`, `StartedRun`, `Transport`, and the stage 2 API shapes `ApiSession`, `ApiMessage`, `ApiRunSummary`, `ApiVaultEntry` (= `VaultEntry`), `ApiSettings`.
  - `store/types.ts`: `Run`, `NodeState`, `StripNode`, `TabId`, `Tab`, `LogLine`, `CmdLine`, `LogLn`, `CodeState`, `TestItem`, `TestsState`, `Attempt`, `Smoke`, `CallArg`, `CallState`, `Health`, `Banner`, `RunStatus`, `Chip`, `Message`, `YouMessage`, `TalosMessage`, `SessionRec`, `VaultTool`, `View`, `DialogReq`, `RunsState`, `SessionState`, `VaultState`, `SettingsState`, `UiState`.
  - `store/createStore.ts`: `Store<S>`, `Action<S>`, `createStore<S>(initial: S): Store<S>`, `useStoreState<S, T>(store, select): T`.
  - `store/runOps.ts`: `STRIPS`, `DONE_STATES`, `nextKey()`, `newRun`, `initStrip`, `setNode`, `flow`, `log`, `logPop`, `startCmd`, `typeCmd`, `endCmd`, `setTab`, `setCaption`, `setLabel`, `setSig`, `setTitle`, `setBanner`, `logStatus`, `logTone`, `patch`, `patchCall`, `patchCode`, `railPercent` (signatures in the code below).
  - `store/sessionOps.ts`: `curSession`, `shownSession`, `addYou`, `addTalos`, `updateTalos`, `rename`, `attachRun`, `openNewSession`.
  - `store/vaultOps.ts`: `freshVault`, `fromVaultEntry`, `vaultRows`, `addTool`, `recordUse`, `recordFailure`, `removeTool`, `findTool`.
  - `store/stores.tsx`: `Stores`, `createStores(init: InitialData): Stores`, `InitialData`, `StoresContext`, `useStores()`, `useRuns`, `useSession`, `useVault`, `useSettings`, `useUi`, `updateRun(stores, id, fn)`.
  - `data/source.ts`: `DataSource` (below). `demo/source.ts`: `createDemoDataSource(): DataSource`. `demo/seeds.ts`: `seedSessions(tools: VaultTool[]): { sessions: SessionRec[]; runs: Run[]; lastRunNumber: number }`.
  - `test/parity/runs.ts`: `asRun(json: unknown): Run` (fills `id`, `sessionId` for fixture run objects).

**Selectors rule:** `useStoreState` uses `useSyncExternalStore`, so a selector must return a value already in the state (a slice or a primitive), never a new object or array. Derive lists with `useMemo` in the component.

- [ ] **Step 1: Write the full `frontend/src/transport/types.ts`**

```ts
/* The run event contract (overview spec §4) and the stage 2 API shapes. Normative for live and demo. */

export type StepKey = "planner" | "forger" | "tester" | "human" | "learn" | "executor" | "answer" | "vault" | "primitive" | "skip";
export type Variant = "forge" | "vault" | "primitive" | "chat";

export interface Sig {
  name: string;
  args: string;
  ret: string;
}

export interface VaultEntry {
  name: string;
  args: string;
  ret: string;
  signature: string;
  description: string;
  keywords: string[];
  uses: number;
  failures: number;
  streak: number;
  created_at: string;
  last_used: string | null;
  last_failure: string | null;
  last_failed_at: string | null;
  web: boolean;
  file: string;
}

export interface EventData {
  "run.started": { session_id: string; query: string; n: number };
  "log.cmd": { text: string };
  "plan.ready": {
    subtasks: { id: number; action: string; needs: "primitive" | "vault" | "forge"; tool_hint: string | null; depends_on: number[] }[];
    verdict: string;
  };
  "strip.set": {
    variant: Variant;
    subtask: { index: number; total: number; label: string };
    sig: Sig | null;
    /** Demo transport only (ruling 2): the bench heading when there's no signature. */
    title?: string;
  };
  "subtask.started": { index: number; total: number };
  "node.started": { step: StepKey; label?: string };
  "node.finished": { step: StepKey; status: "done" | "forge" | "skip" | "fail" | "answer" | "stopped"; label?: string };
  "link.flow": { from: StepKey; to: StepKey };
  caption: { html: string };
  "log.line": { label: string; text: string; tone: "plain" | "g" | "w" | "sub"; caret?: boolean };
  "log.pop": Record<string, never>;
  "log.status": { text: string; gold: boolean; tone: "" | "warm" | "alert" };
  "talos.status": { text: string };
  "forge.code": {
    tool: string;
    attempt: number;
    file: string;
    lines: string[];
    changed: number | null;
    note: string | null;
    /** Proposed addition (ruling 1): how many tests the Forger wrote. */
    tests?: number;
  };
  "forge.tests": { tool: string; attempt: number; results: { name: string; passed: boolean; why: string | null }[] };
  "forge.attempt": { attempt: number; ok: boolean; detail: string };
  "forge.smoke": { call: string; result: string | null; passed: boolean };
  "vault.saved": { tool: VaultEntry; sub: string };
  "vault.failure": { tool: string; streak: number; pruned: boolean; error: string };
  "call.args": { tool: string; args: [string, string, boolean][]; caption: string | null };
  "call.result": { repr: string; type: string; small: boolean };
  "call.error": { error: string; when: string };
  interrupt:
    | { kind: "confirm_exec"; payload: { tool: "python_exec" | "shell_exec"; preview: string } }
    | { kind: "missing_api_key"; payload: { env_var: string; tool_name: string; service: string } };
  "interrupt.resolved": { kind: "confirm_exec" | "missing_api_key"; decision: "approve" | "decline" | "save" | "skip" };
  "answer.delta": { text: string };
  "answer.done": {
    html: string;
    note: string | null;
    chips: { kind: "forged" | "reused" | "failed"; text: string }[];
    /** Demo transport only (ruling 2): show the suggestion buttons under the answer. */
    suggest?: boolean;
  };
  "run.finished": {
    status: "done" | "failed" | "stopped" | "declined";
    summary: string;
    summary_gold: boolean;
    forged: string[];
    used: string[];
  };
  error: { message: string };
}

export type EventType = keyof EventData;
export type RunEvent = { [T in EventType]: { run_id: string; seq: number; ts: string; type: T; data: EventData[T] } }[EventType];
export type EventOf<T extends EventType> = Extract<RunEvent, { type: T }>;

export type ResumeDecision = { decision: "approve" } | { decision: "decline" } | { decision: "save"; value: string } | { decision: "skip" };

/** Applies one event. Resolves when the event is on screen and its animation is done (the demo waits on it). */
export type EventSink = (event: RunEvent) => Promise<void>;

export interface StartedRun {
  runId: string;
  n: number;
  /** Set when the server (or the demo) renamed the session on its first run. */
  sessionName: string | null;
}

/** How runs reach the UI. Demo: DemoTransport (part A). Live: LiveTransport (part B). */
export interface Transport {
  startRun(sessionId: string, text: string): Promise<StartedRun>;
  /** Streams the run's events with seq > after into `sink`, in order. Returns an unsubscribe function. */
  subscribe(runId: string, sink: EventSink, after?: number): () => void;
  resume(runId: string, decision: ResumeDecision): Promise<void>;
  stop(runId: string): Promise<void>;
}

/* Stage 2 API shapes (spec 02 §4), for part B's live data source. */
export interface ApiSession {
  id: string;
  name: string;
  number: number;
  created_at: string;
  updated_at: string;
}
export interface ApiMessage {
  id: string;
  role: "user" | "assistant";
  html: string;
  note: string | null;
  chips: { kind: "forged" | "reused" | "failed"; text: string }[];
  run_id: string | null;
  created_at: string;
}
export interface ApiRunSummary {
  id: string;
  n: number;
  query: string;
  status: "running" | "waiting" | "done" | "failed" | "stopped" | "declined";
  summary: string | null;
  summary_gold: boolean;
  forged: string[];
  used: string[];
  failed: string[];
  started_at: string;
  finished_at: string | null;
}
export type ApiVaultEntry = VaultEntry;
export interface ApiSettings {
  model: string;
  ask_before_exec: boolean;
  forge_retries: number;
  test_timeout_s: number;
  llm_timeout_s: number;
  prune_after: number;
  keys: { name: string; set: boolean; required: boolean; description: string }[];
}
```

- [ ] **Step 2: Write `frontend/src/store/types.ts`**

```ts
import type { Sig, StepKey, Variant } from "../transport/types";

/* The reference's run object (lines 1446–1449 and every renderer), plus `id` and `sessionId`. */
export type NodeState = "pending" | "active" | "done" | "forge" | "skip" | "fail" | "answer" | "stopped";
export interface StripNode {
  label: string;
  llm: boolean;
  state: NodeState;
}
export type TabId = "code" | "tests" | "attempts" | "call" | "history" | "answer" | "log";
export interface Tab {
  id: TabId;
  label: string;
  count?: number;
}
export interface CmdLine {
  kind: "cmd";
  text: string;
  shown?: number | null;
  typing?: boolean;
  key?: number;
}
export interface LogLn {
  kind: "ln" | "sub";
  label: string;
  text: string;
  tone?: string;
  caret?: boolean;
  fresh?: boolean;
  key?: number;
}
export type LogLine = CmdLine | LogLn;
export interface CodeState {
  file: string;
  cap: string;
  lines: string[];
  shown: number;
  changed?: number | null;
  flash?: boolean;
  note?: string;
}
export interface TestItem {
  name: string;
  state: "waiting" | "running" | "passed" | "failed";
  why: string;
  drawn?: boolean;
  flashed?: boolean;
}
export interface TestsState {
  attempt: number;
  list: TestItem[];
}
export interface Attempt {
  n: number;
  ok: boolean | null;
  detail: string;
}
export interface Smoke {
  call: string;
  result: string | null;
}
export type CallArg = [string, string] | [string, string, boolean];
export interface Health {
  streak: number;
  tool: string;
  text: string;
  retry: { q: string; label: string } | null;
}
export interface CallState {
  args: CallArg[];
  shownArgs?: number | null;
  noArgs?: boolean;
  argsCap?: string;
  resultCap?: string;
  result?: string | null;
  resultType?: string;
  smallResult?: boolean;
  pending?: string;
  error?: string;
  when?: string;
  record?: { forged: string; uses: string; fails: string };
  health?: Health;
}
export interface Banner {
  kind: "saved" | "removed";
  name: string;
  sub: string;
}
export type RunStatus = "running" | "waiting" | "done" | "failed" | "stopped" | "declined";
export interface Run {
  id: string;
  sessionId: string;
  n: number;
  query: string;
  status: RunStatus;
  tab: TabId;
  tabs: Tab[];
  strip: Variant;
  nodes: Partial<Record<StepKey, StripNode>>;
  links: Record<string, boolean>;
  title?: string;
  label?: string;
  sig?: Sig | null;
  caption?: string;
  code?: CodeState;
  codeScroll?: "bottom" | number | null;
  tests?: TestsState;
  attempts?: Attempt[];
  smoke?: Smoke | null;
  call?: CallState;
  banner?: Banner | null;
  log: LogLine[];
  logStatus?: string;
  logStatusGold?: boolean;
  logTone?: "" | "warm" | "alert";
  summary?: string;
  summaryGold?: boolean;
  toolName?: string;
  toolUsed?: string;
  forged?: boolean;
  failed?: boolean;
  seeded?: boolean;
  answer?: string;
  /** The Forger–Tester link's backwards packet (retrying(), line 1040). */
  retrying?: boolean;
  /** How many times each link has flowed; a change restarts its packet animation. */
  flows?: Record<string, number>;
}

export interface Chip {
  kind: "forged" | "reused" | "failed";
  text: string;
}
export interface YouMessage {
  kind: "you";
  key: string;
  text: string;
  past: boolean;
}
export interface TalosMessage {
  kind: "talos";
  key: string;
  runN: number;
  /** The orbit spinner's text while working; null once the answer (or stop note) is in. */
  status: string | null;
  html: string | null;
  /** Live answers are word-wrapped for the fade-in; seeded transcripts are not (sessionHtml, line 2229). */
  wrap: boolean;
  wordsOn: number;
  note: string | null;
  chips: Chip[];
  suggest: boolean;
  stopNote: string | null;
  runLink: boolean;
  past: boolean;
}
export type Message = YouMessage | TalosMessage;

export interface SessionRec {
  id: string;
  name: string;
  started: string;
  live: boolean;
  runIds: string[];
  messages: Message[];
}

export interface VaultTool {
  name: string;
  args: string;
  ret: string;
  desc: string;
  kw: string[];
  uses: number;
  fails: number;
  streak: number;
  created: string;
  last: string;
  lastFail: string;
  lastFailAt: string;
  web: boolean;
  fresh: boolean;
}

export type View = "workbench" | "vault" | "sessions" | "settings";
export type DialogReq =
  | { kind: "approval"; runId: string; tool: "python_exec" | "shell_exec"; code: string }
  | { kind: "key"; runId: string; toolName: string; envVar: string; service: string }
  | { kind: "reader"; name: string; lines: string[] };

export interface RunsState {
  byId: Record<string, Run>;
}
export interface SessionState {
  sessions: SessionRec[];
  curId: string;
  viewId: string | null;
  count: number;
}
export interface VaultState {
  tools: VaultTool[];
  /** Tool name → source lines (null: not available). Filled lazily from the data source. */
  sources: Record<string, string[] | null>;
}
export interface SettingsState {
  askExec: boolean;
  /** Demo: keys pasted into the key dialog, kept in memory. Live: names of keys that are set. */
  env: Record<string, string>;
  model: string;
}
export interface UiState {
  view: View;
  /** Bumped when the view changes, to restart `.view.enter`. */
  viewEnter: number;
  dialog: DialogReq | null;
  busy: boolean;
  currentRunId: string | null;
  viewingRunId: string | null;
  selected: string | null;
  filter: "all" | "web" | "failed";
  query: string;
  /** The vault table's rows rise in (renderVault({ stagger: true }), line 1973). */
  stagger: boolean;
  /** Bumped on every renderVault(): rows are keyed by it, so they're re-created as in the reference. */
  vaultRender: number;
  popOpen: boolean;
  speed: number;
  badge: boolean;
  booted: boolean;
  /** The polite live region (#live). */
  live: string;
  /** Tool name whose Remove button is in its confirm step. */
  confirmRemove: string | null;
  /** The composer's text. */
  draft: string;
  /** Bumped whenever the reference would call renderBench(): remounts the bench (clears `flow`, resets the tab indicator). */
  benchKey: number;
  /** The next session-title change decodes into place (setTitle(name, true)). */
  titleAnimate: boolean;
}
```

- [ ] **Step 3: Write `frontend/src/store/createStore.ts`**

```ts
import { useSyncExternalStore } from "react";

export type Action<S> = { type: "set"; patch: Partial<S> } | { type: "update"; fn: (s: S) => S } | { type: "reset"; state: S };

export function reduce<S>(state: S, action: Action<S>): S {
  switch (action.type) {
    case "set":
      return { ...state, ...action.patch };
    case "update":
      return action.fn(state);
    case "reset":
      return action.state;
  }
}

export interface Store<S> {
  get(): S;
  dispatch(action: Action<S>): void;
  set(patch: Partial<S>): void;
  update(fn: (s: S) => S): void;
  subscribe(listener: () => void): () => void;
}

/** One reducer per concern, readable synchronously by the player and the demo transport (ruling 6). */
export function createStore<S>(initial: S): Store<S> {
  let state = initial;
  const listeners = new Set<() => void>();
  const dispatch = (action: Action<S>) => {
    const next = reduce(state, action);
    if (next === state) return;
    state = next;
    for (const l of [...listeners]) l();
  };
  return {
    get: () => state,
    dispatch,
    set: (patch) => dispatch({ type: "set", patch }),
    update: (fn) => dispatch({ type: "update", fn }),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** The selector must return a value already in the state (see the Selectors rule). */
export function useStoreState<S, T>(store: Store<S>, select: (s: S) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(store.get()), () => select(store.get()));
}
```

- [ ] **Step 4: Write `frontend/src/store/runOps.ts`**

```ts
import { COPY } from "../lib/copy";
import type { Sig, StepKey, Variant } from "../transport/types";
import type { Banner, CallState, CodeState, NodeState, Run, TabId } from "./types";

/** Line 992. [key, label, calls a model]. */
export const STRIPS: Record<Variant, [StepKey, string, boolean?][]> = {
  forge: [["planner", "Planner", true], ["forger", "Forger", true], ["tester", "Tester"], ["human", "Human check"], ["learn", "Learn"], ["executor", "Executor", true], ["answer", "Answer"]],
  vault: [["planner", "Planner", true], ["vault", "Vault tool"], ["skip", "Forge sub-graph skipped"], ["executor", "Executor", true], ["answer", "Answer"]],
  primitive: [["planner", "Planner", true], ["primitive", "Primitive"], ["executor", "Executor", true], ["answer", "Answer"]],
  chat: [["planner", "Planner", true], ["answer", "Answer"]],
};
export const DONE_STATES: NodeState[] = ["done", "forge", "skip", "answer", "fail", "stopped"];

let key = 0;
/** Unique React keys for log lines and messages. */
export const nextKey = (): number => ++key;

/** newRun() (line 1446) plus the label submit() sets (line 1465). */
export function newRun(o: { id: string; n: number; query: string; sessionId: string }): Run {
  return { ...o, tab: "log", title: COPY.bench.reading, label: COPY.bench.planning, status: "running", log: [], nodes: {}, links: {}, tabs: [], strip: "forge" };
}

/** initStrip() (line 1000). With `keep`, steps present in both strips keep their state (ruling 3). */
export function initStrip(run: Run, variant: Variant, keep = false): Run {
  const nodes: Run["nodes"] = {};
  for (const [k, label, llm] of STRIPS[variant]) {
    const prev = keep ? run.nodes[k] : undefined;
    nodes[k] = prev ? { ...prev } : { label, llm: !!llm, state: "pending" };
  }
  if (variant === "vault" && nodes.skip && nodes.skip.state === "pending") nodes.skip = { ...nodes.skip, state: "skip" };
  return { ...run, strip: variant, nodes, links: keep ? { ...run.links } : {} };
}

/** setNode() (line 1020). */
export function setNode(run: Run, k: StepKey, state: NodeState, label?: string): Run {
  const n = run.nodes[k];
  if (!n) return run;
  return { ...run, nodes: { ...run.nodes, [k]: { ...n, state, label: label || n.label } } };
}

/** flow() (line 1031): lights the link and restarts its packet. */
export function flow(run: Run, from: StepKey, to: StepKey): Run {
  const lk = `${from}-${to}`;
  const flows = run.flows ?? {};
  return { ...run, links: { ...run.links, [lk]: true }, flows: { ...flows, [lk]: (flows[lk] ?? 0) + 1 } };
}

/** log() (line 1280): clears every caret, marks only the new line fresh. */
export function log(run: Run, label: string, text: string, tone = "", opts: { caret?: boolean; sub?: boolean } = {}): Run {
  const lines = run.log.map((l) => (l.kind === "cmd" ? l : { ...l, caret: false, fresh: false }));
  lines.push({ kind: opts.sub ? "sub" : "ln", label, text, tone, caret: !!opts.caret, fresh: true, key: nextKey() });
  return { ...run, log: lines };
}
export const logPop = (run: Run): Run => ({ ...run, log: run.log.slice(0, -1) });

/** typeCmd() (line 1296), in three steps so the player can pace it. */
export const startCmd = (run: Run, text: string): Run => ({ ...run, log: [...run.log, { kind: "cmd", text, shown: 0, typing: true, key: nextKey() }] });
export function typeCmd(run: Run, shown: number): Run {
  const log = run.log.slice();
  const i = log.length - 1;
  const last = log[i];
  if (last?.kind === "cmd") log[i] = { ...last, shown };
  return { ...run, log };
}
export function endCmd(run: Run): Run {
  const log = run.log.map((l) => (l.kind === "cmd" && l.typing ? { ...l, typing: false, shown: null } : l));
  return { ...run, log };
}

export const setTab = (run: Run, tab: TabId): Run => ({ ...run, tab });
export const setCaption = (run: Run, caption: string): Run => ({ ...run, caption });
export const setLabel = (run: Run, label: string): Run => ({ ...run, label });
export const setSig = (run: Run, sig: Sig | null): Run => ({ ...run, sig });
export const setTitle = (run: Run, title: string): Run => ({ ...run, title });
export const setBanner = (run: Run, banner: Banner | null): Run => ({ ...run, banner });
export const logStatus = (run: Run, text: string, gold = false): Run => ({ ...run, logStatus: text, logStatusGold: gold });
export const logTone = (run: Run, tone: "" | "warm" | "alert"): Run => ({ ...run, logTone: tone });
export const patch = (run: Run, p: Partial<Run>): Run => ({ ...run, ...p });
export const patchCall = (run: Run, p: Partial<CallState>): Run => ({ ...run, call: { args: [], ...run.call, ...p } });
export const patchCode = (run: Run, p: Partial<CodeState>): Run => (run.code ? { ...run, code: { ...run.code, ...p } } : run);

/** updateRail()'s width (line 1051). */
export function railPercent(run: Run): number {
  const all = Object.values(run.nodes).filter((n) => !!n);
  if (!all.length) return 0;
  const d = all.filter((n) => DONE_STATES.includes(n.state)).length + all.filter((n) => n.state === "active").length * 0.5;
  return Math.round((d / all.length) * 100);
}
```

- [ ] **Step 5: Write `frontend/src/store/vaultOps.ts`**

```ts
import type { VaultRow } from "../demo/data";
import type { VaultEntry } from "../transport/types";
import type { UiState, VaultTool } from "./types";

/** freshVault() (line 912). */
export function freshVault(rows: VaultRow[]): VaultTool[] {
  return rows.map(([name, args, ret, desc, kw, uses, fails, streak, created, last, lastFail]) => ({
    name, args, ret, desc, kw, uses, fails, streak, created, last, lastFail,
    lastFailAt: lastFail ? last : "",
    web: name.startsWith("fetch_"),
    fresh: false,
  }));
}

/** API/contract entry → the reference's tool shape. `fresh` = "New this session". */
export function fromVaultEntry(e: VaultEntry, fresh: boolean): VaultTool {
  return {
    name: e.name, args: e.args, ret: e.ret, desc: e.description, kw: e.keywords, uses: e.uses, fails: e.failures, streak: e.streak,
    created: e.created_at, last: e.last_used ?? "", lastFail: e.last_failure ?? "", lastFailAt: e.last_failed_at ?? "", web: e.web, fresh,
  };
}

export const findTool = (tools: VaultTool[], name: string | null | undefined): VaultTool | undefined =>
  name ? tools.find((t) => t.name === name) : undefined;

/** vaultRows() (line 1956). */
export function vaultRows(tools: VaultTool[], filter: UiState["filter"], query: string): VaultTool[] {
  const q = query.toLowerCase();
  return tools
    .filter((t) => filter === "all" || (filter === "web" ? t.web : t.fails > 0))
    .filter((t) => !q || t.name.toLowerCase().includes(q) || t.kw.some((k) => k.includes(q)) || t.desc.toLowerCase().includes(q))
    .sort((a, b) => (b.last || b.created).localeCompare(a.last || a.created));
}

export const addTool = (tools: VaultTool[], tool: VaultTool): VaultTool[] => [...tools.filter((t) => t.name !== tool.name), tool];
export const removeTool = (tools: VaultTool[], name: string): VaultTool[] => tools.filter((t) => t.name !== name);

/** A successful call (lines 1743, 1896). */
export const recordUse = (tools: VaultTool[], name: string, now: string): VaultTool[] =>
  tools.map((t) => (t.name === name ? { ...t, uses: t.uses + 1, streak: 0, last: now } : t));

/** A failed call (lines 1711, 1880). */
export const recordFailure = (tools: VaultTool[], name: string, streak: number, error: string, now: string): VaultTool[] =>
  tools.map((t) => (t.name === name ? { ...t, fails: t.fails + 1, streak, lastFail: error, lastFailAt: now } : t));
```

- [ ] **Step 6: Write `frontend/src/store/sessionOps.ts`**

```ts
import type { Message, SessionRec, SessionState, TalosMessage } from "./types";

export const curSession = (s: SessionState): SessionRec => s.sessions.find((x) => x.id === s.curId)!;
/** The session the conversation column shows: the one being read, or the current one. */
export const shownSession = (s: SessionState): SessionRec => s.sessions.find((x) => x.id === (s.viewId ?? s.curId))!;

const mapSession = (s: SessionState, id: string, fn: (x: SessionRec) => SessionRec): SessionState => ({
  ...s,
  sessions: s.sessions.map((x) => (x.id === id ? fn(x) : x)),
});

/** addYou() (line 936), after submit() marks earlier messages past (line 1455). */
export function addYou(s: SessionState, sessionId: string, text: string, key: string): SessionState {
  return mapSession(s, sessionId, (x) => ({
    ...x,
    messages: [...x.messages.map((m) => ({ ...m, past: true })), { kind: "you", key, text, past: false }],
  }));
}

/** addTalos() (line 942). */
export function addTalos(s: SessionState, sessionId: string, runN: number, key: string, thinking: string): SessionState {
  const m: TalosMessage = { kind: "talos", key, runN, status: thinking, html: null, wrap: true, wordsOn: 0, note: null, chips: [], suggest: false, stopNote: null, runLink: false, past: false };
  return mapSession(s, sessionId, (x) => ({ ...x, messages: [...x.messages, m] }));
}

export function updateTalos(s: SessionState, runN: number, fn: (m: TalosMessage) => TalosMessage): SessionState {
  return {
    ...s,
    sessions: s.sessions.map((x) =>
      x.messages.some((m) => m.kind === "talos" && m.runN === runN)
        ? { ...x, messages: x.messages.map((m): Message => (m.kind === "talos" && m.runN === runN ? fn(m) : m)) }
        : x,
    ),
  };
}

export const rename = (s: SessionState, sessionId: string, name: string): SessionState => mapSession(s, sessionId, (x) => ({ ...x, name }));
export const attachRun = (s: SessionState, sessionId: string, runId: string): SessionState =>
  mapSession(s, sessionId, (x) => ({ ...x, runIds: [...x.runIds, runId] }));

/** newSession() (line 2157): keep the old current session if it has runs, else drop it. */
export function openNewSession(s: SessionState, rec: { id: string; name: string; started: string }): SessionState {
  const cur = s.sessions.find((x) => x.id === s.curId);
  let sessions = s.sessions;
  if (cur && cur.runIds.length) sessions = sessions.map((x) => (x.id === cur.id ? { ...x, live: false } : x));
  else if (cur) sessions = sessions.filter((x) => x.id !== cur.id);
  const next: SessionRec = { ...rec, live: true, runIds: [], messages: [] };
  return { sessions: [...sessions, next], curId: next.id, viewId: null, count: s.count + 1 };
}
```

- [ ] **Step 7: Write the data-source interface and the demo implementation**

`frontend/src/data/source.ts`:

```ts
import type { Run, SessionRec, SettingsState, VaultTool } from "../store/types";

/** Where the stores load from. Demo: createDemoDataSource() (part A). Live: the API (part B). */
export interface DataSource {
  vault(): Promise<VaultTool[]>;
  toolSource(name: string): Promise<string[] | null>;
  settings(): Promise<SettingsState>;
  setAskBeforeExec(on: boolean): Promise<void>;
  /** Past sessions with their runs (final state) and messages, plus the highest run number used. */
  sessions(): Promise<{ sessions: SessionRec[]; runs: Run[]; lastRunNumber: number }>;
  /** Creates the next session. `count` is its number (Session {count}). */
  newSession(count: number): Promise<{ id: string; name: string; started: string }>;
  removeTool(name: string): Promise<void>;
}
```

`frontend/src/demo/seeds.ts` (port of `staticRun`, `sessionHtml` and `seedSessions`, lines 2205–2253):

```ts
import { initStrip, nextKey, STRIPS } from "../store/runOps";
import type { CallArg, LogLine, Message, NodeState, Run, SessionRec, VaultTool } from "../store/types";
import type { StepKey } from "../transport/types";

interface Seed {
  forge?: boolean;
  tool: string;
  query: string;
  args: CallArg[];
  result: string;
  type: string;
  answer: string;
  label?: string;
  log?: [string, string, string?][];
}

function staticRun(n: number, sessionId: string, o: Seed, tools: VaultTool[]): Run {
  const t = tools.find((x) => x.name === o.tool) ?? { args: "", ret: "" };
  let run: Run = {
    id: `run-${n}`, sessionId, n, query: o.query, tab: "call", status: "done", log: [], nodes: {}, links: {}, tabs: [], strip: "forge",
    seeded: true, answer: o.answer, toolUsed: o.tool, forged: !!o.forge,
  };
  run = initStrip(run, o.forge ? "forge" : "vault");
  const st: Partial<Record<StepKey, NodeState>> = o.forge
    ? { planner: "done", forger: "forge", tester: "forge", human: "skip", learn: "done", executor: "done", answer: "answer" }
    : { planner: "done", vault: "done", skip: "skip", executor: "done", answer: "answer" };
  const nodes = { ...run.nodes };
  for (const [k, state] of Object.entries(st) as [StepKey, NodeState][]) {
    const node = nodes[k];
    if (node) nodes[k] = { ...node, state };
  }
  const keys = STRIPS[run.strip].map((x) => x[0]);
  const links: Record<string, boolean> = {};
  for (let i = 0; i < keys.length - 1; i++) links[`${keys[i]}-${keys[i + 1]}`] = true;
  const L = (label: string, text: string, tone?: string): LogLine => ({ label, text, tone, kind: "ln", key: nextKey() });
  const lines = o.log
    ? o.log.map((x) => L(...x))
    : o.forge
      ? [L("plan", "1 sub-task, needs a new tool"), L("vault", "no match"), L("forge", `${o.tool}()`, "g"), L("test", "passed", "g"), L("learn", "saved to the vault"), L("execute", "done", "w")]
      : [L("plan", "1 sub-task, in the vault"), L("vault", o.tool), L("execute", "done", "w")];
  const logStatus = o.forge ? "1 tool forged" : "0 tools forged";
  return {
    ...run, nodes, links,
    label: o.label || (o.forge ? "Sub-task 1 of 1, forged" : "Sub-task 1 of 1, found in the vault"),
    sig: { name: o.tool, args: t.args, ret: t.ret },
    caption: o.forge ? "Forged, tested and saved to the vault in this run." : "Done from the vault. The forge sub-graph never ran.",
    tabs: [{ id: "call", label: "Call" }],
    tab: "call",
    call: { args: o.args, result: o.result, resultType: o.type },
    log: [{ kind: "cmd", text: o.query, key: nextKey() }, ...lines],
    logStatus, logStatusGold: !!o.forge, logTone: o.forge ? "" : "warm",
    summary: logStatus, summaryGold: !!o.forge,
  };
}

/** sessionHtml() (line 2229) as messages: no word wrapping, one chip, a run link. */
function transcript(runs: Run[]): Message[] {
  return runs.flatMap((r): Message[] => [
    { kind: "you", key: `you-${r.n}`, text: r.query, past: false },
    {
      kind: "talos", key: `talos-${r.n}`, runN: r.n, status: null, html: r.answer ?? "", wrap: false, wordsOn: 0, note: null,
      chips: [{ kind: r.forged ? "forged" : "reused", text: `${r.forged ? "Forged" : "Reused"} ${r.toolUsed}${r.forged ? "" : " from the vault"}` }],
      suggest: false, stopNote: null, runLink: true, past: false,
    },
  ]);
}

export function seedSessions(tools: VaultTool[]): { sessions: SessionRec[]; runs: Run[]; lastRunNumber: number } {
  const b64 = "VGFsb3MgZm9yZ2VzIHRvb2xzIGF0IHJ1bnRpbWU=";
  let n = 0;
  const mk = (sid: string, o: Seed) => staticRun(++n, sid, o, tools);
  const seeds: { id: string; name: string; started: string; runs: Run[] }[] = [
    { id: "seed-fib", name: "Fibonacci tools", started: "2026-09-28T14:20", runs: [
      mk("seed-fib", { forge: true, tool: "nth_fibonacci", query: "Build me a tool that returns the Nth Fibonacci number. Then use it to get the 20th Fibonacci number.", args: [["n", "20"]], result: "6765", type: "int", answer: "The 20th Fibonacci number is 6765." }),
      mk("seed-fib", { tool: "nth_fibonacci", query: "What is the 30th Fibonacci number?", args: [["n", "30"]], result: "832040", type: "int", answer: "It's 832040." }),
    ] },
    { id: "seed-lev", name: "Edit distance", started: "2026-09-28T14:23", runs: [
      mk("seed-lev", { forge: true, tool: "levenshtein_distance", query: 'Forge a tool that computes the Levenshtein edit distance between two strings. What\'s the distance between "kitten" and "sitting"?', args: [["s1", '"kitten"'], ["s2", '"sitting"']], result: "3", type: "int", answer: 'The edit distance between "kitten" and "sitting" is 3.' }),
      mk("seed-lev", { tool: "levenshtein_distance", query: 'How similar are the words "algorithm" and "altruistic"? Use edit distance.', args: [["s1", '"algorithm"'], ["s2", '"altruistic"']], result: "6", type: "int", answer: "They're 6 edits apart, so not very similar." }),
    ] },
    { id: "seed-b64", name: "Base64 round trip", started: "2026-09-28T14:29", runs: [
      mk("seed-b64", { forge: true, tool: "base64_codec", label: "Sub-task 2 of 2, decode", query: 'Build a tool that base64-encodes and decodes strings. Encode "Talos forges tools at runtime" and then decode the result to verify.', args: [["text", `"${b64}"`], ["mode", '"decode"']], result: "'Talos forges tools at runtime'", type: "str",
        answer: `Encoded, it's <span class="mono">${b64}</span>. Decoding that gives back "Talos forges tools at runtime", so the round trip works.`,
        log: [["plan", "2 sub-tasks, 1 needs a new tool"], ["vault", "no match"], ["forge", "base64_codec()", "g"], ["test", "passed", "g"], ["learn", "saved to the vault"], ["execute", "encode, done", "w"], ["vault", "base64_codec"], ["execute", "decode, done", "w"]] }),
    ] },
  ];
  return {
    sessions: seeds.map((x) => ({ id: x.id, name: x.name, started: x.started, live: false, runIds: x.runs.map((r) => r.id), messages: transcript(x.runs) })),
    runs: seeds.flatMap((x) => x.runs),
    lastRunNumber: n,
  };
}
```

`frontend/src/demo/source.ts`:

```ts
import type { DataSource } from "../data/source";
import { COPY, fill } from "../lib/copy";
import { nowIso } from "../lib/format";
import { freshVault } from "../store/vaultOps";
import { MODEL, SOURCES, VAULT_ROWS } from "./data";
import { seedSessions } from "./seeds";

/** In-memory data for demo mode: the reference's vault, seeded sessions and settings. */
export function createDemoDataSource(): DataSource {
  return {
    vault: async () => freshVault(VAULT_ROWS),
    toolSource: async (name) => SOURCES[name] ?? null,
    settings: async () => ({ askExec: true, env: {}, model: MODEL }),
    setAskBeforeExec: async () => {},
    sessions: async () => seedSessions(freshVault(VAULT_ROWS)),
    newSession: async (count) => ({ id: `s${count}-${Date.now()}`, name: fill(COPY.convo.sessionName, { n: count }), started: nowIso() }),
    removeTool: async () => {},
  };
}
```

`frontend/src/test/parity/runs.ts`:

```ts
import type { Run } from "../../store/types";

/** Fixture run objects are the reference's; they have no id or sessionId. */
export function asRun(json: unknown): Run {
  const r = json as Partial<Run> & { n: number };
  return { id: `run-${r.n}`, sessionId: "s", ...r } as Run;
}
```

- [ ] **Step 8: Write `frontend/src/store/stores.tsx`**

```tsx
import { createContext, useContext, type ReactNode } from "react";
import { createStore, useStoreState, type Store } from "./createStore";
import type { Run, RunsState, SessionRec, SessionState, SettingsState, UiState, VaultState, VaultTool } from "./types";

export interface Stores {
  runs: Store<RunsState>;
  session: Store<SessionState>;
  vault: Store<VaultState>;
  settings: Store<SettingsState>;
  ui: Store<UiState>;
}

export interface InitialData {
  tools: VaultTool[];
  settings: SettingsState;
  sessions: SessionRec[];
  runs: Run[];
  current: { id: string; name: string; started: string };
  count: number;
}

export const initialUi = (): UiState => ({
  view: "workbench", viewEnter: 0, dialog: null, busy: false, currentRunId: null, viewingRunId: null,
  selected: "caesar_cipher", filter: "all", query: "", stagger: false, vaultRender: 0, popOpen: false, speed: 1, badge: false,
  booted: false, live: "", confirmRemove: null, draft: "", benchKey: 0, titleAnimate: false,
});

export function initialStates(d: InitialData) {
  return {
    runs: { byId: Object.fromEntries(d.runs.map((r) => [r.id, r])) } as RunsState,
    session: {
      sessions: [...d.sessions, { ...d.current, live: true, runIds: [], messages: [] }],
      curId: d.current.id,
      viewId: null,
      count: d.count,
    } as SessionState,
    vault: { tools: d.tools, sources: {} } as VaultState,
    settings: d.settings,
    ui: initialUi(),
  };
}

export function createStores(d: InitialData): Stores {
  const s = initialStates(d);
  return { runs: createStore(s.runs), session: createStore(s.session), vault: createStore(s.vault), settings: createStore(s.settings), ui: createStore(s.ui) };
}

export function updateRun(stores: Stores, id: string, fn: (r: Run) => Run): void {
  stores.runs.update((s) => {
    const r = s.byId[id];
    return r ? { byId: { ...s.byId, [id]: fn(r) } } : s;
  });
}

export const StoresContext = createContext<Stores | null>(null);
export function StoresProvider({ stores, children }: { stores: Stores; children: ReactNode }) {
  return <StoresContext.Provider value={stores}>{children}</StoresContext.Provider>;
}
export function useStores(): Stores {
  const s = useContext(StoresContext);
  if (!s) throw new Error("StoresProvider is missing");
  return s;
}
export const useRuns = <T,>(sel: (s: RunsState) => T) => useStoreState(useStores().runs, sel);
export const useSession = <T,>(sel: (s: SessionState) => T) => useStoreState(useStores().session, sel);
export const useVault = <T,>(sel: (s: VaultState) => T) => useStoreState(useStores().vault, sel);
export const useSettings = <T,>(sel: (s: SettingsState) => T) => useStoreState(useStores().settings, sel);
export const useUi = <T,>(sel: (s: UiState) => T) => useStoreState(useStores().ui, sel);
```

- [ ] **Step 9: Write the tests**

`frontend/src/store/runOps.test.ts`:

```ts
import { fixtureCase, snap } from "../test/parity";
import { asRun } from "../test/parity/runs";
import { flow, initStrip, log, logPop, newRun, railPercent, setNode, startCmd, typeCmd, endCmd } from "./runOps";

const base = () => newRun({ id: "run-6", n: 6, query: "q", sessionId: "s" });

test("initStrip builds the reference's nodes for every variant", () => {
  const ref = asRun(fixtureCase("strip/forge-pending").state.run);
  expect(initStrip(base(), "forge").nodes).toEqual(ref.nodes);
  const vault = initStrip(base(), "vault");
  expect(vault.nodes.skip).toEqual({ label: "Forge sub-graph skipped", llm: false, state: "skip" });
  expect(Object.keys(initStrip(base(), "chat").nodes)).toEqual(["planner", "answer"]);
});

test("initStrip with keep carries shared steps across variants", () => {
  const run = setNode(initStrip(base(), "forge"), "planner", "done");
  const v = initStrip(run, "vault", true);
  expect(v.nodes.planner!.state).toBe("done");
  expect(v.nodes.skip!.state).toBe("skip");
});

test("newRun starts like the reference's submit()", () => {
  const ref = asRun(fixtureCase("bench/planning").state.run);
  const run = initStrip(newRun({ id: "x", n: ref.n, query: ref.query, sessionId: "s" }), "forge");
  for (const k of ["tab", "title", "label", "status", "strip", "nodes", "links", "tabs"] as const) expect(run[k]).toEqual(ref[k]);
});

test("setNode keeps the label unless given one; flow lights and counts", () => {
  let run = initStrip(base(), "primitive");
  run = setNode(run, "executor", "active", "Executor, waiting for you");
  expect(run.nodes.executor).toMatchObject({ state: "active", label: "Executor, waiting for you" });
  run = setNode(run, "executor", "done");
  expect(run.nodes.executor!.label).toBe("Executor, waiting for you");
  run = flow(flow(run, "planner", "primitive"), "planner", "primitive");
  expect(run.links["planner-primitive"]).toBe(true);
  expect(run.flows!["planner-primitive"]).toBe(2);
});

test("log clears carets and freshness, logPop removes the last line, the command types in", () => {
  let run = startCmd(base(), "hello world");
  run = typeCmd(run, 5);
  expect(run.log[0]).toMatchObject({ kind: "cmd", shown: 5, typing: true });
  run = endCmd(run);
  expect(run.log[0]).toMatchObject({ shown: null, typing: false });
  run = log(run, "test", "running", "g", { caret: true });
  run = log(run, "test", "4 of 5 passed, retrying", "g");
  expect(run.log[1]).toMatchObject({ caret: false, fresh: false });
  expect(run.log[2]).toMatchObject({ kind: "ln", caret: false, fresh: true, tone: "g" });
  run = log(run, "", "test_decrypt_reverses_encrypt", "", { sub: true });
  expect(run.log[3]!.kind).toBe("sub");
  expect(logPop(run).log).toHaveLength(3);
});

test("railPercent matches updateRail()", () => {
  expect(railPercent(asRun(fixtureCase("bench/planning").state.run))).toBe(0);
  const planning = snap("caesar-forge", "planning");
  expect(railPercent(asRun(planning.run))).toBe(7);
  expect(planning.regions["#bench"]).toContain("width: 7%");
  expect(railPercent(asRun(fixtureCase("bench/chat-done").state.run))).toBe(100);
});
```

`frontend/src/store/vaultOps.test.ts`:

```ts
import { VAULT_ROWS } from "../demo/data";
import { fixtureCase } from "../test/parity";
import type { VaultTool } from "./types";
import { freshVault, fromVaultEntry, recordFailure, recordUse, removeTool, vaultRows } from "./vaultOps";

test("freshVault equals the reference's S.vault at boot", () => {
  expect(freshVault(VAULT_ROWS)).toEqual(fixtureCase("vault/default").state.tools);
});

test("vaultRows filters, searches and sorts like the reference", () => {
  const tools = freshVault(VAULT_ROWS);
  const html = fixtureCase("vault/failed-query").html!;
  const rows = vaultRows(tools, "failed", "date");
  expect(rows.map((t) => t.name)).toEqual(["normalize_date_strings"]);
  expect(html).toContain('data-tool="normalize_date_strings"');
  expect(vaultRows(tools, "web", "").every((t) => t.web)).toBe(true);
  expect(vaultRows(tools, "all", "zzzz")).toEqual([]);
  expect(vaultRows(tools, "all", "")[0]!.name).toBe("flatten_json");
});

test("use, failure, removal and API entries", () => {
  let tools: VaultTool[] = freshVault(VAULT_ROWS);
  tools = recordUse(tools, "flatten_json", "2026-09-30T12:00");
  expect(tools.find((t) => t.name === "flatten_json")).toMatchObject({ uses: 3, streak: 0, last: "2026-09-30T12:00" });
  tools = recordFailure(tools, "flatten_json", 1, "TypeError: x", "2026-09-30T12:01");
  expect(tools.find((t) => t.name === "flatten_json")).toMatchObject({ fails: 2, streak: 1, lastFail: "TypeError: x", lastFailAt: "2026-09-30T12:01" });
  expect(removeTool(tools, "flatten_json")).toHaveLength(39);
  expect(
    fromVaultEntry({ name: "a", args: "x: int", ret: "int", signature: "a(x: int) -> int", description: "d", keywords: ["k"], uses: 0, failures: 0, streak: 0, created_at: "2026-09-30T12:00", last_used: null, last_failure: null, last_failed_at: null, web: false, file: "talos/vault/tools/a.py" }, true),
  ).toEqual({ name: "a", args: "x: int", ret: "int", desc: "d", kw: ["k"], uses: 0, fails: 0, streak: 0, created: "2026-09-30T12:00", last: "", lastFail: "", lastFailAt: "", web: false, fresh: true });
});
```

`frontend/src/store/sessionOps.test.ts`:

```ts
import { addTalos, addYou, openNewSession, updateTalos } from "./sessionOps";
import type { SessionState } from "./types";

const empty = (): SessionState => ({ sessions: [{ id: "s1", name: "Session 1", started: "2026-09-30T12:00", live: true, runIds: [], messages: [] }], curId: "s1", viewId: null, count: 1 });

test("addYou marks earlier messages past; addTalos starts thinking", () => {
  let s = addYou(empty(), "s1", "one", "y1");
  s = addTalos(s, "s1", 6, "t1", "Working on it");
  s = addYou(s, "s1", "two", "y2");
  const msgs = s.sessions[0]!.messages;
  expect(msgs.map((m) => m.past)).toEqual([true, true, false]);
  expect(msgs[1]).toMatchObject({ kind: "talos", status: "Working on it", html: null, runLink: false });
  s = updateTalos(s, 6, (m) => ({ ...m, runLink: true }));
  expect(s.sessions[0]!.messages[1]).toMatchObject({ runLink: true });
});

test("openNewSession drops an empty current session and keeps one with runs", () => {
  let s = openNewSession(empty(), { id: "s2", name: "Session 2", started: "2026-09-30T12:05" });
  expect(s.sessions.map((x) => x.id)).toEqual(["s2"]);
  expect(s.count).toBe(2);
  s = { ...s, sessions: s.sessions.map((x) => ({ ...x, runIds: ["run-6"] })) };
  s = openNewSession(s, { id: "s3", name: "Session 3", started: "2026-09-30T12:06" });
  expect(s.sessions.map((x) => [x.id, x.live])).toEqual([["s2", false], ["s3", true]]);
  expect(s.curId).toBe("s3");
});
```

`frontend/src/demo/seeds.test.ts`:

```ts
import { fixtureCase } from "../test/parity";
import { freshVault } from "../store/vaultOps";
import { VAULT_ROWS } from "./data";
import { seedSessions } from "./seeds";

const strip = (x: unknown): unknown => JSON.parse(JSON.stringify(x, (k, v) => (["key", "id", "sessionId", "runIds", "messages", "cancelled"].includes(k) ? undefined : v)));

test("seeded sessions and runs equal the reference's seedSessions()", () => {
  const ours = seedSessions(freshVault(VAULT_ROWS));
  const all = fixtureCase("seeds/sessions").value as { id: string; name: string; started: string; live: boolean; runs: unknown[] }[];
  const ref = all.filter((s) => s.id.startsWith("seed-")); // the fourth is the boot session, "Session 1"
  expect(ours.lastRunNumber).toBe(5);
  expect(ours.sessions.map((s) => [s.id, s.name, s.started, s.live])).toEqual(ref.map((s) => [s.id, s.name, s.started, s.live]));
  expect(strip(ours.runs)).toEqual(strip(ref.flatMap((s) => s.runs)));
});
```

`frontend/src/store/stores.test.tsx`:

```tsx
import { act, render, screen } from "@testing-library/react";
import { createStores, StoresProvider, updateRun, useRuns } from "./stores";
import { newRun } from "./runOps";

function Label({ id }: { id: string }) {
  const label = useRuns((s) => s.byId[id]?.label);
  return <span>{label}</span>;
}

test("components re-render from store updates, and getState is synchronous", () => {
  const stores = createStores({ tools: [], settings: { askExec: true, env: {}, model: "m" }, sessions: [], runs: [newRun({ id: "r", n: 1, query: "q", sessionId: "s1" })], current: { id: "s1", name: "Session 1", started: "2026-09-30T12:00" }, count: 1 });
  render(<StoresProvider stores={stores}><Label id="r" /></StoresProvider>);
  expect(screen.getByText("Planning")).toBeInTheDocument();
  act(() => updateRun(stores, "r", (r) => ({ ...r, label: "Sub-task 1 of 1, needs a new tool" })));
  expect(stores.runs.get().byId.r!.label).toBe("Sub-task 1 of 1, needs a new tool");
  expect(screen.getByText("Sub-task 1 of 1, needs a new tool")).toBeInTheDocument();
});
```

- [ ] **Step 10: Run the tests to verify they fail, then pass**

Write the tests first (Step 9) and run `npx vitest run src/store src/demo` before Steps 2–8: FAIL (modules not found). After Steps 1–8: `npx vitest run src/store src/demo && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/transport/types.ts frontend/src/store frontend/src/data frontend/src/demo frontend/src/test/parity/runs.ts
git commit -m "[Feat]: Add the event contract types, the stores and the demo data source"
```

---

### Task 6: Animation and focus hooks

**Files:**
- Create: `frontend/src/hooks/useScramble.ts`, `useCountUp.ts`, `useRestartAnimation.ts`, `useTabIndicator.ts`, `useFocusTrap.ts`, `usePointerGlow.ts`
- Create: `frontend/src/test/ssr.ts`
- Test: `frontend/src/hooks/hooks.test.tsx`

**Interfaces:**
- Consumes: `scramble`, `countUp`, `still` (Task 3).
- Produces:
  - `useScramble(ref: RefObject<HTMLElement | null>, text: string, duration: number, opts?: { onMount?: boolean }): void`: scrambles `text` into `ref` whenever `text` changes, and on mount when `onMount`.
  - `useCountUp(ref: RefObject<HTMLElement | null>, target: number): void`: counts up once, on mount.
  - `useRestartAnimation(ref: RefObject<HTMLElement | null>, className: string, trigger: unknown, opts?: { initial?: boolean }): void`: when `trigger` changes (and on mount if `initial`), removes the class, forces a reflow and adds it back, as the reference does by hand.
  - `useTabIndicator(tabsRef: RefObject<HTMLElement | null>, selected: string, tabsKey: string): void`: `placeInd()` (line 1142).
  - `useFocusTrap(ref: RefObject<HTMLElement | null>, opts: { onEscape: () => void; initialFocus: string }): void`: the key handling and focus restore of `openDialog()` (line 1341).
  - `usePointerGlow(): void`: sets `--mx`/`--my` on `.try` cards (line 2145).
  - `src/test/ssr.ts`: `ssr(el: ReactElement): string` (`renderToStaticMarkup`), `innerOf(html: string, sel?: string): string` (inner HTML of the element matching `sel`, or of the first element).

**Rule for imperatively animated text.** `scramble()` and `countUp()` write `textContent`, which would orphan a React-managed text node. So every element they touch renders its text with `dangerouslySetInnerHTML={{ __html: esc(text) }}` and no children. The server render (and the parity tests) still see the final text.

**Rule for one-shot classes.** An imperatively added class survives only while the element's `className` prop doesn't change. Where the reference keeps such a class on an element whose other classes change (the `flow` class on a strip link), the component puts it in `className` from state (Task 8 shows how) and uses `useRestartAnimation` only to replay it.

- [ ] **Step 1: Write the failing test** `frontend/src/hooks/hooks.test.tsx`

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { setReducedMotion } from "../test/media";
import { useFocusTrap } from "./useFocusTrap";
import { usePointerGlow } from "./usePointerGlow";
import { useRestartAnimation } from "./useRestartAnimation";
import { useScramble } from "./useScramble";
import { useTabIndicator } from "./useTabIndicator";

afterEach(() => vi.useRealTimers());

function Title({ text }: { text: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useScramble(ref, text, 600);
  return <span data-testid="t" ref={ref} dangerouslySetInnerHTML={{ __html: text }} />;
}

test("useScramble decodes new text into place and settles on it", () => {
  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
  const { rerender } = render(<Title text="Session 1" />);
  expect(screen.getByTestId("t").textContent).toBe("Session 1");
  rerender(<Title text="Caesar cipher" />);
  act(() => void vi.advanceTimersByTime(100));
  expect(screen.getByTestId("t").textContent).not.toBe("Caesar cipher");
  act(() => void vi.advanceTimersByTime(700));
  expect(screen.getByTestId("t").textContent).toBe("Caesar cipher");
});

function Panel({ tab }: { tab: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useRestartAnimation(ref, "panel-in", tab);
  return <div data-testid="p" className="stack" ref={ref} />;
}

test("useRestartAnimation adds the class on change, not on mount", () => {
  const { rerender } = render(<Panel tab="log" />);
  expect(screen.getByTestId("p").className).toBe("stack");
  rerender(<Panel tab="code" />);
  expect(screen.getByTestId("p").className).toBe("stack panel-in");
});

function Tabs() {
  const [sel, setSel] = useState("a");
  const ref = useRef<HTMLDivElement>(null);
  useTabIndicator(ref, sel, "run-1");
  return (
    <div className="tabs" ref={ref}>
      <button className="tab" aria-selected={String(sel === "a")} onClick={() => setSel("a")}>A</button>
      <button className="tab" aria-selected={String(sel === "b")} onClick={() => setSel("b")}>B</button>
      <span className="tab-ind" data-testid="ind" />
    </div>
  );
}

test("useTabIndicator places the indicator under the selected tab", () => {
  const offsets = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
    return this.textContent === "B" ? 60 : 0;
  });
  const widths = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(50);
  render(<Tabs />);
  expect(screen.getByTestId("ind").style.left).toBe("0px");
  fireEvent.click(screen.getByText("B"));
  expect(screen.getByTestId("ind").style.left).toBe("60px");
  expect(screen.getByTestId("ind").style.width).toBe("50px");
  offsets.mockRestore();
  widths.mockRestore();
});

function Dialog({ onEscape }: { onEscape: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, { onEscape, initialFocus: '[data-d="no"]' });
  return (
    <div ref={ref}>
      <button data-d="no">Don't run</button>
      <button data-d="yes">Run code</button>
    </div>
  );
}

test("useFocusTrap focuses, traps Tab, handles Escape and restores focus", () => {
  const outside = document.createElement("button");
  document.body.append(outside);
  outside.focus();
  const onEscape = vi.fn();
  const { unmount } = render(<Dialog onEscape={onEscape} />);
  expect(document.activeElement).toBe(screen.getByText("Don't run"));
  fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(screen.getByText("Run code"));
  fireEvent.keyDown(document.activeElement!, { key: "Tab" });
  expect(document.activeElement).toBe(screen.getByText("Don't run"));
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(onEscape).toHaveBeenCalledTimes(1);
  unmount();
  expect(document.activeElement).toBe(outside);
  outside.remove();
});

function Glow() {
  usePointerGlow();
  return <button className="try" data-testid="card"><span className="q">x</span></button>;
}

test("usePointerGlow sets --mx and --my on the card under the pointer", () => {
  render(<Glow />);
  const card = screen.getByTestId("card");
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20 } as DOMRect);
  fireEvent.pointerMove(card.firstChild!, { clientX: 50, clientY: 70 });
  expect(card.style.getPropertyValue("--mx")).toBe("40px");
  expect(card.style.getPropertyValue("--my")).toBe("50px");
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/hooks`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the hooks**

`frontend/src/hooks/useScramble.ts`:

```ts
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
```

`frontend/src/hooks/useCountUp.ts`:

```ts
import { useLayoutEffect, type RefObject } from "react";
import { countUp } from "../lib/motion";

export function useCountUp(ref: RefObject<HTMLElement | null>, target: number): void {
  // renderIdle() counts up once per render of the idle bench (line 1077).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => countUp(ref.current, target), []);
}
```

`frontend/src/hooks/useRestartAnimation.ts`:

```ts
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
```

`frontend/src/hooks/useTabIndicator.ts`:

```ts
import { useLayoutEffect, useRef, type RefObject } from "react";

/** placeInd() (line 1142): slide .tab-ind from the previous tab to the selected one. `tabsKey` resets it. */
export function useTabIndicator(tabsRef: RefObject<HTMLElement | null>, selected: string, tabsKey: string): void {
  const last = useRef<{ key: string; pos: { l: number; w: number } | null }>({ key: tabsKey, pos: null });
  useLayoutEffect(() => {
    const tabs = tabsRef.current;
    if (!tabs) return;
    const ind = tabs.querySelector<HTMLElement>(".tab-ind");
    const sel = tabs.querySelector<HTMLElement>('.tab[aria-selected="true"]');
    if (!ind || !sel) return;
    if (last.current.key !== tabsKey) last.current = { key: tabsKey, pos: null };
    const to = { l: sel.offsetLeft, w: sel.offsetWidth };
    const from = last.current.pos ?? to;
    ind.style.transition = "none";
    ind.style.left = `${from.l}px`;
    ind.style.width = `${from.w}px`;
    void ind.offsetWidth;
    ind.style.transition = "";
    ind.style.left = `${to.l}px`;
    ind.style.width = `${to.w}px`;
    last.current.pos = to;
  });
}
```

`frontend/src/hooks/useFocusTrap.ts`:

```ts
import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = 'button, input, [href], [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(ref: RefObject<HTMLElement | null>, opts: { onEscape: () => void; initialFocus: string }): void {
  const onEscape = useRef(opts.onEscape);
  onEscape.current = opts.onEscape;
  useEffect(() => {
    const prevFocus = document.activeElement as HTMLElement | null;
    const dlg = ref.current;
    dlg?.querySelector<HTMLElement>(opts.initialFocus)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onEscape.current();
      }
      if (e.key === "Tab" && dlg) {
        const f = [...dlg.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => !(x as HTMLButtonElement).disabled);
        if (!f.length) return;
        const first = f[0]!;
        const last = f[f.length - 1]!;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prevFocus?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
```

`frontend/src/hooks/usePointerGlow.ts`:

```ts
import { useEffect } from "react";

export function usePointerGlow(): void {
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const t = (e.target as Element | null)?.closest?.(".try") as HTMLElement | null;
      if (!t) return;
      const b = t.getBoundingClientRect();
      t.style.setProperty("--mx", `${e.clientX - b.left}px`);
      t.style.setProperty("--my", `${e.clientY - b.top}px`);
    };
    document.addEventListener("pointermove", onMove);
    return () => document.removeEventListener("pointermove", onMove);
  }, []);
}
```

`frontend/src/test/ssr.ts`:

```ts
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

/** Server-renders a component; effects don't run, which is what the reference's pure renderers match. */
export const ssr = (el: ReactElement): string => renderToStaticMarkup(el);

export function innerOf(html: string, sel?: string): string {
  const t = document.createElement("template");
  t.innerHTML = html;
  const el = sel ? t.content.querySelector(sel) : t.content.firstElementChild;
  if (!el) throw new Error(`innerOf: nothing matches ${sel ?? "the first element"}`);
  return el.innerHTML;
}
```

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/hooks && npm run lint && npm run typecheck`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks frontend/src/test/ssr.ts
git commit -m "[Feat]: Add the scramble, restart, tab indicator, focus trap and pointer glow hooks"
```

---

### Task 7: Header and Demo controls

**Files:**
- Create: `frontend/src/components/icons.tsx`, `frontend/src/components/Header.tsx`, `frontend/src/components/DemoControls.tsx`
- Test: `frontend/src/components/Header.test.tsx`

**Interfaces:**
- Consumes: `COPY` (Task 4), `ssr` (Task 6), `fixtureCase`, `snap`, `expectParity` (Task 2).
- Produces:
  - `XIcon()`, `TickIcon({ done }: { done: boolean })`, `GitHubIcon()` from `icons.tsx`.
  - `Header(props: HeaderProps)`, `HeaderProps = { mode: "demo" | "live"; busy: boolean; badge: boolean; view: View; model: string; popOpen: boolean; speed: number; onTogglePop(open?: boolean): void; onSpeed(speed: number): void; onReset(): void }`.
  - `DemoControls({ popOpen, speed, onTogglePop, onSpeed, onReset })`.

Transcribe lines 597–625. `DemoControls` is lines 610–622 and renders only when `mode === "demo"` (spec 04 §8.1). The nav link for the current view gets `aria-current="page"` (showView, line 2084). The brand gets `className="brand busy"` while busy (setBusy, line 1503). The badge is `<span className="badge" id="vault-badge" hidden={!badge}></span>`.

`DemoControls` owns two document listeners (lines 2132–2136, 2150): Escape closes the popover; a click outside `#demo-pop` closes it, except clicks the reference handles earlier in the same listener, which return before reaching `togglePop(false)`: `[data-suggest], [data-ask], [data-action="stop"], [data-tab], [data-open-tool], [data-run], [data-tool], [data-read-src], [data-use-tool], [data-remove-tool], #ask-switch, [data-speed], #demo-toggle, #demo-reset`.

- [ ] **Step 1: Write the failing test** `frontend/src/components/Header.test.tsx`

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { expectParity, fixtureCase, snap } from "../test/parity";
import { ssr } from "../test/ssr";
import type { View } from "../store/types";
import { Header, type HeaderProps } from "./Header";

const props = (s: Record<string, unknown>): HeaderProps => ({
  mode: "demo", busy: !!s.busy, badge: !!s.badge, view: (s.view as View) ?? "workbench", model: "deepseek/deepseek-v4.1-flash",
  popOpen: !!s.popOpen, speed: (s.speed as number) ?? 1, onTogglePop: () => {}, onSpeed: () => {}, onReset: () => {},
});

test.each(["header/default", "header/busy-badge-pop"])("%s matches the reference", (id) => {
  const c = fixtureCase(id);
  expectParity(ssr(<Header {...props(c.state)} />), c.html!);
});

test.each([["open", { popOpen: true, speed: 1 }], ["fast", { popOpen: true, speed: 2 }], ["closed", { popOpen: false, speed: 2 }]] as const)(
  "demo controls %s",
  (name, s) => {
    expectParity(ssr(<Header {...props(s)} />), snap("demo-controls", name).regions["header.top"]!);
  },
);

test("live mode has no Demo controls", () => {
  render(<Header {...props({})} mode="live" />);
  expect(screen.queryByText("Demo controls")).toBeNull();
  expect(screen.getByText("deepseek/deepseek-v4.1-flash")).toBeInTheDocument();
});

test("the popover opens, picks a speed, resets, and closes on Escape or an outside click", () => {
  const onTogglePop = vi.fn();
  const onSpeed = vi.fn();
  const onReset = vi.fn();
  render(<Header {...props({ popOpen: true })} onTogglePop={onTogglePop} onSpeed={onSpeed} onReset={onReset} />);
  fireEvent.click(screen.getByText("Fast"));
  expect(onSpeed).toHaveBeenCalledWith(2);
  fireEvent.click(screen.getByText("Reset the demo"));
  expect(onReset).toHaveBeenCalled();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onTogglePop).toHaveBeenCalledWith(false);
  onTogglePop.mockClear();
  fireEvent.click(document.body);
  expect(onTogglePop).toHaveBeenCalledWith(false);
  onTogglePop.mockClear();
  fireEvent.click(screen.getByText("Demo controls"));
  expect(onTogglePop).toHaveBeenCalledTimes(1);
  expect(onTogglePop).toHaveBeenLastCalledWith();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/Header.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `icons.tsx`**

```tsx
/** X_ICON (line 998). */
export function XIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M2 2l8 8M10 2l-8 8"></path>
    </svg>
  );
}

/** The drawn check in the tests panel (line 1188). */
export function TickIcon({ done }: { done: boolean }) {
  return (
    <svg className={`tick${done ? " done" : ""}`} viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2 6.5l2.5 2.5L10 3"></path>
    </svg>
  );
}

/** The GitHub mark (line 623). Copy the `d` attribute from line 623 byte for byte. */
const GITHUB_D =
  "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z";
export function GitHubIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d={GITHUB_D}></path>
    </svg>
  );
}
```

- [ ] **Step 4: Transcribe `Header.tsx` and `DemoControls.tsx`**

`Header` renders `<header className="top">` with the brand (`<a className={busy ? "brand busy" : "brand"} id="brand" href="#workbench" aria-label={COPY.brand.aria}>`, the disc image `src="assets/apple-touch-icon.png" alt="" width="36" height="36"`, the ring and the word), the `nav` (four links from `COPY.nav`, each with `data-view` and `aria-current={view === v ? "page" : undefined}`), and `.top-right` with `<span className="model">{model}</span>`, `{mode === "demo" && <DemoControls … />}` and the GitHub pill (`target="_blank" rel="noopener"`, `<GitHubIcon />`, `<span className="gh-label">`). All text from `COPY`.

`DemoControls` renders `.demo-btn` exactly as lines 610–622: the toggle button (`aria-expanded={String(popOpen)} aria-controls="demo-pop"`, `onClick={() => onTogglePop()}`), the popover (`hidden={!popOpen}`), three `data-speed` buttons (`"0.5"`, `"1"`, `"2"`, `aria-pressed={String(speed === value)}`, `onClick={() => onSpeed(value)}`) and `#demo-reset` (`onClick={() => { onReset(); onTogglePop(false); }}`). Add the two document listeners from the task intro in one `useEffect`:

```tsx
const KEEP_OPEN =
  '[data-suggest], [data-ask], [data-action="stop"], [data-tab], [data-open-tool], [data-run], [data-tool], [data-read-src], [data-use-tool], [data-remove-tool], #ask-switch, [data-speed], #demo-toggle, #demo-reset, #demo-pop';

useEffect(() => {
  const onClick = (e: MouseEvent) => {
    if (!(e.target as Element | null)?.closest?.(KEEP_OPEN)) onTogglePop(false);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape" && popOpen) onTogglePop(false);
  };
  document.addEventListener("click", onClick);
  document.addEventListener("keydown", onKey);
  return () => {
    document.removeEventListener("click", onClick);
    document.removeEventListener("keydown", onKey);
  };
}, [popOpen, onTogglePop]);
```

- [ ] **Step 5: Run the tests**

Run: `npx vitest run src/components/Header.test.tsx && npm run lint && npm run typecheck`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/icons.tsx frontend/src/components/Header.tsx frontend/src/components/DemoControls.tsx frontend/src/components/Header.test.tsx
git commit -m "[Feat]: Add the header and the demo controls, matching the reference DOM"
```

---

### Task 8: Bench frame (Strip, Banner, Tabs, Bench, Idle)

**Files:**
- Create: `frontend/src/components/workbench/Strip.tsx`, `Banner.tsx`, `Tabs.tsx`, `Bench.tsx`, `Idle.tsx`
- Test: `frontend/src/components/workbench/frame.test.tsx`

**Interfaces:**
- Consumes: `STRIPS`, `railPercent` (Task 5), `COPY`, `fill` (Task 4), `esc` (Task 3), hooks (Task 6), `XIcon` (Task 7), `Panel` (Task 9; until then `Bench` renders `panel` passed in as a prop, see below).
- Produces:
  - `Strip({ run }: { run: Run })`.
  - `Banner({ banner }: { banner: Banner | null | undefined })`.
  - `Tabs({ run, onSelect }: { run: Run; onSelect(tab: TabId): void })`.
  - `Bench(props: BenchProps)`, `BenchProps = { run: Run; live: boolean; panel: ReactNode; onTab(tab: TabId): void; onStop(): void; onOpenTool(name: string): void }`. `live` = the rail's `running` state (updateRail, line 1053).
  - `Idle(props: IdleProps)`, `IdleProps = { count: number; weatherKeySet: boolean; askExec: boolean; onSuggest(i: number): void }`.

Transcription map:

| Component | Reference | Notes |
|---|---|---|
| `Strip` | `stripHtml` 1007–1019 | renders `<ol className="strip" id="b-strip" aria-label={COPY.bench.graph}>` around the items (the `ol` is in `renderBench`, line 1097). Node: `className={\`node ${n.state}\`}`, `data-node`, `aria-current={n.state === "active" ? "step" : undefined}`, `<XIcon />` first when `fail`, `<span className="nl">`, the pip when `llm`. Link: see the code below. |
| `Banner` | `bannerHtml` 1122–1128, `setBanner` 1115–1121 | saved: the name `<span className="mono gold" data-scramble="" ref=… dangerouslySetInnerHTML={{ __html: esc(name) }} />` with `useScramble(ref, name, 900, { onMount: true })`; `<a className="pill ghost sm" href="#vault" data-open-tool={name} onClick={() => onOpenTool(name)}>`. `Banner` takes an optional `onOpenTool` prop too. Returns `null` when there's no banner. |
| `Tabs` | `tabsHtml` 1130–1134 | `null` when fewer than 2 tabs (the `log` tab is always appended: `allTabs`, line 1129). Button text: `{t.label}{t.count != null ? <>{" "}<span className="n">{t.count}</span></> : null}`. `aria-selected={String(run.tab === t.id)}`. `useTabIndicator(ref, run.tab, \`${run.id}\`)`. |
| `Bench` | `renderBench` 1086–1104, `sigHtml` 1105, `setActions` 1110–1114 | returns a fragment (the `<main className="bench">` wrapper is App's). Rail: `<div className={\`rail ${live ? "running" : "done"}\`} id="b-rail" aria-hidden="true"><i style={{ width: \`${railPercent(run)}%\` }}></i></div>`. `<div className="stack" style={{ gap: 16 }}>`. Caption: `<p className="caption" id="b-cap" dangerouslySetInnerHTML={{ __html: run.caption || "" }} />`. Signature: `{sig.name}<span>({sig.args}){sig.ret ? \` -> ${sig.ret}\` : ""}</span>` or `run.title`. `#b-act` holds the Stop button while `running`/`waiting`. `#b-panel` is `<div id="b-panel" className="stack" ref={panelRef}>{panel}</div>` with `useRestartAnimation(panelRef, "panel-in", run.tab)`. |
| `Idle` | `renderIdle` 1060–1078 | `<h1 id="idle-h">` via `dangerouslySetInnerHTML` + `useScramble(ref, COPY.idle.heading, 1000, { onMount: true })`; `<span id="idle-count">` via `dangerouslySetInnerHTML` + `useCountUp`. Suggestion cards from `SUGGESTIONS` with `data-suggest={i}`. The setup line: `<p className="setup-line">{fill(COPY.idle.setup, { keys: weatherKeySet ? COPY.idle.keysWithWeather : COPY.idle.keysWithout, state: askExec ? COPY.idle.on : COPY.idle.off })}<a href="#settings">{COPY.idle.settings}</a></p>`, appended inside `.try-wrap` (line 1075). The image: `src="assets/hero-mark.webp" alt="" width="1200" height="480"`. |

`Strip`'s link needs its own component, because the `flow` class must survive later class changes (the Task 6 rule):

```tsx
function StripLink({ lk, swap, lit, retrying, flows, mountFlows }: {
  lk: string; swap: boolean; lit: boolean; retrying: boolean; flows: number; mountFlows: number;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useRestartAnimation(ref, "flow", flows);
  // The reference adds "flow" on each flow() and keeps it until the bench is re-rendered (line 1038).
  const flowed = flows > mountFlows;
  const cls = `link${swap ? " swap" : ""}${lit ? " lit" : ""}${flowed ? " flow" : ""}${swap && retrying ? " retrying" : ""}`;
  return <li ref={ref} className={cls} data-link={lk} aria-hidden="true"></li>;
}
```

In `Strip`, capture the flow counts at mount (`const mountFlows = useRef(run.flows ?? {})`) and pass `mountFlows.current[lk] ?? 0`. App keys the bench by `${run.id}:${benchKey}` (Task 15), so a re-render of the bench (the reference's `renderBench`) remounts the strip and clears `flow`, as in the reference.

- [ ] **Step 1: Write the failing test** `frontend/src/components/workbench/frame.test.tsx`

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { allFlows, expectParity, fixtureCase, flow } from "../../test/parity";
import { asRun } from "../../test/parity/runs";
import { innerOf, ssr } from "../../test/ssr";
import { Banner } from "./Banner";
import { Bench } from "./Bench";
import { Idle } from "./Idle";
import { Strip } from "./Strip";
import { Tabs } from "./Tabs";

const noop = () => {};
const pureSnaps = () => allFlows().flatMap((f) => Object.entries(flow(f).snaps).filter(([, s]) => s.pure).map(([n, s]) => [`${f}/${n}`, s] as const));

test.each(["strip/forge-pending", "strip/forge-planner-active", "strip/forge-retry", "strip/forge-failed", "strip/vault", "strip/primitive-waiting", "strip/chat", "strip/stopped"])(
  "%s",
  (id) => {
    const c = fixtureCase(id);
    expectParity(innerOf(ssr(<Strip run={asRun(c.state.run)} />)), c.html!);
  },
);

test.each(["banner/saved", "banner/removed", "banner/none"])("%s", (id) => {
  const c = fixtureCase(id);
  expectParity(ssr(<Banner banner={asRun(c.state.run).banner} />), c.html!);
});

test.each(["tabs/log-only", "tabs/forge"])("%s", (id) => {
  const c = fixtureCase(id);
  expectParity(ssr(<Tabs run={asRun(c.state.run)} onSelect={noop} />), c.html!);
});

test("strip, banner and tabs match every flow checkpoint", () => {
  const snaps = pureSnaps();
  expect(snaps.length).toBeGreaterThan(30);
  for (const [, s] of snaps) {
    const run = asRun(s.run);
    expectParity(innerOf(ssr(<Strip run={run} />)), s.pure!.strip);
    expectParity(ssr(<Banner banner={run.banner} />), s.pure!.banner);
    expectParity(ssr(<Tabs run={run} onSelect={noop} />), s.pure!.tabs);
  }
});

/** Empties #b-panel: the panel itself is Task 9's and is compared there. */
const withoutPanel = (html: string) => {
  const t = document.createElement("template");
  t.innerHTML = html;
  t.content.querySelector("#b-panel")!.innerHTML = "";
  return t.innerHTML;
};

test.each(["bench/planning", "bench/chat-done"])("%s (renderBench)", (id) => {
  const c = fixtureCase(id);
  const run = asRun(c.state.run);
  const html = ssr(<Bench run={run} live={c.state.live as boolean} panel={null} onTab={noop} onStop={noop} onOpenTool={noop} />);
  expectParity(withoutPanel(html), withoutPanel(c.html!));
});

test.each(["idle/default", "idle/key-set-ask-off"])("%s (renderIdle)", (id) => {
  const c = fixtureCase(id);
  const s = c.state as { count: number; env: Record<string, string>; askExec: boolean };
  expectParity(ssr(<Idle count={s.count} weatherKeySet={!!s.env.OPENWEATHERMAP_API_KEY} askExec={s.askExec} onSuggest={noop} />), c.html!);
});

test("tabs select, stop and suggestions call back", () => {
  const onTab = vi.fn();
  const run = asRun(fixtureCase("tabs/forge").state.run);
  render(<Tabs run={run} onSelect={onTab} />);
  fireEvent.click(screen.getByRole("tab", { name: /Code/ }));
  expect(onTab).toHaveBeenCalledWith("code");
  const onSuggest = vi.fn();
  render(<Idle count={40} weatherKeySet={false} askExec onSuggest={onSuggest} />);
  fireEvent.click(screen.getByText(/Build a Caesar cipher tool/));
  expect(onSuggest).toHaveBeenCalledWith(0);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/workbench/frame.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Transcribe the five components** per the table and the `StripLink` code above. Keep every class name, attribute and piece of text literal, taking text from `COPY`.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/components/workbench/frame.test.tsx && npm run lint && npm run typecheck`
Expected: PASS. A parity failure prints both normalised strings: fix the component until they are equal. Never change a fixture.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workbench
git commit -m "[Feat]: Add the bench frame: strip, banner, tabs, bench head and idle bench"
```

---

### Task 9: Bench panels

**Files:**
- Create: `frontend/src/components/workbench/panels/CodePanel.tsx`, `TestsPanel.tsx`, `AttemptsPanel.tsx`, `CallPanel.tsx`, `HistoryPanel.tsx`, `LogPanel.tsx`, `Earlier.tsx`, `Panel.tsx`
- Test: `frontend/src/components/workbench/panels/panels.test.tsx`

**Interfaces:**
- Consumes: `highlight` (Task 3), `COPY`, `fill` (Task 4), `PRUNE_AT` (Task 3), `fmtTime` (Task 3), `TickIcon`, `XIcon` (Task 7), `useScramble` (Task 6).
- Produces:
  - `Panel(props: PanelProps)`: `panelHtml` (line 1156). `PanelProps = { run: Run; isCurrent: boolean; tool: VaultTool | undefined; earlier: EarlierData | null; onAsk(q: string): void; onOpenTool(name: string): void; onRun(n: number): void }`.
  - `EarlierData = { heading: string; runs: Run[] }` (runs already filtered and in display order).
  - `earlierData(runs: Run[], except: Run | null, viewSession: boolean): EarlierData | null`: `earlierHtml`'s list logic (line 1268): drop `except`, drop running/waiting runs, reverse, heading `COPY.log.inSession` when reading an old session, else `COPY.log.earlier`; `null` when empty.
  - The seven panel components, each taking only what it renders.

Transcription map:

| Component | Reference | Notes |
|---|---|---|
| `CodePanel({ code, codeScroll })` | `codeHtml` 1168–1180, scroll in `renderPanel` 1154 | `highlight(code.lines).slice(0, code.shown)`; each row `<div className={\`code-row${changed}\`} data-ln={n}><span className="ln">{n}</span><span className="tx" dangerouslySetInnerHTML={{ __html: hl[i] \|\| " " }} /></div>`; the typing caret row while `shown < lines.length`; the note `<p className="code-note"><i aria-hidden="true"></i>` + note HTML (use `dangerouslySetInnerHTML` on a wrapper-less fragment: render `<p className="code-note" dangerouslySetInnerHTML={{ __html: '<i aria-hidden="true"></i>' + code.note }} />`). `.code-body` has `tabIndex={0}` and `aria-label={COPY.code.aria}`. After each render, a layout effect scrolls `.code-body`: `"bottom"` → `scrollTop = scrollHeight`; a number → the row `[data-ln=n]` to the middle (line 1154). |
| `TestsPanel({ runN, tests, smoke, attempts })` | `testsHtml` 1181–1200 | `drawn`/`flashed`: a module-level `Set<string>` keyed `${runN}:${attempt}:${name}` records what earlier renders drew. A passed test renders `<TickIcon done={x.drawn \|\| drawnSet.has(k)} />passed`; a failed one `<XIcon />failed` and `just-failed` unless `x.flashed \|\| flashedSet.has(k)`. After the commit (`useEffect`), add the passed and failed keys to the sets. This is the reference's `x.drawn = true` / `x.flashed = true` (lines 1188–1191) without a store write, so the draw animation isn't cut short. Inline styles become style objects (`style={{ gap: 6, padding: "0 4px" }}` etc.). The note is `fill(COPY.tests.note, { s: 10 })`. |
| `AttemptsPanel({ attempts })` | `attemptsHtml` 1201–1205 | `detail` is text (`esc`), shown with `white-space` from CSS. |
| `CallPanel({ call, onAsk, onOpenTool })` | `callHtml` 1206–1229 | `c.pending` is HTML (it can hold the caret span): `dangerouslySetInnerHTML`. The health paragraph `h.text` is HTML. The meter has `role="img"` and `aria-label={fill(COPY.call.meter, { s: h.streak, p: PRUNE_AT })}`. The retry button has `data-ask={h.retry.q}` and calls `onAsk(q)`. |
| `HistoryPanel({ tool })` | `historyHtml` 1230–1234 | `fmtTime(t.created)`, `fmtTime(t.last)` (`Never` when empty). |
| `LogPanel({ run, isCurrent, earlier, onRun })` | `logPanelHtml` 1239–1246, `logLineHtml` 1273–1278 | caption `isCurrent ? COPY.log.thisRun : fill(COPY.log.runN, { n: run.n })`; `#term-status` class `gold`/`muted`. A `cmd` line renders two siblings: `<div className="cmd">{COPY.log.prompt}{text}{typing && caret}</div><div className="gap"></div>`. An `ln` line: `<div className={\`ln${tone ? " " + tone : ""}${fresh ? " fresh" : ""}\`}><em …/><span className="lt" …/>{caret}</div>`, where `em` and `.lt` use `dangerouslySetInnerHTML` + `useScramble` (label 320 ms on mount when `fresh`; text 480 ms on mount when `fresh` and tone `g`), as in `log()` (lines 1286–1289). The caret: `<span className="caret" aria-hidden="true" style={{ marginLeft: 4 }}></span>`. A `sub` line: `<div className="ln sub">{text}</div>`. Key each line by `line.key ?? index`. |
| `Earlier({ data, onRun })` | `earlierHtml` 1268–1272 | buttons `data-run={r.n}` call `onRun(r.n)`; summary class `s gold` when `summaryGold`. |
| `Panel` | `panelHtml` 1156–1167 | switch on `run.tab`; `"answer"` renders nothing (the reference never sets `answerPanel`). |

- [ ] **Step 1: Write the failing test** `frontend/src/components/workbench/panels/panels.test.tsx`

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { allFlows, expectParity, fixtureCase, flow } from "../../../test/parity";
import { asRun } from "../../../test/parity/runs";
import { ssr } from "../../../test/ssr";
import type { VaultTool } from "../../../store/types";
import { earlierData, Panel } from "./Panel";

const noop = () => {};

const CASES = [
  "panel/code-typing", "panel/code-changed", "panel/tests-none", "panel/tests-mixed", "panel/tests-smoke-prev",
  "panel/attempts-none", "panel/attempts", "panel/call-resolving", "panel/call-result-record", "panel/call-error-health",
  "panel/call-no-args", "panel/call-pending-approval", "panel/history", "panel/history-gone",
];

test.each(CASES)("%s", (id) => {
  const c = fixtureCase(id);
  const run = asRun(c.state.run);
  const tool = (c.state.tool as VaultTool | null) ?? undefined;
  expectParity(ssr(<Panel run={run} isCurrent={false} tool={tool} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />), c.html!);
});

test("every flow checkpoint's panel matches panelHtml()", () => {
  let n = 0;
  for (const f of allFlows()) {
    for (const s of Object.values(flow(f).snaps)) {
      if (!s.pure) continue;
      const run = asRun(s.run);
      const tools = s.vault as VaultTool[];
      const others = s.sessionRuns.map(asRun);
      const html = ssr(
        <Panel
          run={run}
          isCurrent={s.isCurrent}
          tool={tools.find((t) => t.name === run.toolName)}
          earlier={earlierData(others, run, s.viewSession)}
          onAsk={noop}
          onOpenTool={noop}
          onRun={noop}
        />,
      );
      expectParity(html, s.pure.panel);
      n++;
    }
  }
  expect(n).toBeGreaterThan(30);
});

test("the retry button asks again and Earlier opens a run", () => {
  const onAsk = vi.fn();
  const c = fixtureCase("panel/call-error-health");
  render(<Panel run={asRun(c.state.run)} isCurrent={false} tool={undefined} earlier={null} onAsk={onAsk} onOpenTool={noop} onRun={noop} />);
  fireEvent.click(screen.getByText("Ask again with shift 7"));
  expect(onAsk).toHaveBeenCalledWith('Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"');
});

test("a test drawn once keeps the done tick on the next render", () => {
  const c = fixtureCase("panel/tests-mixed");
  const run = asRun(c.state.run);
  const { rerender, container } = render(<Panel run={run} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  const next = { ...run, tests: { ...run.tests!, list: run.tests!.list.map((t, i) => (i === 2 ? { ...t, state: "passed" as const } : t)) } };
  rerender(<Panel run={next} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  const ticks = [...container.querySelectorAll("svg.tick")].map((s) => s.getAttribute("class"));
  expect(ticks).toEqual(["tick done", "tick"]);
  expect(container.querySelector("li.failed")!.className).toBe("failed");
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/workbench/panels`
Expected: FAIL (module not found).

- [ ] **Step 3: Transcribe the panels** per the map. Export `earlierData` from `Panel.tsx`:

```ts
export function earlierData(runs: Run[], except: Run | null, viewSession: boolean): EarlierData | null {
  const list = runs.filter((r) => r.n !== except?.n && r.status !== "running" && r.status !== "waiting");
  if (!list.length) return null;
  return { heading: viewSession ? COPY.log.inSession : COPY.log.earlier, runs: list.slice().reverse() };
}
```

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/components/workbench && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workbench/panels
git commit -m "[Feat]: Add the code, tests, attempts, call, history and run log panels"
```

---

### Task 10: Conversation column and dialogs

**Files:**
- Create: `frontend/src/components/workbench/Message.tsx`, `Conversation.tsx`, `Composer.tsx`
- Create: `frontend/src/components/dialogs/ModalRoot.tsx`, `ApprovalDialog.tsx`, `KeyDialog.tsx`, `ReaderDialog.tsx`
- Test: `frontend/src/components/workbench/conversation.test.tsx`, `frontend/src/components/dialogs/dialogs.test.tsx`

**Interfaces:**
- Consumes: `wrapWordsHtml` (Task 3), `COPY`, `fill`, `SUGGESTIONS` (Task 4), `useScramble`, `useFocusTrap` (Task 6), `highlight` (Task 3).
- Produces:
  - `Message({ msg, showPast, viewingN, onRun, onSuggest })`: one `.msg`.
  - `Conversation(props: ConversationProps)`, `ConversationProps = { title: string; animateTitle: boolean; readOnly: { name: string; started: string } | null; messages: Message[]; empty: boolean; busy: boolean; viewingN: number | null; live: string; composer: ComposerProps; onNew(): void; onBack(): void; onRun(n: number): void; onSuggest(i: number): void }`. Renders `<section className="col convo" aria-label="Conversation">` (lines 630–646).
  - `Composer(props: ComposerProps)`, `ComposerProps = { value: string; disabled: boolean; hint: string; busy: boolean; onChange(v: string): void; onSubmit(): void; inputRef?: Ref<HTMLTextAreaElement> }`.
  - `ModalRoot({ dialog, demo, onApproval, onKey, onClose })` (`demo: boolean` adds the key dialog's demo footer sentence) renders the `.scrim` inside App's `#modal-root`; `onApproval(action: "yes" | "no" | "cancel")`, `onKey(r: { action: "save"; value: string } | { action: "skip" } | { action: "cancel" })`, `onClose()` (reader).
  - `ApprovalDialog({ tool, code, onAnswer })`, `KeyDialog({ toolName, envVar, service, demo, onAnswer })`, `ReaderDialog({ name, lines, onClose })`.

Transcription map:

| Component | Reference | Notes |
|---|---|---|
| `Message` (you) | `addYou` 936–941 | `className={\`msg you${past && showPast ? " past" : ""}\`}`; `<p>{text}</p>` (text, never HTML). |
| `Message` (talos) | `addTalos` 942–970, `say` 950–960, `chip` 961–965, `stop` 967, submit's run link 1481, `markRunLinks` 2232–2234, `sessionHtml` 2229–2231 | order: `who`; the thinking row while `html == null && stopNote == null` (`<span className="tt" key={status}>` so a new status is a new element, restarting its fade, as `status()` replaces it, line 949); the answer `<p>`; the note `<p className="note" dangerouslySetInnerHTML>`; chips `<span className={\`chip ${kind}\`}><i aria-hidden="true"></i>{text}</span>`; the inline suggestions `<div className="suggest-inline">` with `data-suggest` buttons (line 1951); the stop note `<p className="note">{stopNote}</p>`; the run link `<button type="button" className="run-link" data-run={runN} aria-current={String(viewingN === runN)}>`. |
| answer `<p>` | `say()` + `wrapWords` | when `msg.wrap`: `const [initialOn] = useState(msg.wordsOn)`; `__html = useMemo(() => wrapWordsHtml(msg.html, initialOn).html, [msg.html])`; a layout effect adds `on` to the first `msg.wordsOn` `.wd` spans (so the CSS transition runs on the same element, as `classList.add("on")` does). When `!msg.wrap` (seeded transcripts): `dangerouslySetInnerHTML={{ __html: msg.html }}`. |
| `Conversation` | lines 631–644, `renderEmptyConvo` 987–989, `openSession` 2185, `updateComposer` 1507–1514, `scrollMsgs` 971 | head: `<h2 id="session-name"><span className="scr" id="session-title" ref dangerouslySetInnerHTML={{ __html: esc(title) }} /></h2>` with `useScramble(ref, title, 600)` only when `animateTitle`; `#new-session` (`hidden={!!readOnly}`, `disabled={busy}`) and `#back-session` (`hidden={!readOnly}`). `#msgs`: when `readOnly`, first `<p className="viewing-note"><span>{fill(COPY.convo.readOnly, { name, time: fmtTime(started) })}</span></p>`; when `empty`, only `<p className="empty-convo">`. Scroll `#msgs` to the bottom after each render when not reading an old session, to the top when one opens. `<div className="sr" aria-live="polite" id="live">{live}</div>`. |
| `Composer` | lines 638–645, `setBusy` 1501–1506, keydown 2093 | `<form className="composer" id="composer" onSubmit>`; `<label htmlFor="ask">`; `<textarea id="ask" rows={3} placeholder=… value disabled>`; Enter without Shift (and not composing) submits; `#composer-hint`; `#send` shows `COPY.convo.working` while `busy`. |
| `ModalRoot` | `openDialog` 1341–1367 | `<div className="scrim" id="scrim">{dialog}</div>`; reader closes on a click on the scrim itself (line 2038). |
| `ApprovalDialog` | `approvalDialog` 1368–1390 | `useFocusTrap(ref, { onEscape: () => onAnswer("cancel"), initialFocus: '[data-d="no"]' })`. The footer link `href="#settings" data-d="settings"` answers `"no"` (line 1386) and lets the hash change happen. |
| `KeyDialog` | `keyDialog` 1391–1420 | `<form className="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-t" noValidate onSubmit>`; the error text is local state; empty submit sets it and refocuses the input; `demo` adds `COPY.key.footDemo` after `COPY.key.foot` (part B passes `false`). Initial focus `#dlg-key`. |
| `ReaderDialog` | `readerDialog` 2016–2040, `codeRows` 2015 | Copy: `navigator.clipboard.writeText(lines.join("\n"))` → `Copied`; on failure select the code body and show `Selected, press Ctrl+C`; back to `Copy` after 1800 ms. Initial focus `[data-r="close"]`. |

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/workbench/conversation.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { expectParity, fixtureCase } from "../../test/parity";
import { ssr } from "../../test/ssr";
import { seedSessions } from "../../demo/seeds";
import { freshVault } from "../../store/vaultOps";
import { VAULT_ROWS } from "../../demo/data";
import type { TalosMessage } from "../../store/types";
import { Message } from "./Message";

const noop = () => {};
const talos = (p: Partial<TalosMessage>): TalosMessage => ({
  kind: "talos", key: "t", runN: 6, status: "Working on it", html: null, wrap: true, wordsOn: 0, note: null, chips: [],
  suggest: false, stopNote: null, runLink: false, past: false, ...p,
});

test("a You message escapes its text (addYou)", () => {
  const c = fixtureCase("convo/you");
  expectParity(ssr(<Message msg={{ kind: "you", key: "y", text: c.state.text as string, past: false }} showPast viewingN={null} onRun={noop} onSuggest={noop} />), c.html!);
});

test("a Talos message thinking (addTalos + status)", () => {
  const c = fixtureCase("convo/talos-thinking");
  expectParity(ssr(<Message msg={talos({ status: c.state.status as string })} showPast viewingN={null} onRun={noop} onSuggest={noop} />), c.html!);
});

test("a seeded transcript (sessionHtml)", () => {
  const c = fixtureCase("convo/seeded-fib");
  const fib = seedSessions(freshVault(VAULT_ROWS)).sessions[0]!;
  const html = fib.messages.map((m) => ssr(<Message msg={m} showPast viewingN={null} onRun={noop} onSuggest={noop} />)).join("");
  // sessionHtml() has no aria-current on its run links until markRunLinks() runs; the app always marks them.
  expectParity(html.replace(/ aria-current="false"/g, ""), c.html!);
});

test("answer words fade in on the same elements", () => {
  const html = 'It decrypts to <span class="mono">TALOS AGENT</span>.';
  const { container, rerender } = render(<Message msg={talos({ status: null, html, wordsOn: 0 })} showPast viewingN={null} onRun={noop} onSuggest={noop} />);
  const first = container.querySelector(".wd")!;
  expect(first.className).toBe("wd");
  rerender(<Message msg={talos({ status: null, html, wordsOn: 2 })} showPast viewingN={null} onRun={noop} onSuggest={noop} />);
  expect(container.querySelector(".wd")).toBe(first);
  expect([...container.querySelectorAll(".wd")].map((w) => w.className)).toEqual(["wd on", "wd on", "wd", "wd", "wd", "wd"]);
});
```

`frontend/src/components/dialogs/dialogs.test.tsx`:

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import { SOURCES } from "../../demo/data";
import { expectParity, fixtureCase, snap } from "../../test/parity";
import { innerOf, ssr } from "../../test/ssr";
import type { DialogReq } from "../../store/types";
import { ModalRoot } from "./ModalRoot";

const noop = () => {};
const modal = (dialog: DialogReq) => ssr(<ModalRoot dialog={dialog} demo onApproval={noop} onKey={noop} onClose={noop} />);

test.each([["dialog/approval-python", "python_exec"], ["dialog/approval-shell", "shell_exec"]] as const)("%s", (id, tool) => {
  const c = fixtureCase(id);
  expectParity(modal({ kind: "approval", runId: "r", tool, code: c.state.code as string }), c.html!);
});

test("dialog/key and dialog/reader-caesar", () => {
  const k = fixtureCase("dialog/key");
  expectParity(modal({ kind: "key", runId: "r", toolName: "get_current_temperature", envVar: "OPENWEATHERMAP_API_KEY", service: "OpenWeatherMap" }), k.html!);
  const r = fixtureCase("dialog/reader-caesar");
  expectParity(modal({ kind: "reader", name: "caesar_cipher", lines: SOURCES.caesar_cipher! }), r.html!);
});

test("Escape cancels and restores focus", () => {
  const before = document.createElement("button");
  document.body.append(before);
  before.focus();
  const onApproval = vi.fn();
  const { unmount } = render(<ModalRoot dialog={{ kind: "approval", runId: "r", tool: "python_exec", code: "print(1)" }} demo onApproval={onApproval} onKey={noop} onClose={noop} />);
  expect(document.activeElement).toBe(screen.getByText("Don't run"));
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(onApproval).toHaveBeenCalledWith("cancel");
  unmount();
  expect(document.activeElement).toBe(before);
  before.remove();
});

test("approval answers; the Settings link declines", () => {
  const onApproval = vi.fn();
  render(<ModalRoot dialog={{ kind: "approval", runId: "r", tool: "python_exec", code: "print(1)" }} demo onApproval={onApproval} onKey={noop} onClose={noop} />);
  fireEvent.click(screen.getByText("Run code"));
  fireEvent.click(screen.getByText("Ask before running code"));
  expect(onApproval.mock.calls).toEqual([["yes"], ["no"]]);
});

test("the key dialog asks for a key before saving, and skips", () => {
  const onKey = vi.fn();
  const { container } = render(<ModalRoot dialog={{ kind: "key", runId: "r", toolName: "get_current_temperature", envVar: "OPENWEATHERMAP_API_KEY", service: "OpenWeatherMap" }} demo onApproval={noop} onKey={onKey} onClose={noop} />);
  fireEvent.click(screen.getByText("Save key"));
  expect(onKey).not.toHaveBeenCalled();
  expectParity(container.innerHTML, innerOf(snap("weather-save", "dialog-error").regions["#modal-root"]!, "#modal-root"));
  expect(document.activeElement).toBe(container.querySelector("#dlg-key"));
  fireEvent.change(container.querySelector("#dlg-key")!, { target: { value: "  owm-key  " } });
  fireEvent.click(screen.getByText("Save key"));
  fireEvent.click(screen.getByText("Skip"));
  expect(onKey.mock.calls).toEqual([[{ action: "save", value: "owm-key" }], [{ action: "skip" }]]);
});

test("the reader copies, falls back, and closes on a click outside", async () => {
  vi.useFakeTimers();
  const onClose = vi.fn();
  const writeText = vi.fn().mockRejectedValue(new Error("denied"));
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const { container } = render(<ModalRoot dialog={{ kind: "reader", name: "caesar_cipher", lines: ["a", "b"] }} demo onApproval={noop} onKey={noop} onClose={onClose} />);
  await act(async () => void fireEvent.click(screen.getByText("Copy")));
  expect(writeText).toHaveBeenCalledWith("a\nb");
  expect(screen.getByText("Selected, press Ctrl+C")).toBeInTheDocument();
  act(() => void vi.advanceTimersByTime(1800));
  expect(screen.getByText("Copy")).toBeInTheDocument();
  fireEvent.click(container.querySelector("#scrim")!);
  expect(onClose).toHaveBeenCalled();
  vi.useRealTimers();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/components/workbench/conversation.test.tsx src/components/dialogs`
Expected: FAIL (modules not found).

- [ ] **Step 3: Transcribe the components** per the map.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/components && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workbench/Message.tsx frontend/src/components/workbench/Conversation.tsx frontend/src/components/workbench/Composer.tsx frontend/src/components/workbench/conversation.test.tsx frontend/src/components/dialogs
git commit -m "[Feat]: Add the conversation column and the approval, key and reader dialogs"
```

---

### Task 11: Vault view

**Files:**
- Create: `frontend/src/components/vault/VaultView.tsx`, `VaultTable.tsx`, `VaultDetail.tsx`, `CodeRows.tsx`
- Test: `frontend/src/components/vault/vault.test.tsx`

**Interfaces:**
- Consumes: `vaultRows`, `findTool` (Task 5), `argNames`, `fmtClock`, `fmtShort`, `fmtTime`, `sameDay`, `esc` (Task 3), `highlight` (Task 3), `COPY`, `fill` (Task 4), `PRUNE_AT`, `useRestartAnimation` (Task 6).
- Produces:
  - `VaultView(props: VaultViewProps)`: the `.vault` grid (lines 652–679). `VaultViewProps = { tools: VaultTool[]; filter: "all" | "web" | "failed"; query: string; selected: string | null; stagger: boolean; renderKey: number; confirmRemove: string | null; source: string[] | null; onQuery(q: string): void; onFilter(f): void; onSelect(name: string): void; onFallbackSelect(name: string | null): void; onRead(name: string): void; onUse(name: string): void; onRemove(name: string): void; onOpenTool?(name: string): void }`.
  - `effectiveSelected(tools, rows, selected): string | null`: `renderVault`'s fallback (line 1971): keep `selected` if it's in the vault, else the first row's name, else `null`.
  - `CodeRows({ lines })`: `codeRows` (line 2015), shared with `ReaderDialog`.

Transcription map: static parts lines 653–677; `renderVault` 1963–1981 (lede, counts, `aria-pressed` on the filters, rows, the empty row `<tr><td colSpan={4} className="v-empty">`, `Showing r of n`); `renderDetail` 1984–2013 (`VaultDetail`). The reference adds `swap` on the first render and keeps it from then on (it only removes and re-adds it, line 1989), so render `<aside className="v-detail swap" id="v-detail" aria-label={COPY.vault.detailAria}>` and replay it with `useRestartAnimation(ref, "swap", tool?.name ?? null)` when the selection changes (`S.detailShown`). Rows: `className={\`${t.fresh ? "fresh" : ""}${stagger ? " in" : ""}\`}` and `style={stagger ? { animationDelay: \`${Math.min(i, 14) * 22}ms\` } : undefined}`. Rows are keyed `${t.name}:${renderKey}`, so each `renderVault()` (a new `renderKey`) re-creates them and replays `rise`, as the reference's `innerHTML` rewrite does. The controller sets `stagger` and bumps `vaultRender` the way the reference calls `renderVault` (Task 15): staggered on entering the view and on a filter click; not staggered on a search, a row selection and a removal. The row click and the name button both select (lines 2111–2112, and the button gets focus). "Last failure" is `{COPY.vault.lastFailure}{t.lastFailAt ? ", " + fmtTime(t.lastFailAt) : ""}`. The remove button shows `fill(COPY.vault.confirm, { name })` when `confirmRemove === name` and has `data-confirm="1"` then (line 2127). The source preview (when `source`) uses `CodeRows`; without a source, the `COPY.vault.noSource` paragraph with `style={{ margin: 0, fontSize: 13 }}`. The search input is controlled (`value={query}`) and calls `onQuery` on input.

Call `onFallbackSelect(effective)` from an effect when `effective !== selected`, so the store keeps the fallback as the reference does.

- [ ] **Step 1: Write the failing test** `frontend/src/components/vault/vault.test.tsx`

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { SOURCES } from "../../demo/data";
import { expectParity, fixtureCase, snap } from "../../test/parity";
import { innerOf, ssr } from "../../test/ssr";
import type { VaultTool } from "../../store/types";
import { VaultView, type VaultViewProps } from "./VaultView";

const noop = () => {};
const view = (s: Record<string, unknown>, extra: Partial<VaultViewProps> = {}) => (
  <VaultView
    tools={s.tools as VaultTool[]}
    filter={(s.filter as VaultViewProps["filter"]) ?? "all"}
    query={(s.query as string) ?? ""}
    selected={(s.selected as string | null) ?? null}
    stagger={!!s.stagger}
    renderKey={0}
    confirmRemove={null}
    source={(s.source as string[] | undefined) ?? null}
    onQuery={noop} onFilter={noop} onSelect={noop} onFallbackSelect={noop} onRead={noop} onUse={noop} onRemove={noop}
    {...extra}
  />
);

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
});
afterAll(() => vi.useRealTimers());

test.each(["vault/default", "vault/fresh-selected", "vault/web", "vault/failed-query", "vault/empty"])("%s", (id) => {
  const c = fixtureCase(id);
  // vault/default: the reference falls back to the first row because caesar_cipher isn't in the vault yet.
  expectParity(ssr(view(c.state)), c.html!);
});

test("the caesar-forge vault page (fresh tool with its source)", () => {
  const s = snap("caesar-forge", "vault");
  const tools = s.vault as VaultTool[];
  expectParity(ssr(view({ tools, selected: "caesar_cipher", stagger: true, source: SOURCES.caesar_cipher })), innerOf(s.regions["#view-vault"]!, "#view-vault"));
});

test("the remove button asks first", () => {
  const onRemove = vi.fn();
  const s = snap("vault-browse", "confirm");
  const tools = s.vault as VaultTool[];
  expectParity(ssr(view({ tools, filter: "failed", selected: "flatten_json" }, { confirmRemove: "flatten_json" })), innerOf(s.regions["#view-vault"]!, "#view-vault"));
  render(view({ tools, selected: "flatten_json" }, { onRemove }));
  fireEvent.click(screen.getByText("Remove from vault"));
  expect(onRemove).toHaveBeenCalledWith("flatten_json");
});

test("search, filters, selection, read and use call back", () => {
  const onQuery = vi.fn();
  const onFilter = vi.fn();
  const onSelect = vi.fn();
  const onUse = vi.fn();
  const tools = fixtureCase("vault/default").state.tools as VaultTool[];
  render(view({ tools, selected: "hex_to_rgb" }, { onQuery, onFilter, onSelect, onUse }));
  fireEvent.input(screen.getByPlaceholderText("Search by name or keyword"), { target: { value: "hex" } });
  fireEvent.click(screen.getByText("Uses the web"));
  fireEvent.click(screen.getByText("slugify"));
  fireEvent.click(screen.getByText("Use in a question"));
  expect(onQuery).toHaveBeenCalledWith("hex");
  expect(onFilter).toHaveBeenCalledWith("web");
  expect(onSelect).toHaveBeenCalledWith("slugify");
  expect(onUse).toHaveBeenCalledWith("hex_to_rgb");
});
```

The flow snapshots for `vault-browse` (`search`, `empty`, `web`, `failed`, `detail`, `removed`) are covered end to end in Task 16.

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/vault`
Expected: FAIL (module not found).

- [ ] **Step 3: Transcribe** per the map. Move `codeRows` into `CodeRows.tsx` and use it from `ReaderDialog` too (replace Task 10's local copy).

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/components && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/vault frontend/src/components/dialogs/ReaderDialog.tsx
git commit -m "[Feat]: Add the vault view with search, filters, detail and the source preview"
```

---

### Task 12: Sessions and Settings views

**Files:**
- Create: `frontend/src/components/sessions/SessionsView.tsx`, `SessionCard.tsx`, `frontend/src/components/settings/SettingsView.tsx`
- Test: `frontend/src/components/sessions/sessions.test.tsx`, `frontend/src/components/settings/settings.test.tsx`

**Interfaces:**
- Consumes: `fmtClock`, `fmtDay`, `sameDay` (Task 3), `COPY`, `fill` (Task 4), `PRUNE_AT`.
- Produces:
  - `SessionsView({ sessions, runsById, curId, onOpen })`: `renderSessions` (line 2257) into `.sessions-in`'s content. `sessions: SessionRec[]`, `runsById: Record<string, Run>`.
  - `SessionCard({ session, runs, index, isCur, onOpen })`: `sessCard` (line 2270). `style={{ animationDelay: \`${index * 60}ms\` }}`.
  - `SettingsView({ askExec, env, model, onToggleAsk })`: `renderSettings` (line 2043) into `.settings-in`'s content. The switch: `<button type="button" className="switch" role="switch" aria-checked={String(askExec)} aria-labelledby="ask-lbl" id="ask-switch">`; after a toggle, focus returns to it (line 2131).

Both render fragments: App (Task 15) provides `<div className="sessions"><div className="sessions-in" id="sessions-in">` and `<div className="settings"><div className="settings-in" id="settings-in">`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/sessions/sessions.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { seedSessions } from "../../demo/seeds";
import { VAULT_ROWS } from "../../demo/data";
import { freshVault } from "../../store/vaultOps";
import { expectParity, fixtureCase, snap } from "../../test/parity";
import { asRun } from "../../test/parity/runs";
import { innerOf, ssr } from "../../test/ssr";
import type { Run, SessionRec } from "../../store/types";
import { SessionsView } from "./SessionsView";

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
});
afterAll(() => vi.useRealTimers());

const seeded = () => seedSessions(freshVault(VAULT_ROWS));
const current = (runs: Run[] = [], name = "Session 1"): SessionRec => ({ id: "s1", name, started: "2026-09-30T12:00", live: true, runIds: runs.map((r) => r.id), messages: [] });

test("sessions/boot (seeds plus the empty current session)", () => {
  const { sessions, runs } = seeded();
  const byId = Object.fromEntries(runs.map((r) => [r.id, r]));
  expectParity(ssr(<SessionsView sessions={[...sessions, current()]} runsById={byId} curId="s1" onOpen={() => {}} />), fixtureCase("sessions/boot").html!);
});

test("escapes queries (unknown-html flow)", () => {
  const s = snap("unknown-html", "sessions");
  const { sessions, runs } = seeded();
  const mine = s.sessionRuns.map(asRun).map((r) => ({ ...r, id: `run-${r.n}` }));
  const byId = Object.fromEntries([...runs, ...mine].map((r) => [r.id, r]));
  const name = "Summarise <b>this</b> PDF &";
  expectParity(ssr(<SessionsView sessions={[...sessions, current(mine, name)]} runsById={byId} curId="s1" onOpen={() => {}} />), innerOf(s.regions["#view-sessions"]!, "#sessions-in"));
  expect(s.regions["#view-sessions"]).toContain("Summarise &lt;b&gt;this&lt;/b&gt; PDF &amp;");
});

test("Open and Continue call back with the session id", () => {
  const onOpen = vi.fn();
  const { sessions, runs } = seeded();
  render(<SessionsView sessions={[...sessions, current()]} runsById={Object.fromEntries(runs.map((r) => [r.id, r]))} curId="s1" onOpen={onOpen} />);
  fireEvent.click(screen.getAllByText("Open")[0]!);
  expect(onOpen).toHaveBeenCalledWith("seed-b64");
});
```

`frontend/src/components/settings/settings.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { expectParity, fixtureCase } from "../../test/parity";
import { ssr } from "../../test/ssr";
import { SettingsView } from "./SettingsView";

test.each(["settings/default", "settings/off-key"])("%s", (id) => {
  const c = fixtureCase(id);
  const s = c.state as { askExec: boolean; env: Record<string, string> };
  expectParity(ssr(<SettingsView askExec={s.askExec} env={s.env} model="deepseek/deepseek-v4.1-flash" onToggleAsk={() => {}} />), c.html!);
});

test("the switch toggles and keeps focus", () => {
  const onToggleAsk = vi.fn();
  render(<SettingsView askExec env={{}} model="m" onToggleAsk={onToggleAsk} />);
  const sw = screen.getByRole("switch");
  fireEvent.click(sw);
  expect(onToggleAsk).toHaveBeenCalled();
  expect(document.activeElement).toBe(sw);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/components/sessions src/components/settings`
Expected: FAIL (modules not found).

- [ ] **Step 3: Transcribe** `renderSessions` (2257–2269), `sessCard` (2270–2279) and `renderSettings` (2043–2075). Session groups: sort by `started` descending, keep only sessions with runs or the current one, group label `COPY.sessions.today` when `sameDay`, else `fmtDay`. The running index `k` for `animationDelay` counts across groups. Card marks: `failed`, `forged`, `reused` (`toolUsed` and not forged), or `""`. The "and N more" row: `<li className="muted" style={{ paddingLeft: 17 }}>`. The empty session: `<p className="sess-empty" style={{ margin: 0 }}>`. Settings key rows: the reference's five-row list (line 2044–2050) with the weather key's state from `env.OPENWEATHERMAP_API_KEY`; `<span className="mono" style={{ fontSize: 13 }}>`; the model `<dd className="mono" style={{ fontSize: 13 }}>`.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/components && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sessions frontend/src/components/settings
git commit -m "[Feat]: Add the sessions and settings views"
```

---

### Task 13: The event player

**Files:**
- Create: `frontend/src/transport/player.ts`
- Test: `frontend/src/transport/player.test.ts`

**Interfaces:**
- Consumes: the contract types (Task 5), `runOps`, `sessionOps`, `vaultOps`, `updateRun`, `Stores` (Task 5), `COPY`, `fill`, `healthText`, `removedSub`, `retryLabel` (Task 4), `fmtTime`, `nowIso` (Task 3), `still`, `wrapWordsHtml` (Task 3), `NUM_WORDS`, `PRUNE_AT`, `provisionalVariant` (Task 3).
- Produces (part B's live transport feeds the same class):
  - `dwell(ms: number, speed: number, still: boolean): number`: the reference's `wait()` scaling (line 929): `still ? Math.min(ms, 40) : ms / speed`.
  - `typingPlan(len: number): { step: number; ticks: number }`, `revealPlan(lines: number): { perTick: number; ticks: number }`.
  - `PACE` (fact animations), `MOMENTS`, `MIN_ACTIVE`, `momentAfter(e: RunEvent): number` (spec 04 §6 minimum dwells, live only).
  - `class Player { constructor(stores: Stores, opts: PlayerOptions); push: EventSink; abort(): void; dispose(): void }`, `PlayerOptions = { runId: string; sessionId: string; momentDwell: boolean; replay?: boolean; source?: (tool: string) => Promise<string[] | null> }`.

Event → store effect (each is the reference call named in spec 04 §6; the code below is normative):

| Event | Effect |
|---|---|
| `run.started` | new run with the provisional strip (ruling 3); You and Talos messages; `currentRunId`, `viewingRunId`, `busy` |
| `log.cmd` | type the command, 22 ms per step (`typeCmd`, line 1296) |
| `strip.set` | same variant: label, signature, title; else re-init keeping shared steps |
| `node.started` / `node.finished` | `setNode`; the Forger starting again after an attempt turns `retrying` on; the Forger finishing turns it off |
| `link.flow`, `caption`, `log.line`, `log.pop`, `log.status`, `talos.status` | `flow`, `setCaption`, `log`, pop, `logStatus` + `logTone`, the spinner text. `log.line execute running` also sets the call's pending text to `running` + caret (line 1822) |
| `forge.code` | attempt 1: tabs, attempt entry, reveal at 24 ms per tick; later attempts: replace lines, `changed`, `flash`, scroll to the changed line |
| `forge.tests` | clear `flash`; tick each test: 360 ms running, then its result, then 90 ms |
| `forge.attempt`, `forge.smoke` | attempt verdict; smoke running for 800 ms, then its result |
| `vault.saved` | tool into the vault store, selected, badge on, saved banner |
| `vault.failure` | failure recorded (or tool removed), health panel with the retry, removed banner when pruned |
| `call.args` | tabs for the variant, the Call tab, arguments revealed (ruling 5), code and history for vault tools |
| `call.result` / `call.error` | result (and a use recorded, and the record row for vault tools, ruling 8) / error |
| `interrupt` / `interrupt.resolved` | `waiting` and the dialog / `running` and no dialog |
| `answer.done` | the answer words fade in at 34 ms (none under reduced motion), note, chips, the live region |
| `run.finished` | status, summary, stop note when stopped, "View this run", `busy` off |

- [ ] **Step 1: Write the failing test** `frontend/src/transport/player.test.ts`

```ts
import { freshVault } from "../store/vaultOps";
import { VAULT_ROWS } from "../demo/data";
import { createStores, type Stores } from "../store/stores";
import { setReducedMotion } from "../test/media";
import type { EventData, EventType, RunEvent } from "./types";
import { dwell, momentAfter, Player, revealPlan, typingPlan } from "./player";

let seq = 0;
const ev = <T extends EventType>(type: T, data: EventData[T]): RunEvent => ({ run_id: "r", seq: ++seq, ts: "", type, data }) as RunEvent;
const stores = (): Stores =>
  createStores({ tools: freshVault(VAULT_ROWS), settings: { askExec: true, env: {}, model: "m" }, sessions: [], runs: [], current: { id: "s1", name: "Session 1", started: "2026-09-30T12:00" }, count: 1 });
const run = (s: Stores) => s.runs.get().byId.r!;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
});
afterEach(() => vi.useRealTimers());

test("pacing math, normal and reduced motion", () => {
  expect(dwell(900, 1, false)).toBe(900);
  expect(dwell(900, 2, false)).toBe(450);
  expect(dwell(900, 0.5, false)).toBe(1800);
  expect(dwell(900, 1, true)).toBe(40);
  expect(dwell(22, 1, true)).toBe(22);
  expect(typingPlan(96)).toEqual({ step: 3, ticks: 32 });
  expect(typingPlan(10)).toEqual({ step: 1, ticks: 10 });
  expect(revealPlan(63)).toEqual({ perTick: 1, ticks: 63 });
  expect(revealPlan(200)).toEqual({ perTick: 4, ticks: 50 });
});

test("the §6 minimum dwells for live runs", () => {
  expect(momentAfter(ev("log.line", { label: "vault", text: "no match", tone: "plain" }))).toBe(400);
  expect(momentAfter(ev("forge.code", { tool: "t", attempt: 2, file: "t.py", lines: [], changed: 1, note: null }))).toBe(1300);
  expect(momentAfter(ev("forge.attempt", { attempt: 1, ok: false, detail: "" }))).toBe(700);
  expect(momentAfter(ev("node.finished", { step: "human", status: "skip" }))).toBe(450);
  expect(momentAfter(ev("vault.saved", { tool: {} as never, sub: "" }))).toBe(900);
  expect(momentAfter(ev("call.args", { tool: "t", args: [["a", "1", false], ["b", "2", false]], caption: null }))).toBe(450);
  expect(momentAfter(ev("caption", { html: "" }))).toBe(0);
});

test("a normal-speed code reveal takes 24 ms per tick and stops where it was on abort", async () => {
  setReducedMotion(false);
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  const lines = Array.from({ length: 63 }, (_, i) => `line ${i}`);
  void p.push(ev("forge.code", { tool: "t", attempt: 1, file: "t.py", lines, changed: null, note: null, tests: 5 }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).code!.shown).toBe(1);
  await vi.advanceTimersByTimeAsync(24 * 9);
  expect(run(s).code!.shown).toBe(10);
  expect(run(s).tabs.map((t) => [t.id, t.count])).toEqual([["code", undefined], ["tests", 5], ["attempts", 1]]);
  p.abort();
  await vi.advanceTimersByTimeAsync(1000);
  expect(run(s).code!.shown).toBe(10);
});

test("reduced motion caps every step at 40 ms and shows the whole answer at once", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  const done = p.push(ev("forge.tests", { tool: "t", attempt: 1, results: [{ name: "a", passed: true, why: null }, { name: "b", passed: false, why: "AssertionError" }] }));
  void p.push(ev("answer.done", { html: "It decrypts to <b>x</b>.", note: null, chips: [] }));
  // 40 ms running, 40 ms gap, then the second test runs from 80 ms to 120 ms.
  await vi.advanceTimersByTimeAsync(100);
  expect(run(s).tests!.list.map((t) => t.state)).toEqual(["passed", "running"]);
  await vi.advanceTimersByTimeAsync(60);
  await done;
  expect(run(s).tests!.list[1]).toMatchObject({ state: "failed", why: "AssertionError" });
  const talos = s.session.get().sessions[0]!.messages[1]!;
  expect(talos).toMatchObject({ kind: "talos", html: "It decrypts to <b>x</b>.", wordsOn: 5, status: null }); // "." is its own text node
  expect(s.ui.get().live).toBe("Talos: It decrypts to x.");
});

test("run.started, a failure with prune, and a stop", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  s.vault.update((v) => ({ ...v, tools: [...v.tools, { ...v.tools[0]!, name: "caesar_cipher", streak: 1 }] }));
  const q = 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"';
  void p.push(ev("run.started", { session_id: "s1", query: q, n: 7 }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).strip).toBe("vault");
  expect(s.ui.get()).toMatchObject({ busy: true, currentRunId: "r", viewingRunId: "r" });
  void p.push(ev("call.args", { tool: "caesar_cipher", args: [["text", '"AHSVZ HNLUA"', false], ["shift", '"seven"', true], ["mode", '"decrypt"', false]], caption: null }));
  void p.push(ev("vault.failure", { tool: "caesar_cipher", streak: 2, pruned: true, error: "TypeError: shift must be an int, got str" }));
  await vi.advanceTimersByTimeAsync(2000);
  expect(run(s).call!.health).toMatchObject({ streak: 2, tool: "caesar_cipher", retry: { q: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"', label: "Ask again with shift 7" } });
  expect(run(s).banner).toMatchObject({ kind: "removed", name: "caesar_cipher" });
  expect(s.vault.get().tools.some((t) => t.name === "caesar_cipher")).toBe(false);
  void p.push(ev("run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] }));
  await vi.advanceTimersByTimeAsync(0);
  expect(s.session.get().sessions[0]!.messages[1]).toMatchObject({ stopNote: "Stopped. Ask again whenever you're ready.", runLink: true, status: null });
  expect(s.ui.get().busy).toBe(false);
});

test("dispose drops later events (Reset)", async () => {
  const s = stores();
  const p = new Player(s, { runId: "r", sessionId: "s1", momentDwell: false });
  void p.push(ev("run.started", { session_id: "s1", query: "q", n: 6 }));
  await vi.advanceTimersByTimeAsync(0);
  p.dispose();
  void p.push(ev("caption", { html: "late" }));
  await vi.advanceTimersByTimeAsync(0);
  expect(run(s).caption).toBeUndefined();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/transport/player.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `frontend/src/transport/player.ts`**

```ts
import { COPY, fill, healthText, removedSub, retryLabel } from "../lib/copy";
import { fmtTime, nowIso } from "../lib/format";
import { still as reducedMotion, wrapWordsHtml } from "../lib/motion";
import { NUM_WORDS, PRUNE_AT, provisionalVariant } from "../lib/routing";
import * as R from "../store/runOps";
import * as M from "../store/sessionOps";
import { updateRun, type Stores } from "../store/stores";
import type { CallArg, CallState, Run, Tab, TalosMessage } from "../store/types";
import * as V from "../store/vaultOps";
import type { EventOf, EventSink, RunEvent, StepKey } from "./types";

export const STILL_CAP_MS = 40;
/** The reference's wait() scaling (line 929). */
export const dwell = (ms: number, speed: number, still: boolean): number => (still ? Math.min(ms, STILL_CAP_MS) : ms / speed);

/** typeCmd() (line 1299). */
export function typingPlan(len: number): { step: number; ticks: number } {
  const step = Math.max(1, Math.ceil(len / 40));
  return { step, ticks: Math.ceil(len / step) };
}
/** revealCode() (line 1314). */
export function revealPlan(lines: number): { perTick: number; ticks: number } {
  const perTick = Math.max(1, Math.round(lines / 45));
  return { perTick, ticks: Math.ceil(lines / perTick) };
}

/** Fact animations: always player-side (ruling 4). */
export const PACE = { typeStep: 22, revealTick: 24, testRun: 360, testGap: 90, smokeRun: 800, argEach: 260, argSingle: 350, word: 34 } as const;
/** Spec 04 §6 minimum dwells: live runs only (momentDwell). DemoTransport waits these itself. */
export const MOMENTS = {
  afterVaultNoMatch: 400, retryShown: 1300, afterFailedAttempt: 700, afterSmoke: 400, humanPass: 450, afterSaved: 900,
  beforeResult: 450, beforeResultSingle: 500, vaultStep: 500, vaultSkip: 350, beforeDialog: 350,
} as const;
export const MIN_ACTIVE: Partial<Record<StepKey, number>> = { planner: 900, learn: 600 };

export function momentAfter(e: RunEvent): number {
  switch (e.type) {
    case "log.line":
      if (e.data.label === "vault" && e.data.text === "no match") return MOMENTS.afterVaultNoMatch;
      return e.data.label === "smoke" ? MOMENTS.afterSmoke : 0;
    case "forge.code":
      return e.data.attempt > 1 ? MOMENTS.retryShown : 0;
    case "forge.attempt":
      return e.data.ok ? 0 : MOMENTS.afterFailedAttempt;
    case "node.finished":
      if (e.data.step === "human" && e.data.status === "skip") return MOMENTS.humanPass;
      return e.data.step === "vault" ? MOMENTS.vaultStep : 0;
    case "link.flow":
      return e.data.from === "vault" && e.data.to === "skip" ? MOMENTS.vaultSkip : 0;
    case "vault.saved":
      return MOMENTS.afterSaved;
    case "call.args":
      if (e.data.caption) return 0;
      return e.data.args.length === 1 ? MOMENTS.beforeResultSingle : MOMENTS.beforeResult;
    default:
      return 0;
  }
}

const RUNNING_PENDING = `${COPY.call.running}<span class="caret" aria-hidden="true"></span>`;
const textOf = (html: string): string => {
  const p = document.createElement("p");
  p.innerHTML = html;
  return p.textContent ?? "";
};

export interface PlayerOptions {
  runId: string;
  sessionId: string;
  /** Live runs apply the §6 minimum dwells; DemoTransport performs them itself (ruling 4). */
  momentDwell: boolean;
  /** Replaying a finished run: no pacing, final states, no messages. */
  replay?: boolean;
  /** Tool source for vault runs' Code tab. */
  source?: (tool: string) => Promise<string[] | null>;
}

/** Turns contract events into store updates, with the reference's pacing (spec 04 §6). */
export class Player {
  private queue: Promise<void> = Promise.resolve();
  private aborted = false;
  private gone = false;
  private wake: (() => void) | null = null;
  private startedAt = new Map<StepKey, number>();
  private callTool: string | null = null;
  private testsCount: number | undefined;

  constructor(
    private readonly stores: Stores,
    private readonly opts: PlayerOptions,
  ) {}

  /** The EventSink: resolves once the event is on screen and its animation is over. */
  push: EventSink = (e) => {
    this.queue = this.queue
      .then(() => (this.gone ? undefined : this.apply(e)))
      .catch((err: unknown) => console.error("player", err));
    return this.queue;
  };

  /** Stop: animations stay where they are; later events apply without pacing. */
  abort(): void {
    this.aborted = true;
    this.wake?.();
  }
  /** Reset: nothing more is applied. */
  dispose(): void {
    this.gone = true;
    this.abort();
  }

  private get fast(): boolean {
    return this.aborted || !!this.opts.replay;
  }
  private sleep(ms: number): Promise<void> {
    if (this.fast || ms <= 0) return Promise.resolve();
    const d = dwell(ms, this.stores.ui.get().speed, reducedMotion());
    return new Promise((resolve) => {
      const t = setTimeout(() => {
        this.wake = null;
        resolve();
      }, d);
      this.wake = () => {
        clearTimeout(t);
        this.wake = null;
        resolve();
      };
    });
  }
  private run(): Run {
    return this.stores.runs.get().byId[this.opts.runId]!;
  }
  private up(fn: (r: Run) => Run): void {
    updateRun(this.stores, this.opts.runId, fn);
  }
  private talos(fn: (m: TalosMessage) => TalosMessage): void {
    const n = this.run().n;
    this.stores.session.update((s) => M.updateTalos(s, n, fn));
  }

  private async apply(e: RunEvent): Promise<void> {
    if (this.opts.momentDwell) {
      if (e.type === "node.finished") {
        const min = MIN_ACTIVE[e.data.step];
        const at = this.startedAt.get(e.data.step);
        if (min && at != null) await this.sleep(Math.max(0, min - (Date.now() - at)));
      }
      if (e.type === "interrupt") await this.sleep(MOMENTS.beforeDialog);
    }
    await this.handle(e);
    if (this.opts.momentDwell) await this.sleep(momentAfter(e));
  }

  private async handle(e: RunEvent): Promise<void> {
    switch (e.type) {
      case "run.started":
        return this.started(e);
      case "log.cmd":
        return this.typeCmd(e.data.text);
      case "plan.ready":
      case "subtask.started":
      case "answer.delta":
      case "error":
        return;
      case "strip.set": {
        const d = e.data;
        this.up((r) => {
          let x = r.strip === d.variant ? r : R.initStrip(r, d.variant, true);
          x = R.setSig(R.setLabel(x, d.subtask.label), d.sig);
          return d.sig ? x : R.setTitle(x, d.title ?? COPY.bench.noTools);
        });
        return;
      }
      case "node.started": {
        const { step, label } = e.data;
        this.startedAt.set(step, Date.now());
        this.up((r) => {
          const x = R.setNode(r, step, "active", label);
          return step === "forger" && (r.attempts?.length ?? 0) > 0 ? R.patch(x, { retrying: true }) : x;
        });
        return;
      }
      case "node.finished": {
        const { step, status, label } = e.data;
        this.up((r) => {
          const x = R.setNode(r, step, status, label);
          return step === "forger" && r.retrying ? R.patch(x, { retrying: false }) : x;
        });
        return;
      }
      case "link.flow":
        this.up((r) => R.flow(r, e.data.from, e.data.to));
        return;
      case "caption":
        this.up((r) => R.setCaption(r, e.data.html));
        return;
      case "log.line": {
        const { label, text, tone, caret } = e.data;
        this.up((r) => {
          const x = R.log(r, label, text, tone === "plain" || tone === "sub" ? "" : tone, { caret, sub: tone === "sub" });
          return label === "execute" && text === "running" && x.call ? R.patchCall(x, { pending: RUNNING_PENDING }) : x;
        });
        return;
      }
      case "log.pop":
        this.up(R.logPop);
        return;
      case "log.status":
        this.up((r) => R.logTone(R.logStatus(r, e.data.text, e.data.gold), e.data.tone));
        return;
      case "talos.status":
        this.talos((m) => ({ ...m, status: e.data.text }));
        return;
      case "forge.code":
        return this.forgeCode(e);
      case "forge.tests":
        return this.forgeTests(e);
      case "forge.attempt": {
        const { attempt, ok, detail } = e.data;
        this.up((r) => ({ ...r, attempts: (r.attempts ?? []).map((a) => (a.n === attempt ? { ...a, ok, detail } : a)) }));
        return;
      }
      case "forge.smoke": {
        const { call, result } = e.data;
        this.up((r) => ({ ...r, smoke: { call, result: null } }));
        await this.sleep(PACE.smokeRun);
        if (this.aborted) return;
        this.up((r) => ({ ...r, smoke: { call, result } }));
        return;
      }
      case "vault.saved": {
        const tool = V.fromVaultEntry(e.data.tool, true);
        this.stores.vault.update((v) => ({ ...v, tools: V.addTool(v.tools, tool) }));
        this.stores.ui.set({ selected: tool.name, badge: true });
        this.up((r) => R.setBanner(r, { kind: "saved", name: tool.name, sub: e.data.sub }));
        return;
      }
      case "vault.failure":
        return this.failure(e);
      case "call.args":
        return this.callArgs(e);
      case "call.result":
        return this.callResult(e);
      case "call.error":
        this.up((r) => R.patchCall(r, { error: e.data.error, when: e.data.when }));
        return;
      case "interrupt": {
        const d = e.data;
        const runId = this.opts.runId;
        this.up((r) => R.patch(r, { status: "waiting" }));
        if (this.opts.replay) return;
        this.stores.ui.set({
          dialog:
            d.kind === "confirm_exec"
              ? { kind: "approval", runId, tool: d.payload.tool, code: d.payload.preview }
              : { kind: "key", runId, toolName: d.payload.tool_name, envVar: d.payload.env_var, service: d.payload.service },
        });
        return;
      }
      case "interrupt.resolved": {
        this.up((r) => R.patch(r, { status: "running" }));
        const dlg = this.stores.ui.get().dialog;
        if (dlg && "runId" in dlg && dlg.runId === this.opts.runId) this.stores.ui.set({ dialog: null });
        return;
      }
      case "answer.done":
        return this.answer(e);
      case "run.finished":
        return this.finished(e);
    }
  }

  private started(e: EventOf<"run.started">): void {
    const { query, n } = e.data;
    const sid = this.opts.sessionId;
    const names = this.stores.vault.get().tools.map((t) => t.name);
    const run = R.initStrip(R.newRun({ id: this.opts.runId, n, query, sessionId: sid }), provisionalVariant(query, names));
    this.stores.runs.update((s) => ({ byId: { ...s.byId, [run.id]: run } }));
    if (this.opts.replay) return;
    this.stores.session.update((s) => M.addTalos(M.attachRun(M.addYou(s, sid, query, `you-${n}`), sid, run.id), sid, n, `talos-${n}`, COPY.convo.thinking));
    this.stores.ui.set({ currentRunId: run.id, viewingRunId: run.id, busy: true });
  }

  private async typeCmd(text: string): Promise<void> {
    this.up((r) => R.startCmd(r, text));
    if (!this.fast) {
      const { step } = typingPlan(text.length);
      let shown = 0;
      while (shown < text.length) {
        shown = Math.min(text.length, shown + step);
        const s = shown;
        this.up((r) => R.typeCmd(r, s));
        await this.sleep(PACE.typeStep);
        if (this.aborted) return;
      }
    }
    this.up(R.endCmd);
  }

  private async forgeCode(e: EventOf<"forge.code">): Promise<void> {
    const d = e.data;
    if (d.tests != null) this.testsCount = d.tests;
    const count = this.testsCount;
    const first = d.attempt === 1 || !this.run().code;
    this.up((r) => {
      const attempts = [...(r.attempts ?? []), { n: d.attempt, ok: null, detail: "" }];
      const tabs: Tab[] = r.tabs.some((t) => t.id === "code")
        ? r.tabs.map((t) => (t.id === "attempts" ? { ...t, count: attempts.length } : t.id === "tests" && count != null ? { ...t, count } : t))
        : [
            { id: "code", label: COPY.bench.tabs.code },
            { id: "tests", label: COPY.bench.tabs.tests, count },
            { id: "attempts", label: COPY.bench.tabs.attempts, count: attempts.length },
          ];
      const cap = fill(COPY.code.cap, { n: d.lines.length, a: d.attempt });
      const next: Run = first
        ? { ...r, attempts, tabs, code: { file: d.file, cap, lines: d.lines, shown: 0, changed: null, note: "" }, codeScroll: "bottom" }
        : { ...r, attempts, tabs, code: { ...r.code!, lines: d.lines, cap, changed: d.changed, flash: true, note: d.note ?? "", shown: d.lines.length }, codeScroll: d.changed };
      return R.setTab(next, "code");
    });
    if (!first) return;
    if (this.fast) {
      this.up((r) => R.patchCode(r, { shown: d.lines.length }));
      return;
    }
    const { perTick } = revealPlan(d.lines.length);
    let shown = 0;
    while (shown < d.lines.length) {
      shown = Math.min(d.lines.length, shown + perTick);
      const s = shown;
      this.up((r) => R.patchCode(r, { shown: s }));
      await this.sleep(PACE.revealTick);
      if (this.aborted) return;
    }
  }

  private async forgeTests(e: EventOf<"forge.tests">): Promise<void> {
    const d = e.data;
    this.testsCount = d.results.length;
    this.up((r) =>
      R.setTab({ ...R.patchCode(r, { flash: false }), tests: { attempt: d.attempt, list: d.results.map((x) => ({ name: x.name, state: "waiting" as const, why: "" })) } }, "tests"),
    );
    const set = (i: number, state: "running" | "passed" | "failed", why = "") =>
      this.up((r) => ({ ...r, tests: { ...r.tests!, list: r.tests!.list.map((x, j) => (j === i ? { ...x, state, why } : x)) } }));
    for (let i = 0; i < d.results.length; i++) {
      const res = d.results[i]!;
      const final = res.passed ? "passed" : "failed";
      if (this.fast) {
        if (!this.aborted) set(i, final, res.passed ? "" : (res.why ?? ""));
        continue;
      }
      set(i, "running");
      await this.sleep(PACE.testRun);
      if (this.aborted) return;
      set(i, final, res.passed ? "" : (res.why ?? ""));
      await this.sleep(PACE.testGap);
      if (this.aborted) return;
    }
  }

  private failure(e: EventOf<"vault.failure">): void {
    const { tool, streak, pruned, error } = e.data;
    const now = nowIso();
    this.stores.vault.update((v) => ({ ...v, tools: pruned ? V.removeTool(v.tools, tool) : V.recordFailure(v.tools, tool, streak, error, now) }));
    const r0 = this.run();
    // The retry button (lines 1717–1718, 1731): a word where the tool wanted a number.
    let retry: { q: string; label: string } | null = null;
    const bad = r0.call?.args.find((a) => a[2]);
    if (bad) {
      const [name, repr] = bad;
      const word = repr.replace(/^"|"$/g, "");
      const digit = NUM_WORDS[word.toLowerCase()];
      if (digit != null) retry = { q: r0.query.replace(new RegExp(`${name}(\\s+of)?\\s+${word}`, "i"), `${name} ${digit}`), label: retryLabel(name, digit) };
    }
    this.up((r) => {
      let x = R.patch(R.patchCall(r, { health: { streak: Math.min(streak, PRUNE_AT), tool, text: healthText(tool, pruned), retry } }), { failed: true });
      if (pruned) x = R.setBanner(x, { kind: "removed", name: tool, sub: removedSub(tool) });
      return x;
    });
  }

  private async callArgs(e: EventOf<"call.args">): Promise<void> {
    const d = e.data;
    const r0 = this.run();
    this.callTool = d.tool;
    const exec = d.tool === "python_exec" || d.tool === "shell_exec";
    const args: CallArg[] = d.args.map(([k, v, bad]) => [k, v, bad]);
    let tabs = r0.tabs;
    let code = r0.code;
    if (r0.strip === "forge") tabs = [...r0.tabs.filter((t) => t.id !== "call" && t.id !== "log"), { id: "call", label: COPY.bench.tabs.call }];
    else if (r0.strip === "vault") {
      tabs = [{ id: "call", label: COPY.bench.tabs.call }, { id: "code", label: COPY.bench.tabs.code }, { id: "history", label: COPY.bench.tabs.history }];
      const lines = await this.source(d.tool);
      if (lines) code = { file: `${d.tool}.py`, cap: fill(COPY.code.lines, { n: lines.length }), lines, shown: lines.length };
    } else tabs = [{ id: "call", label: COPY.bench.tabs.call }];
    const call: CallState = {
      args,
      shownArgs: d.caption || this.fast ? undefined : 0,
      noArgs: args.length === 0 ? true : undefined,
      argsCap: d.caption ?? undefined,
      resultCap: r0.strip === "primitive" ? COPY.call.output : undefined,
      pending: exec ? COPY.call.awaitingApproval : undefined,
    };
    this.up((r) =>
      R.setTab(
        { ...r, tabs, code, call, toolName: r.strip === "vault" ? d.tool : r.toolName, toolUsed: r.strip === "primitive" ? r.toolUsed : d.tool },
        "call",
      ),
    );
    if (d.caption || this.fast) return;
    const each = args.length === 1 ? PACE.argSingle : PACE.argEach;
    for (let i = 1; i <= args.length; i++) {
      await this.sleep(each);
      if (this.aborted) return;
      this.up((r) => R.patchCall(r, { shownArgs: i }));
    }
  }

  private async source(tool: string): Promise<string[] | null> {
    const cached = this.stores.vault.get().sources[tool];
    if (cached !== undefined) return cached;
    const lines = (await this.opts.source?.(tool)) ?? null;
    this.stores.vault.update((v) => ({ ...v, sources: { ...v.sources, [tool]: lines } }));
    return lines;
  }

  private callResult(e: EventOf<"call.result">): void {
    const { repr, type, small } = e.data;
    const r0 = this.run();
    const tool = this.callTool;
    let record: CallState["record"];
    if (tool && r0.strip !== "primitive") {
      this.stores.vault.update((v) => ({ ...v, tools: V.recordUse(v.tools, tool, nowIso()) }));
      const t = V.findTool(this.stores.vault.get().tools, tool);
      if (t && r0.strip === "vault" && !small) {
        record = { forged: fmtTime(t.created), uses: fill(COPY.call.recordUses, { n: t.uses }), fails: t.fails ? fill(COPY.call.recordFails, { n: t.fails }) : COPY.call.recordNone };
      }
    }
    this.up((r) => R.patchCall(r, { result: repr, resultType: type || undefined, smallResult: small || undefined, record }));
  }

  private async answer(e: EventOf<"answer.done">): Promise<void> {
    const d = e.data;
    const total = wrapWordsHtml(d.html, 0).count;
    const instant = this.fast || reducedMotion();
    this.talos((m) => ({ ...m, status: null, html: d.html, wrap: true, wordsOn: instant ? total : 0 }));
    if (!instant) {
      for (let i = 1; i <= total; i++) {
        this.talos((m) => ({ ...m, wordsOn: i }));
        await this.sleep(PACE.word);
        if (this.aborted) return;
      }
    }
    this.talos((m) => ({ ...m, note: d.note, chips: d.chips, suggest: !!d.suggest }));
    if (!this.opts.replay) this.stores.ui.set({ live: COPY.convo.livePrefix + textOf(d.html) });
  }

  private finished(e: EventOf<"run.finished">): void {
    const d = e.data;
    this.up((r) => ({
      ...r,
      status: r.status === "running" || r.status === "waiting" ? d.status : r.status,
      summary: d.summary,
      summaryGold: d.summary_gold,
      forged: r.forged || d.forged.length > 0,
      retrying: false,
    }));
    if (this.opts.replay) return;
    const stopped = d.status === "stopped";
    this.talos((m) => ({
      ...m,
      ...(stopped ? { status: null, wordsOn: Number.MAX_SAFE_INTEGER, stopNote: COPY.convo.stopped } : {}),
      runLink: true,
    }));
    this.stores.ui.set({ busy: false });
  }
}
```

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/transport/player.test.ts && npm run lint && npm run typecheck`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/transport/player.ts frontend/src/transport/player.test.ts
git commit -m "[Feat]: Add the event player with the reference's pacing"
```

---

### Task 14: DemoTransport (the scripted flows as contract events)

**Files:**
- Create: `frontend/src/transport/demo.ts`
- Create (by the golden test): `frontend/src/transport/__golden__/caesar-forge.json`, `caesar-reuse.json`, `caesar-word-shift.json`, `python-approve.json`, `weather-key-save.json`
- Test: `frontend/src/transport/demo.test.tsx`

**Interfaces:**
- Consumes: the contract types, `dwell`, `Player` (Task 13), `STRIPS` (Task 5), `classify`, `parseCaesar`, `caesar`, `runPython`, `sessionName`, `provisionalVariant`, `NUM_WORDS`, `PRUNE_AT` (Task 3), `esc`, `fmtTime`, `nowIso`, `pyStr` (Task 3), `CAESAR`, `WEATHER`, `SOURCES` (Task 4), `still` (Task 3).
- Produces:
  - `class DemoTransport implements Transport { constructor(world: DemoWorld, opts: { lastRunNumber: number }); reset(lastRunNumber: number): void; events(runId: string): RunEvent[] }`.
  - `DemoWorld = { tools(): VaultTool[]; hasKey(env: string): boolean; saveKey(env: string, value: string): void; askExec(): boolean; speed(): number; sessionRunCount(sessionId: string): number }`.

`DemoTransport` is the reference's flows (`planner` 1517, `forgeTool` 1527, `humanCheck` 1595, `learn` 1639, `flowCaesar` 1654, `executeCaesar` 1698, `flowPython` 1779, `flowWeather` 1840, `flowVaultList` 1909, `flowChat` 1930, `flowUnknown` 1940, `stopRun` 1485) with every renderer call replaced by an event and every non-animation `wait()` kept. Every string, value and step is the reference's. The mapping:

| Reference call | Event |
|---|---|
| `setNode(k, "active", label?)` | `node.started` |
| `setNode(k, state, label?)` | `node.finished` with `status: state` |
| `flow(a, b)` | `link.flow` |
| `setCaption(html)` | `caption` |
| `log(label, text, tone, {caret, sub})` | `log.line` (`tone: "plain"` for `""`, `"sub"` for sub lines) |
| `run.log.pop()` | `log.pop` |
| `logStatus(text, gold)` / `logTone(tone)` | `log.status` carrying all three (the transport tracks the current text, gold and tone) |
| `run.talos.status(text)` | `talos.status` |
| `setLabel` + `setSig` (+ `run.title`) | `strip.set` |
| `revealCode` / the retry's code swap | `forge.code` (+ `tests`, ruling 1) |
| `runTests` | `forge.tests` (all results at once; the player ticks them) |
| `run.attempts[a].ok/detail` | `forge.attempt` |
| smoke | `forge.smoke` (the player shows it running for 800 ms) |
| `learn()`'s vault push + banner | `vault.saved` |
| a failure's vault update + banner + health | `vault.failure` |
| `run.call = {…}` + argument reveal | `call.args` |
| `run.call.result` / `run.call.error` | `call.result` / `call.error` |
| `approvalDialog` / `keyDialog` | `interrupt`, then `interrupt.resolved` after `resume()` |
| `run.talos.say(html, note)` + `chip()` + the inline suggestions | `answer.done` |
| the end of `submit()` | `run.finished` |

Waits that the player owns (don't repeat them here): typing (22), reveal (24), tests (360/90), smoke running (800), per-argument (260/350), words (34). Waits the transport keeps: 900 (planner), 400 (after `vault no match`), 1300 (retry), 700 (failed attempt), 400 (after smoke), 450 (human pass-through), 350 (before a dialog), 500 (after a key answer), 600 + 900 (learn), 450 or 500 (before a result), 500 + 350 (vault step, Caesar), 400 + 300 (vault step, weather), 700 (python running, vault_list).

- [ ] **Step 1: Write the failing test** `frontend/src/transport/demo.test.tsx`

```tsx
import { SOURCES, VAULT_ROWS } from "../demo/data";
import { Panel, earlierData } from "../components/workbench/panels/Panel";
import { Banner } from "../components/workbench/Banner";
import { Strip } from "../components/workbench/Strip";
import { Tabs } from "../components/workbench/Tabs";
import { createStores, type Stores } from "../store/stores";
import type { VaultTool } from "../store/types";
import { freshVault } from "../store/vaultOps";
import { expectParity, FIXED_NOW, snap } from "../test/parity";
import { innerOf, ssr } from "../test/ssr";
import { DemoTransport, type DemoWorld } from "./demo";
import { Player } from "./player";
import type { ResumeDecision, RunEvent } from "./types";

const Q = {
  forge: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.',
  reuse: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  wordShift: 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"',
  python: "Run this Python code and give me the output: print(sum(range(1, 101)))",
  weather: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};

function setup() {
  const stores = createStores({ tools: freshVault(VAULT_ROWS), settings: { askExec: true, env: {}, model: "m" }, sessions: [], runs: [], current: { id: "s1", name: "Session 1", started: "2026-09-30T12:00" }, count: 1 });
  const world: DemoWorld = {
    tools: () => stores.vault.get().tools,
    hasKey: (env) => !!stores.settings.get().env[env],
    saveKey: (env, value) => stores.settings.update((s) => ({ ...s, env: { ...s.env, [env]: value } })),
    askExec: () => stores.settings.get().askExec,
    speed: () => stores.ui.get().speed,
    sessionRunCount: (sid) => stores.session.get().sessions.find((s) => s.id === sid)?.runIds.length ?? 0,
  };
  const transport = new DemoTransport(world, { lastRunNumber: 5 });
  return { stores, transport };
}

/** Runs one query through DemoTransport and the Player; answers dialogs with `answer`. */
async function ask(stores: Stores, transport: DemoTransport, q: string, answer?: ResumeDecision) {
  const started = await transport.startRun("s1", q);
  const player = new Player(stores, { runId: started.runId, sessionId: "s1", momentDwell: false, source: async (n) => SOURCES[n] ?? null });
  transport.subscribe(started.runId, player.push);
  for (let i = 0; i < 5000; i++) {
    await vi.advanceTimersToNextTimerAsync();
    const d = stores.ui.get().dialog;
    if (d && "runId" in d && answer) {
      stores.ui.set({ dialog: null });
      await transport.resume(d.runId, answer);
    }
    if (!stores.ui.get().busy && stores.runs.get().byId[started.runId]?.summary !== undefined) break;
  }
  return started.runId;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
});
afterEach(() => vi.useRealTimers());

function expectRunMatches(stores: Stores, runId: string, flowName: string, snapName: string) {
  const s = snap(flowName, snapName);
  const run = stores.runs.get().byId[runId]!;
  const tools = stores.vault.get().tools as VaultTool[];
  const runs = stores.session.get().sessions[0]!.runIds.map((id) => stores.runs.get().byId[id]!);
  expectParity(innerOf(ssr(<Strip run={run} />)), s.pure!.strip);
  expectParity(ssr(<Banner banner={run.banner} />), s.pure!.banner);
  expectParity(ssr(<Tabs run={run} onSelect={() => {}} />), s.pure!.tabs);
  expectParity(
    ssr(<Panel run={run} isCurrent tool={tools.find((t) => t.name === run.toolName)} earlier={earlierData(runs, run, false)} onAsk={() => {}} onOpenTool={() => {}} onRun={() => {}} />),
    s.pure!.panel,
  );
}

test("the Caesar forge run ends exactly as the reference's", async () => {
  const { stores, transport } = setup();
  const id = await ask(stores, transport, Q.forge);
  expectRunMatches(stores, id, "caesar-forge", "end");
  expect(stores.session.get().sessions[0]!.name).toBe("Session 1"); // renaming is the controller's job (Task 15)
});

test("the Caesar reuse run ends as the reference's", async () => {
  const { stores, transport } = setup();
  await ask(stores, transport, Q.forge);
  const reuse = await ask(stores, transport, Q.reuse);
  expectRunMatches(stores, reuse, "caesar-reuse", "end");
});

test("python approve ends as the reference's", async () => {
  const { stores, transport } = setup();
  const id = await ask(stores, transport, Q.python, { decision: "approve" });
  expectRunMatches(stores, id, "python-approve", "end");
});

test("stop during a pause finishes the run as stopped", async () => {
  const { stores, transport } = setup();
  const started = await transport.startRun("s1", Q.python);
  const player = new Player(stores, { runId: started.runId, sessionId: "s1", momentDwell: false });
  transport.subscribe(started.runId, player.push);
  while (!stores.ui.get().dialog) await vi.advanceTimersToNextTimerAsync();
  player.abort();
  stores.ui.set({ dialog: null });
  await transport.stop(started.runId);
  await vi.advanceTimersByTimeAsync(0);
  const run = stores.runs.get().byId[started.runId]!;
  expect(run.status).toBe("stopped");
  expect(run.nodes.executor).toMatchObject({ state: "stopped", label: "Executor, stopped" });
  expect(run.caption).toBe("You stopped this run. Nothing was saved to the vault.");
  expect(transport.events(started.runId).at(-1)!.type).toBe("run.finished");
});

test("sessionName comes back on a session's first run only", async () => {
  const { transport } = setup();
  expect((await transport.startRun("s1", Q.weather)).sessionName).toBe("Weather in Mumbai");
});

/** Golden event logs for the five fake-graph flows (ruling 14). `npx vitest -u` rewrites them. */
test.each([
  ["caesar-forge", [Q.forge], undefined],
  ["caesar-reuse", [Q.forge, Q.reuse], undefined],
  ["caesar-word-shift", [Q.forge, Q.wordShift], undefined],
  ["python-approve", [Q.python], { decision: "approve" } as ResumeDecision],
  ["weather-key-save", [Q.weather], { decision: "save", value: "k" } as ResumeDecision],
] as const)("golden: %s", async (name, queries, answer) => {
  const { stores, transport } = setup();
  let last = "";
  for (const q of queries) last = await ask(stores, transport, q, answer);
  const events = transport.events(last).map((e: RunEvent) => ({ seq: e.seq, type: e.type, data: e.data }));
  expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1));
  expect(events[0]!.type).toBe("run.started");
  expect(events.at(-1)!.type).toBe("run.finished");
  await expect(JSON.stringify(events, null, 1) + "\n").toMatchFileSnapshot(`./__golden__/${name}.json`);
});

test("reset cancels runs silently and restarts the counter", async () => {
  const { transport } = setup();
  const started = await transport.startRun("s1", Q.forge);
  const seen: string[] = [];
  transport.subscribe(started.runId, async (e) => void seen.push(e.type));
  await vi.advanceTimersByTimeAsync(100);
  transport.reset(5);
  const count = seen.length;
  await vi.advanceTimersByTimeAsync(10000);
  expect(seen.length).toBe(count);
  expect((await transport.startRun("s1", Q.forge)).n).toBe(6);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/transport/demo.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `frontend/src/transport/demo.ts`**

```ts
import { CAESAR, SOURCES, WEATHER, type ToolMeta } from "../demo/data";
import { esc, fmtTime, nowIso, pyStr } from "../lib/format";
import { still } from "../lib/motion";
import { caesar, classify, NUM_WORDS, parseCaesar, provisionalVariant, PRUNE_AT, runPython, sessionName, type CaesarParams } from "../lib/routing";
import { STRIPS } from "../store/runOps";
import type { VaultTool } from "../store/types";
import { dwell } from "./player";
import type { EventData, EventSink, EventType, ResumeDecision, RunEvent, Sig, StartedRun, StepKey, Transport, Variant, VaultEntry } from "./types";

export interface DemoWorld {
  tools(): VaultTool[];
  hasKey(env: string): boolean;
  saveKey(env: string, value: string): void;
  askExec(): boolean;
  speed(): number;
  sessionRunCount(sessionId: string): number;
}

class Stopped extends Error {}

interface Outcome {
  status: "done" | "failed" | "declined";
  summary: string;
  gold: boolean;
  forged: string[];
  used: string[];
}

interface DemoRun {
  id: string;
  n: number;
  sessionId: string;
  query: string;
  sink: EventSink | null;
  seq: number;
  events: RunEvent[];
  cancelled: boolean;
  silent: boolean;
  stopping: boolean;
  done: boolean;
  timers: ReturnType<typeof setTimeout>[];
  rejectWait: (() => void) | null;
  waiting: { resolve: (d: ResumeDecision) => void; reject: (e: unknown) => void } | null;
  variant: Variant;
  labels: Map<StepKey, string>;
  active: Set<StepKey>;
  status: { text: string; gold: boolean; tone: "" | "warm" | "alert" };
  outcome: Outcome;
  flow: Promise<void> | null;
}

const sigOf = (m: ToolMeta): Sig => ({ name: m.name, args: m.args, ret: m.ret });
const entryOf = (m: ToolMeta): VaultEntry => ({
  name: m.name, args: m.args, ret: m.ret, signature: `${m.name}(${m.args}) -> ${m.ret}`, description: m.desc, keywords: m.kw,
  uses: 0, failures: 0, streak: 0, created_at: nowIso(), last_used: null, last_failure: null, last_failed_at: null, web: !!m.web,
  file: `talos/vault/tools/${m.name}.py`,
});

interface ForgeSpec {
  meta: ToolMeta;
  attempts: { lines: string[]; changed?: number; note?: string }[];
  tests: string[];
  failIdx: number;
  failWhy: string;
  smoke: { call: string; result: string } | null;
}

/** The reference's scripted flows, emitting contract events (spec 04 §8.3). */
export class DemoTransport implements Transport {
  private runs = new Map<string, DemoRun>();
  private counter: number;

  constructor(
    private readonly world: DemoWorld,
    opts: { lastRunNumber: number },
  ) {
    this.counter = opts.lastRunNumber;
  }

  async startRun(sessionId: string, text: string): Promise<StartedRun> {
    const n = ++this.counter;
    const id = `demo-${n}`;
    const variant = provisionalVariant(text, this.world.tools().map((t) => t.name));
    this.runs.set(id, {
      id, n, sessionId, query: text, sink: null, seq: 0, events: [], cancelled: false, silent: false, stopping: false, done: false,
      timers: [], rejectWait: null, waiting: null, variant, labels: new Map(STRIPS[variant].map(([k, l]) => [k, l])), active: new Set(),
      status: { text: "", gold: false, tone: "" }, outcome: { status: "done", summary: "", gold: false, forged: [], used: [] }, flow: null,
    });
    const first = this.world.sessionRunCount(sessionId) === 0;
    return { runId: id, n, sessionName: first ? sessionName(classify(text), text) : null };
  }

  subscribe(runId: string, sink: EventSink): () => void {
    const r = this.runs.get(runId);
    if (!r) return () => {};
    r.sink = sink;
    if (!r.flow) r.flow = this.play(r);
    return () => {
      r.sink = null;
    };
  }

  async resume(runId: string, decision: ResumeDecision): Promise<void> {
    const r = this.runs.get(runId);
    const w = r?.waiting;
    if (!r || !w) return;
    r.waiting = null;
    w.resolve(decision);
  }

  /** stopRun() (line 1485). */
  async stop(runId: string): Promise<void> {
    const r = this.runs.get(runId);
    if (!r || r.done || r.cancelled) return;
    this.cancel(r);
    await r.flow?.catch(() => {});
    r.stopping = true;
    for (const [step] of STRIPS[r.variant]) {
      if (!r.active.has(step)) continue;
      const label = `${(r.labels.get(step) ?? "").replace(/, .*$/, "")}, stopped`;
      await this.emit(r, "node.finished", { step, status: "stopped", label });
    }
    await this.line(r, "stop", "stopped by you", "w");
    await this.logStatus(r, "Stopped");
    await this.cap(r, "You stopped this run. Nothing was saved to the vault.");
    await this.emit(r, "run.finished", { status: "stopped", summary: "Stopped", summary_gold: false, forged: [], used: [] });
    r.done = true;
  }

  /** resetDemo() (line 2280): every run ends without another event. */
  reset(lastRunNumber: number): void {
    for (const r of this.runs.values()) {
      r.silent = true;
      this.cancel(r);
    }
    this.runs.clear();
    this.counter = lastRunNumber;
  }

  events(runId: string): RunEvent[] {
    return this.runs.get(runId)?.events ?? [];
  }

  /* ---------- plumbing ---------- */

  private cancel(r: DemoRun): void {
    r.cancelled = true;
    r.timers.forEach(clearTimeout);
    r.rejectWait?.();
    r.waiting?.reject(new Stopped());
    r.waiting = null;
  }

  private async emit<T extends EventType>(r: DemoRun, type: T, data: EventData[T]): Promise<void> {
    if (r.silent || (r.cancelled && !r.stopping)) throw new Stopped();
    r.seq += 1;
    if (type === "node.started" || type === "node.finished") {
      const d = data as EventData["node.started"] & { label?: string };
      if (d.label) r.labels.set(d.step, d.label);
      if (type === "node.started") r.active.add(d.step);
      else r.active.delete(d.step);
    }
    if (type === "strip.set") {
      const v = (data as EventData["strip.set"]).variant;
      if (v !== r.variant) {
        r.variant = v;
        for (const [k, l] of STRIPS[v]) if (!r.labels.has(k)) r.labels.set(k, l);
      }
    }
    const e = { run_id: r.id, seq: r.seq, ts: new Date().toISOString(), type, data } as RunEvent;
    r.events.push(e);
    await r.sink?.(e);
    if (r.silent || (r.cancelled && !r.stopping)) throw new Stopped();
  }

  /** wait() (line 926) for the moments the player doesn't own. */
  private wait(r: DemoRun, ms: number): Promise<void> {
    return new Promise((resolve, reject) => {
      if (r.cancelled) return reject(new Stopped());
      const t = setTimeout(() => {
        r.rejectWait = null;
        if (r.cancelled) reject(new Stopped());
        else resolve();
      }, dwell(ms, this.world.speed(), still()));
      r.timers.push(t);
      r.rejectWait = () => {
        clearTimeout(t);
        reject(new Stopped());
      };
    });
  }

  private async interrupt(r: DemoRun, data: EventData["interrupt"]): Promise<ResumeDecision> {
    await this.emit(r, "interrupt", data);
    const d = await new Promise<ResumeDecision>((resolve, reject) => {
      r.waiting = { resolve, reject };
    });
    if (r.cancelled) throw new Stopped();
    return d;
  }

  private node = (r: DemoRun, step: StepKey, state: string, label?: string) =>
    state === "active"
      ? this.emit(r, "node.started", label ? { step, label } : { step })
      : this.emit(r, "node.finished", { step, status: state as EventData["node.finished"]["status"], ...(label ? { label } : {}) });
  private flowTo = (r: DemoRun, from: StepKey, to: StepKey) => this.emit(r, "link.flow", { from, to });
  private cap = (r: DemoRun, html: string) => this.emit(r, "caption", { html });
  private say = (r: DemoRun, text: string) => this.emit(r, "talos.status", { text });
  private line = (r: DemoRun, label: string, text: string, tone: "plain" | "g" | "w" | "sub" = "plain", caret = false) =>
    this.emit(r, "log.line", caret ? { label, text, tone, caret } : { label, text, tone });
  private logStatus(r: DemoRun, text: string, gold = false) {
    r.status = { ...r.status, text, gold };
    return this.emit(r, "log.status", { ...r.status });
  }
  private logTone(r: DemoRun, tone: "" | "warm" | "alert") {
    r.status = { ...r.status, tone };
    return this.emit(r, "log.status", { ...r.status });
  }
  private strip = (r: DemoRun, variant: Variant, label: string, sig: Sig | null, title?: string) =>
    this.emit(r, "strip.set", { variant, subtask: { index: 1, total: 1, label }, sig, ...(title ? { title } : {}) });
  private findTool = (name: string) => this.world.tools().find((t) => t.name === name);

  /* ---------- flows ---------- */

  private async play(r: DemoRun): Promise<void> {
    try {
      await this.emit(r, "run.started", { session_id: r.sessionId, query: r.query, n: r.n });
      await this.emit(r, "log.cmd", { text: r.query });
      const kind = classify(r.query);
      if (kind === "caesar") await this.flowCaesar(r, parseCaesar(r.query));
      else if (kind === "python") await this.flowPython(r, r.query);
      else if (kind === "weather") await this.flowWeather(r, r.query);
      else if (kind === "vaultlist") await this.flowVaultList(r);
      else if (kind === "chat") await this.flowChat(r);
      else await this.flowUnknown(r);
    } catch (err) {
      if (err instanceof Stopped) return;
      console.error(err);
      r.outcome = { ...r.outcome, status: "failed" };
    }
    const o = r.outcome;
    await this.emit(r, "run.finished", { status: o.status, summary: o.summary, summary_gold: o.gold, forged: o.forged, used: o.used }).catch(() => {});
    r.done = true;
  }

  /** planner() (line 1517). */
  private async planner(r: DemoRun, caption: string, logText: string, needs: "primitive" | "vault" | "forge" | null, tool: string | null) {
    await this.node(r, "planner", "active");
    await this.cap(r, "The Planner is splitting your request into sub-tasks and checking the vault.");
    await this.say(r, "Planning");
    await this.wait(r, 900);
    await this.node(r, "planner", "done");
    await this.emit(r, "plan.ready", { subtasks: needs ? [{ id: 1, action: r.query, needs, tool_hint: tool, depends_on: [] }] : [], verdict: "" });
    await this.line(r, "plan", logText);
    await this.cap(r, caption);
  }

  /** forgeTool() (line 1527). Returns the number of attempts. */
  private async forgeTool(r: DemoRun, spec: ForgeSpec): Promise<number> {
    const meta = spec.meta;
    await this.strip(r, "forge", "Sub-task 1 of 1, needs a new tool", sigOf(meta));
    await this.line(r, "vault", "no match");
    await this.wait(r, 400);
    await this.flowTo(r, "planner", "forger");
    await this.say(r, `Writing ${meta.name}`);
    for (let a = 0; a < spec.attempts.length; a++) {
      const att = spec.attempts[a]!;
      const n = a + 1;
      await this.node(r, "forger", "active");
      if (a > 0) await this.node(r, "tester", "forge");
      await this.cap(
        r,
        a === 0
          ? `The Forger is writing <span class="mono">${esc(meta.name)}</span> and its tests in one structured call.`
          : `<span class="gold">Attempt ${n} of 3.</span> The failing test and its traceback went back to the Forger.`,
      );
      await this.line(r, "forge", a === 0 ? `${meta.name}()` : `attempt ${n}`, "g");
      await this.emit(r, "forge.code", { tool: meta.name, attempt: n, file: `${meta.name}.py`, lines: att.lines, changed: att.changed ?? null, note: att.note ?? null, tests: spec.tests.length });
      if (a > 0) await this.wait(r, 1300);
      await this.node(r, "forger", "forge");
      await this.flowTo(r, "forger", "tester");
      await this.node(r, "tester", "active");
      await this.cap(r, `<span class="gold">Attempt ${n} of 3.</span> Running ${spec.tests.length} tests in a subprocess, 10-second limit.`);
      await this.line(r, "test", "running", "g", true);
      const fail = a === 0 && spec.failIdx >= 0 && spec.attempts.length > 1;
      await this.emit(r, "forge.tests", {
        tool: meta.name,
        attempt: n,
        results: spec.tests.map((name, i) => ({ name, passed: !(fail && i === spec.failIdx), why: fail && i === spec.failIdx ? spec.failWhy : null })),
      });
      await this.emit(r, "log.pop", {});
      if (fail) {
        const failing = spec.tests[spec.failIdx]!;
        await this.line(r, "test", `${spec.tests.length - 1} of ${spec.tests.length} passed, retrying`, "g");
        await this.line(r, "", failing, "sub");
        await this.emit(r, "forge.attempt", { attempt: n, ok: false, detail: `${failing}\n${spec.failWhy}` });
        await this.say(r, "The first attempt failed a test. Trying again");
        await this.wait(r, 700);
      } else {
        await this.line(r, "test", `${spec.tests.length} of ${spec.tests.length} passed`, "g");
        await this.emit(r, "forge.attempt", { attempt: n, ok: true, detail: `${spec.tests.length} of ${spec.tests.length} tests passed` });
      }
    }
    if (spec.smoke) {
      await this.cap(r, "Smoke test: the tool runs once on a real input before it can be saved.");
      await this.emit(r, "forge.smoke", { call: spec.smoke.call, result: spec.smoke.result, passed: true });
      await this.line(r, "smoke", spec.smoke.result);
      await this.wait(r, 400);
    }
    await this.node(r, "tester", "forge");
    await this.flowTo(r, "tester", "human");
    return spec.attempts.length;
  }

  /** humanCheck() (line 1595). Returns whether a key is available. */
  private async humanCheck(r: DemoRun, meta: ToolMeta): Promise<boolean> {
    if (!meta.env) {
      await this.node(r, "human", "skip");
      await this.cap(r, "No API key needed, so Human check passed straight through.");
      await this.wait(r, 450);
      await this.flowTo(r, "human", "learn");
      return true;
    }
    if (this.world.hasKey(meta.env)) {
      await this.node(r, "human", "skip");
      await this.cap(r, `<span class="mono">${esc(meta.env)}</span> is already set, so Human check passed straight through.`);
      await this.line(r, "check", "key already set");
      await this.wait(r, 450);
      await this.flowTo(r, "human", "learn");
      return true;
    }
    await this.node(r, "human", "active");
    await this.cap(r, `Human check paused the graph. <span class="mono">${esc(meta.name)}</span> needs <span class="mono">${esc(meta.env)}</span>.`);
    await this.line(r, "check", "waiting for a key", "g", true);
    await this.logStatus(r, "Waiting for you", true);
    await this.say(r, "The tool is written and tested. It needs an API key before it can run");
    await this.wait(r, 350);
    const res = await this.interrupt(r, { kind: "missing_api_key", payload: { env_var: meta.env, tool_name: meta.name, service: "OpenWeatherMap" } });
    const save = res.decision === "save";
    await this.emit(r, "interrupt.resolved", { kind: "missing_api_key", decision: save ? "save" : "skip" });
    await this.emit(r, "log.pop", {});
    if (save && res.decision === "save") {
      this.world.saveKey(meta.env, res.value);
      await this.line(r, "check", "key saved to .env");
      await this.node(r, "human", "done");
      await this.cap(r, `Saved <span class="mono">${esc(meta.env)}</span> to .env. Talos won't ask again.`);
    } else {
      await this.line(r, "check", "skipped by you");
      await this.node(r, "human", "done", "Human check, skipped");
      await this.cap(r, "You skipped the key. The tool is still saved, but it will fail until the key is set.");
    }
    await this.logStatus(r, "Forging", true);
    await this.wait(r, 500);
    await this.flowTo(r, "human", "learn");
    return save;
  }

  /** learn() (line 1639). */
  private async learn(r: DemoRun, meta: ToolMeta, sub: string) {
    await this.node(r, "learn", "active");
    await this.cap(r, "Learn is writing the .py file and its manifest entry.");
    await this.wait(r, 600);
    await this.node(r, "learn", "done");
    await this.line(r, "learn", "saved to the vault");
    await this.emit(r, "vault.saved", { tool: entryOf(meta), sub });
    await this.flowTo(r, "learn", "executor");
    await this.wait(r, 900);
  }

  /** flowCaesar() (line 1654). */
  private async flowCaesar(r: DemoRun, p: CaesarParams) {
    if (!this.findTool(CAESAR.name)) {
      await this.planner(r, "1 sub-task. Nothing in the vault matches, so it needs a new tool.", "1 sub-task, needs a new tool", "forge", CAESAR.name);
      await this.logStatus(r, "Forging", true);
      const src = SOURCES.caesar_cipher!;
      const bad = src.slice();
      bad[47] = "    effective_shift = shift";
      const attempts = await this.forgeTool(r, {
        meta: CAESAR,
        attempts: [{ lines: bad }, { lines: src, changed: 48, note: "Line 48 is new in attempt 2. Decrypt now shifts backwards instead of forwards." }],
        tests: ["test_encrypt_shifts_forward", "test_decrypt_reverses_encrypt", "test_preserves_case_and_spaces", "test_wraps_past_z", "test_rejects_unknown_mode"],
        failIdx: 1,
        failWhy: "AssertionError: 'HOZCG OUSBH' != 'TALOS AGENT'",
        smoke: { call: 'caesar_cipher(text="TALOS AGENT", shift=7, mode="encrypt")', result: "'AHSVZ HNLUA'" },
      });
      await this.humanCheck(r, CAESAR);
      await this.learn(r, CAESAR, "Next time a request needs a Caesar cipher, Talos skips forging and goes straight to Execute.");
      r.outcome.forged = [CAESAR.name];
      await this.executeCaesar(r, p, true, attempts);
      return;
    }
    await this.planner(
      r,
      `The Planner matched <span class="mono">caesar_cipher</span> on the keywords caesar, cipher and ${p.mode}. Nothing will be written or tested this time.`,
      "1 sub-task, in the vault",
      "vault",
      CAESAR.name,
    );
    await this.strip(r, "vault", "Sub-task 1 of 1, found in the vault", sigOf(CAESAR));
    await this.flowTo(r, "planner", "vault");
    await this.node(r, "vault", "done");
    await this.line(r, "vault", CAESAR.name);
    await this.logTone(r, "warm");
    await this.logStatus(r, "0 tools forged");
    await this.say(r, "Found caesar_cipher in the vault");
    await this.wait(r, 500);
    await this.flowTo(r, "vault", "skip");
    await this.wait(r, 350);
    await this.flowTo(r, "skip", "executor");
    await this.executeCaesar(r, p, false, 0);
  }

  /** executeCaesar() (line 1698). */
  private async executeCaesar(r: DemoRun, p: CaesarParams, afterForge: boolean, attempts: number) {
    r.outcome.used = [CAESAR.name];
    await this.node(r, "executor", "active");
    await this.cap(r, "The Executor is reading your message and filling in the arguments.");
    await this.say(r, "Running caesar_cipher");
    const shiftVal = p.shiftWord ? JSON.stringify(p.shiftWord) : String(p.shift);
    await this.emit(r, "call.args", {
      tool: CAESAR.name,
      args: [["text", JSON.stringify(p.text), false], ["shift", shiftVal, !!p.shiftWord], ["mode", JSON.stringify(p.mode), false]],
      caption: null,
    });
    await this.wait(r, 450);
    const now = nowIso();
    if (p.shiftWord) {
      const tool = this.findTool(CAESAR.name)!;
      const err = "TypeError: shift must be an int, got str";
      const streak = tool.streak + 1;
      const pruned = streak >= PRUNE_AT;
      await this.emit(r, "call.error", { error: err, when: fmtTime(now) });
      await this.node(r, "executor", "fail", "Executor failed");
      await this.line(r, "execute", "failed, TypeError", "w");
      await this.logTone(r, "alert");
      await this.logStatus(r, "1 step failed");
      await this.line(r, "vault", pruned ? `removed after ${PRUNE_AT} failures in a row` : `${streak} failure in a row`);
      await this.emit(r, "vault.failure", { tool: CAESAR.name, streak, pruned, error: err });
      await this.flowTo(r, "executor", "answer");
      await this.node(r, "answer", "answer");
      await this.cap(r, "The run still finished. Talos explained the failure instead of guessing a result.");
      r.outcome = { ...r.outcome, summary: pruned ? "Failed, removed from the vault" : "Failed, 1 failure in a row", gold: false };
      const digit = NUM_WORDS[p.shiftWord];
      await this.emit(r, "answer.done", {
        html: `I couldn't ${p.mode} that. <span class="mono">caesar_cipher</span> needs the shift as a number, and it was given the word "${esc(p.shiftWord)}".`,
        note: digit != null ? `Ask again with "shift ${digit}" and it should work.` : "Ask again with the shift as a number.",
        chips: [{ kind: "failed", text: "caesar_cipher raised a TypeError" }],
      });
      return;
    }
    const out = caesar(p.text, p.shift, p.mode);
    await this.emit(r, "call.result", { repr: pyStr(out), type: "str", small: false });
    await this.node(r, "executor", "done");
    await this.line(r, "execute", "done", "w");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    if (afterForge) {
      await this.logStatus(r, "1 tool forged", true);
      await this.cap(r, `Done in ${attempts} attempts. No API key was needed, so Human check passed straight through.`);
      r.outcome = { ...r.outcome, summary: `1 tool forged, ${attempts} attempts`, gold: true };
    } else {
      await this.cap(r, "Done from the vault. The forge sub-graph never ran.");
      r.outcome = { ...r.outcome, summary: "0 tools forged", gold: false };
    }
    const html =
      p.mode === "encrypt"
        ? `"${esc(p.text)}" encrypted with a shift of ${p.shift} is <span class="mono">${esc(out)}</span>.`
        : `It decrypts to <span class="mono">${esc(out)}</span>.`;
    const note = afterForge
      ? p.mode === "encrypt"
        ? 'The same tool decrypts too. Ask with "decrypt" and the same shift.'
        : 'The same tool encrypts too. Ask with "encrypt" and the same shift.'
      : null;
    await this.emit(r, "answer.done", {
      html,
      note,
      chips: [{ kind: afterForge ? "forged" : "reused", text: afterForge ? "Forged caesar_cipher" : "Reused caesar_cipher from the vault" }],
    });
  }

  /** flowPython() (line 1779). */
  private async flowPython(r: DemoRun, q: string) {
    const m = q.match(/`([^`]+)`/) || q.match(/:\s*(.+)$/);
    const code = (m?.[1] ?? "print(sum(range(1, 101)))").trim();
    await this.planner(r, "1 sub-task, a built-in primitive. Nothing needs forging.", "1 sub-task, primitive", "primitive", "python_exec");
    await this.strip(r, "primitive", "Sub-task 1 of 1, built-in primitive", { name: "python_exec", args: "code: str, timeout: int | None = None", ret: "dict" });
    await this.flowTo(r, "planner", "primitive");
    await this.node(r, "primitive", "done");
    await this.flowTo(r, "primitive", "executor");
    await this.emit(r, "call.args", { tool: "python_exec", args: [["code", JSON.stringify(code), false]], caption: "Written by the Executor" });
    let approved = true;
    if (this.world.askExec()) {
      await this.node(r, "executor", "active", "Executor, waiting for you");
      await this.cap(r, 'The Executor paused. <span class="mono">python_exec</span> runs code on your machine, so it asks first.');
      await this.line(r, "execute", "paused for approval", "g", true);
      await this.logStatus(r, "Waiting for you", true);
      await this.say(r, "Waiting for you to approve the code");
      await this.wait(r, 350);
      const res = await this.interrupt(r, { kind: "confirm_exec", payload: { tool: "python_exec", preview: code } });
      approved = res.decision === "approve";
      await this.emit(r, "interrupt.resolved", { kind: "confirm_exec", decision: approved ? "approve" : "decline" });
      await this.emit(r, "log.pop", {});
    } else {
      await this.node(r, "executor", "active");
      await this.cap(r, 'Ran without asking, because "Ask before running code" is off in Settings.');
    }
    if (!approved) {
      await this.node(r, "executor", "fail", "Executor, declined");
      await this.line(r, "execute", "declined by you", "w");
      await this.logStatus(r, "Not run");
      await this.emit(r, "call.error", { error: "declined by user", when: "You chose Don't run" });
      await this.flowTo(r, "executor", "answer");
      await this.node(r, "answer", "answer");
      await this.cap(r, "Nothing ran. The sub-task is recorded as declined.");
      r.outcome = { ...r.outcome, status: "declined", summary: "Declined, nothing ran" };
      await this.emit(r, "answer.done", { html: "I didn't run the code, so I don't have its output.", note: "Approve it next time, or turn off the prompt in Settings.", chips: [] });
      return;
    }
    await this.line(r, "execute", "running", "g", true);
    await this.wait(r, 700);
    await this.emit(r, "log.pop", {});
    const out = runPython(code);
    await this.emit(r, "call.result", out == null ? { repr: "The demo only runs simple print() calls.", type: "", small: true } : { repr: out, type: "stdout", small: false });
    await this.node(r, "executor", "done", "Executor");
    await this.line(r, "execute", "done", "w");
    await this.logStatus(r, "0 tools forged");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    await this.cap(r, "Done. Primitives go straight to the Executor, so nothing was forged.");
    r.outcome = { ...r.outcome, summary: "Built-in, approved" };
    await this.emit(r, "answer.done", {
      html: out == null ? 'This demo can only run simple <span class="mono">print()</span> calls, so there\'s no output to show.' : `The code prints <span class="mono">${esc(out)}</span>.`,
      note: null,
      chips: [],
    });
  }

  /** flowWeather() (line 1840). */
  private async flowWeather(r: DemoRun, q: string) {
    const cityM = q.match(/\bin ([A-Z][A-Za-z .'-]+?)(?:[.?!]|$)/);
    const city = cityM ? (cityM[1] ?? "").trim() : "Mumbai";
    const env = WEATHER.env!;
    let hasKey = this.world.hasKey(env);
    let forged = false;
    if (!this.findTool(WEATHER.name)) {
      await this.planner(r, "1 sub-task. Nothing in the vault fetches weather, so it needs a new tool.", "1 sub-task, needs a new tool", "forge", WEATHER.name);
      await this.logStatus(r, "Forging", true);
      await this.forgeTool(r, {
        meta: WEATHER,
        attempts: [{ lines: SOURCES.get_current_temperature! }],
        tests: ["test_reads_temperature_from_response", "test_raises_when_key_missing", "test_raises_on_unknown_city"],
        failIdx: -1,
        failWhy: "",
        smoke: null,
      });
      hasKey = await this.humanCheck(r, WEATHER);
      await this.learn(r, WEATHER, "Next time you ask about the weather, Talos reuses it. It reads the key from .env.");
      forged = true;
      r.outcome.forged = [WEATHER.name];
    } else {
      await this.planner(r, `The Planner matched <span class="mono">${WEATHER.name}</span> in the vault.`, "1 sub-task, in the vault", "vault", WEATHER.name);
      await this.strip(r, "vault", "Sub-task 1 of 1, found in the vault", sigOf(WEATHER));
      await this.flowTo(r, "planner", "vault");
      await this.node(r, "vault", "done");
      await this.line(r, "vault", WEATHER.name);
      await this.logTone(r, "warm");
      await this.logStatus(r, "0 tools forged");
      await this.wait(r, 400);
      await this.flowTo(r, "vault", "skip");
      await this.wait(r, 300);
      await this.flowTo(r, "skip", "executor");
    }
    r.outcome.used = [WEATHER.name];
    await this.node(r, "executor", "active");
    await this.cap(r, "The Executor is filling in the arguments.");
    await this.emit(r, "call.args", { tool: WEATHER.name, args: [["city", JSON.stringify(city), false]], caption: null });
    await this.wait(r, 500);
    const now = nowIso();
    if (!hasKey) {
      const tool = this.findTool(WEATHER.name)!;
      const err = "RuntimeError: OPENWEATHERMAP_API_KEY is not set";
      const streak = tool.streak + 1;
      const pruned = streak >= PRUNE_AT;
      await this.emit(r, "call.error", { error: err, when: fmtTime(now) });
      await this.emit(r, "vault.failure", { tool: WEATHER.name, streak, pruned, error: err });
      await this.node(r, "executor", "fail", "Executor failed");
      await this.line(r, "execute", "failed, RuntimeError", "w");
      await this.logTone(r, "alert");
      await this.logStatus(r, "1 step failed");
      await this.flowTo(r, "executor", "answer");
      await this.node(r, "answer", "answer");
      await this.cap(r, "The tool ran without its key and raised an error.");
      r.outcome = { ...r.outcome, summary: forged ? "1 tool forged, failed without a key" : "Failed without a key", gold: forged };
      await this.emit(r, "answer.done", {
        html: `I couldn't get the temperature. <span class="mono">${WEATHER.name}</span> needs <span class="mono">${env}</span>, and it isn't set.`,
        note: "Ask again and paste the key when Human check asks for it.",
        chips: [{ kind: "failed", text: `${WEATHER.name} raised a RuntimeError` }],
      });
      return;
    }
    await this.emit(r, "call.result", { repr: "Not called in this demo", type: "", small: true });
    await this.node(r, "executor", "done");
    await this.line(r, "execute", "done (demo stops before the API)", "w");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    if (forged) {
      await this.logStatus(r, "1 tool forged", true);
      r.outcome = { ...r.outcome, summary: "1 tool forged, key saved", gold: true };
    } else r.outcome = { ...r.outcome, summary: "0 tools forged", gold: false };
    await this.cap(r, "Done. In Talos the Executor would call OpenWeatherMap here with your key.");
    await this.emit(r, "answer.done", {
      html: "The tool is ready and your key is saved. This demo can't reach the internet, so it stops before calling OpenWeatherMap.",
      note: `In Talos, you'd get the current temperature in ${esc(city)} here.`,
      chips: [{ kind: forged ? "forged" : "reused", text: forged ? `Forged ${WEATHER.name}` : `Reused ${WEATHER.name} from the vault` }],
    });
  }

  /** flowVaultList() (line 1909). */
  private async flowVaultList(r: DemoRun) {
    await this.planner(r, '1 sub-task, a built-in primitive: <span class="mono">vault_list</span>.', "1 sub-task, primitive", "primitive", "vault_list");
    await this.strip(r, "primitive", "Sub-task 1 of 1, built-in primitive", { name: "vault_list", args: "", ret: "list[dict]" });
    await this.flowTo(r, "planner", "primitive");
    await this.node(r, "primitive", "done");
    await this.flowTo(r, "primitive", "executor");
    await this.node(r, "executor", "active");
    await this.emit(r, "call.args", { tool: "vault_list", args: [], caption: "Takes no arguments" });
    await this.wait(r, 700);
    const tools = this.world.tools();
    const n = tools.length;
    const top = tools.slice().sort((a, b) => b.uses - a.uses).slice(0, 2);
    await this.emit(r, "call.result", { repr: `${n} tools`, type: "list[dict]", small: false });
    await this.node(r, "executor", "done");
    await this.line(r, "execute", "done", "w");
    await this.logStatus(r, "0 tools forged");
    await this.flowTo(r, "executor", "answer");
    await this.node(r, "answer", "answer");
    await this.cap(r, "Done. Talos read its own manifest.");
    r.outcome = { ...r.outcome, summary: "Built-in" };
    await this.emit(r, "answer.done", {
      html: `There are ${n} tools in the vault. The most used are <span class="mono">${esc(top[0]!.name)}</span> and <span class="mono">${esc(top[1]!.name)}</span>, with ${top[0]!.uses} uses each.`,
      note: 'Open <a href="#vault">the Vault</a> to see all of them.',
      chips: [],
    });
  }

  /** flowChat() (line 1930). */
  private async flowChat(r: DemoRun) {
    await this.planner(r, "The Planner returned an empty plan. There's nothing to run, so Talos answers directly.", "no sub-tasks, answering directly", null, null);
    await this.strip(r, "chat", "Conversational", null);
    await this.flowTo(r, "planner", "answer");
    await this.node(r, "answer", "answer");
    await this.logStatus(r, "0 tools forged");
    r.outcome = { ...r.outcome, summary: "Answered directly" };
    await this.emit(r, "answer.done", {
      html: `I split your request into steps, then use a built-in tool, reuse one from my vault, or write and test a new Python tool for whatever's missing. The vault holds ${this.world.tools().length} tools right now.`,
      note: "Try asking me to build a Caesar cipher.",
      chips: [],
    });
  }

  /** flowUnknown() (line 1940). */
  private async flowUnknown(r: DemoRun) {
    await this.planner(r, "This demo only replays a few scripted runs, so the Planner stops here.", "not in this demo", null, null);
    await this.strip(r, "chat", "Scripted demo", null, "Not in this demo");
    await this.flowTo(r, "planner", "answer");
    await this.node(r, "answer", "answer");
    await this.logStatus(r, "Nothing ran");
    r.outcome = { ...r.outcome, summary: "Not in this demo" };
    await this.emit(r, "answer.done", {
      html: "This demo can't plan that one. It replays a few scripted runs over the real vault. Try one of these:",
      note: null,
      chips: [],
      suggest: true,
    });
  }
}
```

- [ ] **Step 4: Run the tests (the golden files are written on the first run)**

Run: `npx vitest run src/transport/demo.test.tsx`
Expected: PASS, and five files appear under `src/transport/__golden__/`. Open `caesar-forge.json` and check it reads like the reference's `flowCaesar`: `run.started`, `log.cmd`, the planner, `strip.set`, two `forge.code` attempts with the failing test in between, the smoke test, Human check skipped, Learn, the executor and `answer.done`, ending with `run.finished`.

Run again: `npx vitest run src/transport && npm run lint && npm run typecheck`
Expected: PASS (the golden files now match).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/transport/demo.ts frontend/src/transport/demo.test.tsx frontend/src/transport/__golden__
git commit -m "[Feat]: Add DemoTransport: the reference's scripted flows as contract events"
```

---

### Task 15: Controller, services, mode and the app shell

**Files:**
- Create: `frontend/src/mode.ts`, `frontend/src/services.ts`, `frontend/src/app/workbench.ts`, `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx` (replace the Task 1 placeholder)
- Test: `frontend/src/app/workbench.test.ts`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: everything above.
- Produces (part B's seams):
  - `mode.ts`: `Mode = "demo" | "live"`, `resolveMode(search?: string, flag?: string): Mode` (demo when `?demo` is in the query or `VITE_DEMO=1`).
  - `services.ts`: `Services = { mode: Mode; data: DataSource; transport: Transport; demo: DemoTransport | null; lastRunNumber: number }`, `createServices(mode: Mode): Promise<{ stores: Stores; services: Services }>`, `demoWorld(stores: Stores): DemoWorld`. Part B makes `createServices("live")` build the live data source and transport; in part A it returns the demo ones for both modes (ruling 12).
  - `app/workbench.ts`: `class Workbench` with `submit(text)`, `submitDraft()`, `stop()`, `answerApproval(a: "yes" | "no" | "cancel")`, `answerKey(r)`, `closeReader()`, `selectTab(tab)`, `viewRun(n)`, `newSession()`, `openSession(id)`, `backToNow()`, `showView(hash)`, `setDraft(v)`, `setQuery(q)`, `setFilter(f)`, `selectTool(name)`, `fallbackSelect(name)`, `readSource(name)`, `loadSource(name)`, `useTool(name)`, `removeTool(name)`, `openTool(name)`, `toggleAskExec()`, `togglePop(open?)`, `setSpeed(s)`, `reset()`. Every guard is the reference's.
  - `App({ stores, workbench })`.

Controller rules, each the reference's handler (lines 2078–2202, 2280–2289):

| Method | Reference | Behaviour |
|---|---|---|
| `submit` | 1450–1484 | ignore empty text, a busy app, or an old session being read; `busy` on at once; go to `#workbench`; `startRun`; rename the session when `sessionName` comes back (`titleAnimate`); new `Player` (`momentDwell: mode !== "demo"`); bump `benchKey`; subscribe |
| `stop` | 1485–1500 | only while busy: `player.abort()`, close any dialog, `transport.stop` |
| `answerApproval` / `answerKey` | 1382–1419, 1799–1801, 1618–1628 | close the dialog; cancel → `stop()`; else `resume` with `approve`/`decline` or `save`/`skip` |
| `selectTab` | 2101–2102 | on the viewed run: `codeScroll = null`, then the tab |
| `viewRun` | 2105–2110 | ignored while busy; a run of the shown session; bump `benchKey`; bench scrolled to the top |
| `newSession` | 2143, 2157–2167 | ignored while busy; leave an old session first; `data.newSession(count + 1)`; `openNewSession`; no current or viewed run; `titleAnimate = booted`; bump `benchKey` |
| `openSession` / `backToNow` | 2178–2202 | ignored while busy; `#workbench`; the current session means back to now; the last run is viewed (or idle); `titleAnimate`; bump `benchKey` |
| `showView` | 2078–2089 | unknown views mean workbench; a change bumps `viewEnter`; the vault clears the badge, resets the remove confirm, staggers on a change (and doesn't when not changed) and bumps `vaultRender` |
| `setQuery`, `selectTool`, `removeTool` (second click) | 2138, 2111–2112, 2124–2130 | not staggered, `vaultRender` bumped, confirm reset; a selected tool's name button gets focus; removal drops the tool, clears the selection and calls `data.removeTool` |
| `setFilter` | 2140 | staggered, `vaultRender` bumped, confirm reset |
| `removeTool` (first click) | 2127 | `confirmRemove = name` only |
| `useTool` | 2115–2123 | `#workbench`; the preset or `Use {name} on `; after 30 ms focus `#ask` with the caret at the end |
| `openTool` | 2103–2104 | `selected = name` (the link's `href="#vault"` does the navigation) |
| `readSource` | 2113–2114 | opens the reader only when the tool has a source |
| `toggleAskExec` | 2131 | flip `askExec`, tell the data source |
| `reset` | 2280–2289 | `demo.reset(lastRunNumber)` first, dispose every player, reload the data source, a new "Session 1"; keep `view`, `viewEnter`, `speed` and the live region; `booted` stays on, `titleAnimate` on; bump `benchKey` and `vaultRender` |

- [ ] **Step 1: Write the failing tests**

`frontend/src/app/workbench.test.ts`:

```ts
import { createServices } from "../services";
import { FIXED_NOW } from "../test/parity";
import { Workbench } from "./workbench";

async function boot() {
  const { stores, services } = await createServices("demo");
  return { stores, services, wb: new Workbench(stores, services) };
}
async function settle(stores: Awaited<ReturnType<typeof boot>>["stores"]) {
  for (let i = 0; i < 5000 && stores.ui.get().busy; i++) await vi.advanceTimersToNextTimerAsync();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
  window.location.hash = "";
});
afterEach(() => vi.useRealTimers());

test("boot state is the reference's", async () => {
  const { stores } = await boot();
  const s = stores.session.get();
  expect(s.sessions.map((x) => x.id)).toEqual(["seed-fib", "seed-lev", "seed-b64", s.curId]);
  expect(s.sessions.at(-1)!.name).toBe("Session 1");
  expect(stores.vault.get().tools).toHaveLength(40);
  expect(stores.ui.get()).toMatchObject({ view: "workbench", busy: false, selected: "caesar_cipher", speed: 1 });
});

test("submit guards: whitespace, busy, reading an old session", async () => {
  const { stores, wb } = await boot();
  await wb.submit("   ");
  expect(stores.ui.get().busy).toBe(false);
  await wb.submit("What can you do?");
  await wb.submit("What can you do?"); // while busy
  await settle(stores);
  expect(Object.values(stores.runs.get().byId).filter((r) => !r.seeded)).toHaveLength(1);
  expect(stores.session.get().sessions.at(-1)!.name).toBe("Getting to know Talos");
  wb.openSession("seed-fib");
  await wb.submit("What can you do?");
  expect(Object.values(stores.runs.get().byId).filter((r) => !r.seeded)).toHaveLength(1);
});

test("reset drops the old run's late events", async () => {
  const { stores, wb } = await boot();
  await wb.submit('Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.');
  await vi.advanceTimersByTimeAsync(500);
  await wb.reset();
  await vi.advanceTimersByTimeAsync(60000);
  const s = stores.session.get();
  expect(s.sessions.map((x) => x.name)).toEqual(["Fibonacci tools", "Edit distance", "Base64 round trip", "Session 1"]);
  expect(s.sessions.at(-1)!.messages).toEqual([]);
  expect(stores.ui.get()).toMatchObject({ busy: false, viewingRunId: null, currentRunId: null, badge: false });
  expect(stores.vault.get().tools.some((t) => t.name === "caesar_cipher")).toBe(false);
  await wb.submit("What can you do?");
  await settle(stores);
  expect(Object.values(stores.runs.get().byId).find((r) => !r.seeded)!.n).toBe(6);
});

test("new session drops an empty current session; old sessions open read-only", async () => {
  const { stores, wb } = await boot();
  await wb.newSession();
  expect(stores.session.get().sessions.map((x) => x.name)).toEqual(["Fibonacci tools", "Edit distance", "Base64 round trip", "Session 2"]);
  wb.openSession("seed-lev");
  expect(stores.session.get().viewId).toBe("seed-lev");
  expect(stores.runs.get().byId[stores.ui.get().viewingRunId!]!.n).toBe(4);
  wb.backToNow();
  expect(stores.session.get().viewId).toBeNull();
  expect(stores.ui.get().viewingRunId).toBeNull();
});

test("vault actions: filter staggers, remove asks first, use prefills", async () => {
  const { stores, wb } = await boot();
  wb.showView("vault");
  expect(stores.ui.get()).toMatchObject({ view: "vault", stagger: true, badge: false });
  wb.setQuery("hex");
  expect(stores.ui.get().stagger).toBe(false);
  wb.setFilter("web");
  expect(stores.ui.get().stagger).toBe(true);
  wb.removeTool("hex_to_rgb");
  expect(stores.ui.get().confirmRemove).toBe("hex_to_rgb");
  wb.removeTool("hex_to_rgb");
  expect(stores.vault.get().tools.some((t) => t.name === "hex_to_rgb")).toBe(false);
  expect(stores.ui.get()).toMatchObject({ confirmRemove: null, selected: null });
  wb.useTool("slugify");
  expect(stores.ui.get().draft).toBe("Use slugify on ");
  wb.useTool("caesar_cipher");
  expect(stores.ui.get().draft).toBe('Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"');
});

test("Ask before running code off runs python without a dialog", async () => {
  const { stores, wb } = await boot();
  wb.toggleAskExec();
  await wb.submit("Run this Python code and give me the output: print(sum(range(1, 101)))");
  await settle(stores);
  const run = Object.values(stores.runs.get().byId).find((r) => !r.seeded)!;
  expect(run.caption).toBe("Done. Primitives go straight to the Executor, so nothing was forged.");
  expect(run.call!.result).toBe("5050");
});
```

`frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { App } from "./App";
import { Workbench } from "./app/workbench";
import { resolveMode } from "./mode";
import { createServices } from "./services";

test("resolveMode", () => {
  expect(resolveMode("?demo", undefined)).toBe("demo");
  expect(resolveMode("", "1")).toBe("demo");
  expect(resolveMode("", undefined)).toBe("live");
});

test("demo mode shows the Demo controls; live mode doesn't", async () => {
  for (const mode of ["demo", "live"] as const) {
    const { stores, services } = await createServices(mode);
    const { unmount } = render(<App stores={stores} workbench={new Workbench(stores, services)} />);
    expect(screen.getByText("Ask for something it can't do yet")).toBeInTheDocument();
    expect(screen.queryByText("Demo controls") !== null).toBe(mode === "demo");
    unmount();
  }
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/app src/App.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write `mode.ts` and `services.ts`**

`frontend/src/mode.ts`:

```ts
export type Mode = "demo" | "live";

/** `/?demo` or a build with VITE_DEMO=1 runs the scripted demo (spec 04 §8.3). */
export function resolveMode(search: string = window.location.search, flag: string | undefined = import.meta.env.VITE_DEMO): Mode {
  return flag === "1" || new URLSearchParams(search).has("demo") ? "demo" : "live";
}
```

`frontend/src/services.ts`:

```ts
import type { DataSource } from "./data/source";
import { createDemoDataSource } from "./demo/source";
import type { Mode } from "./mode";
import { createStores, type Stores } from "./store/stores";
import { DemoTransport, type DemoWorld } from "./transport/demo";
import type { Transport } from "./transport/types";

export interface Services {
  mode: Mode;
  data: DataSource;
  transport: Transport;
  demo: DemoTransport | null;
  lastRunNumber: number;
}

export function demoWorld(stores: Stores): DemoWorld {
  return {
    tools: () => stores.vault.get().tools,
    hasKey: (env) => !!stores.settings.get().env[env],
    saveKey: (env, value) => stores.settings.update((s) => ({ ...s, env: { ...s.env, [env]: value } })),
    askExec: () => stores.settings.get().askExec,
    speed: () => stores.ui.get().speed,
    sessionRunCount: (sid) => stores.session.get().sessions.find((s) => s.id === sid)?.runIds.length ?? 0,
  };
}

/** The seam part B changes: live mode gets the API data source and LiveTransport. Ruling 12. */
export async function createServices(mode: Mode): Promise<{ stores: Stores; services: Services }> {
  const data = createDemoDataSource();
  const [tools, settings, past] = await Promise.all([data.vault(), data.settings(), data.sessions()]);
  const current = await data.newSession(1);
  const stores = createStores({ tools, settings, sessions: past.sessions, runs: past.runs, current, count: 1 });
  const demo = new DemoTransport(demoWorld(stores), { lastRunNumber: past.lastRunNumber });
  return { stores, services: { mode, data, transport: demo, demo, lastRunNumber: past.lastRunNumber } };
}
```

Add `frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_DEMO?: string;
}
```

- [ ] **Step 4: Write `frontend/src/app/workbench.ts`**

```ts
import { USE_PRESETS } from "../demo/data";
import { COPY, fill } from "../lib/copy";
import { initialStates, updateRun, type Stores } from "../store/stores";
import { curSession, openNewSession, rename, shownSession } from "../store/sessionOps";
import type { TabId, UiState, View } from "../store/types";
import { removeTool as dropTool } from "../store/vaultOps";
import type { Services } from "../services";
import { Player } from "../transport/player";

const VIEWS: View[] = ["workbench", "vault", "sessions", "settings"];

/** Every user action, with the reference's guards. Components call these; nothing else writes stores. */
export class Workbench {
  private players = new Map<string, Player>();

  constructor(
    private readonly stores: Stores,
    private readonly services: Services,
  ) {}

  get mode() {
    return this.services.mode;
  }

  private ui = (patch: Partial<UiState>) => this.stores.ui.set(patch);

  async submit(raw: string): Promise<void> {
    const text = raw.trim();
    const ui = this.stores.ui.get();
    if (!text || ui.busy || this.stores.session.get().viewId) return;
    this.ui({ busy: true });
    if (ui.view !== "workbench") window.location.hash = "workbench";
    const sid = this.stores.session.get().curId;
    const started = await this.services.transport.startRun(sid, text);
    const name = started.sessionName;
    if (name) {
      this.stores.session.update((s) => rename(s, sid, name));
      this.ui({ titleAnimate: true });
    }
    const player = new Player(this.stores, {
      runId: started.runId,
      sessionId: sid,
      momentDwell: this.services.mode !== "demo",
      source: (tool) => this.services.data.toolSource(tool),
    });
    this.players.set(started.runId, player);
    this.ui({ benchKey: this.stores.ui.get().benchKey + 1 });
    this.services.transport.subscribe(started.runId, player.push);
  }

  stop(): void {
    const { currentRunId: id, busy } = this.stores.ui.get();
    if (!id || !busy) return;
    this.players.get(id)?.abort();
    this.ui({ dialog: null });
    void this.services.transport.stop(id);
  }

  answerApproval(action: "yes" | "no" | "cancel"): void {
    const d = this.stores.ui.get().dialog;
    if (d?.kind !== "approval") return;
    this.ui({ dialog: null });
    if (action === "cancel") return this.stop();
    void this.services.transport.resume(d.runId, { decision: action === "yes" ? "approve" : "decline" });
  }

  answerKey(r: { action: "save"; value: string } | { action: "skip" } | { action: "cancel" }): void {
    const d = this.stores.ui.get().dialog;
    if (d?.kind !== "key") return;
    this.ui({ dialog: null });
    if (r.action === "cancel") return this.stop();
    void this.services.transport.resume(d.runId, r.action === "save" ? { decision: "save", value: r.value } : { decision: "skip" });
  }

  closeReader(): void {
    if (this.stores.ui.get().dialog?.kind === "reader") this.ui({ dialog: null });
  }

  selectTab(tab: TabId): void {
    const id = this.stores.ui.get().viewingRunId;
    if (id) updateRun(this.stores, id, (r) => ({ ...r, codeScroll: null, tab }));
  }

  viewRun(n: number): void {
    if (this.stores.ui.get().busy) return;
    const shown = shownSession(this.stores.session.get());
    const id = shown.runIds.find((rid) => this.stores.runs.get().byId[rid]?.n === n);
    if (!id) return;
    this.ui({ viewingRunId: id, benchKey: this.stores.ui.get().benchKey + 1 });
    const bench = document.getElementById("bench");
    if (bench) bench.scrollTop = 0;
  }

  async newSession(): Promise<void> {
    if (this.stores.ui.get().busy) return;
    if (this.stores.session.get().viewId) this.backToNow();
    const rec = await this.services.data.newSession(this.stores.session.get().count + 1);
    this.stores.session.update((s) => openNewSession(s, rec));
    const ui = this.stores.ui.get();
    this.ui({ currentRunId: null, viewingRunId: null, titleAnimate: ui.booted, benchKey: ui.benchKey + 1 });
  }

  openSession(id: string): void {
    if (this.stores.ui.get().busy) return;
    const ss = this.stores.session.get();
    const sess = ss.sessions.find((x) => x.id === id);
    if (!sess) return;
    window.location.hash = "workbench";
    if (id === ss.curId) return this.backToNow();
    this.stores.session.set({ viewId: id });
    this.ui({ viewingRunId: sess.runIds.at(-1) ?? null, titleAnimate: true, benchKey: this.stores.ui.get().benchKey + 1 });
  }

  backToNow(): void {
    const ss = this.stores.session.get();
    if (!ss.viewId) return;
    this.stores.session.set({ viewId: null });
    this.ui({ viewingRunId: curSession(ss).runIds.at(-1) ?? null, titleAnimate: true, benchKey: this.stores.ui.get().benchKey + 1 });
  }

  showView(hash: string): void {
    const v = (VIEWS as string[]).includes(hash) ? (hash as View) : "workbench";
    const ui = this.stores.ui.get();
    const changed = ui.view !== v;
    const patch: Partial<UiState> = { view: v };
    if (changed) patch.viewEnter = ui.viewEnter + 1;
    if (v === "vault") Object.assign(patch, { badge: false, stagger: changed, vaultRender: ui.vaultRender + 1, confirmRemove: null });
    this.ui(patch);
  }

  setDraft(v: string): void {
    this.ui({ draft: v });
  }

  /** The composer's submit (line 2092): it always clears the box, then submits what was in it. */
  submitDraft(): Promise<void> {
    const v = this.stores.ui.get().draft;
    this.ui({ draft: "" });
    return this.submit(v);
  }

  private rerenderVault(stagger: boolean, patch: Partial<UiState> = {}): void {
    this.ui({ ...patch, stagger, vaultRender: this.stores.ui.get().vaultRender + 1, confirmRemove: null });
  }
  setQuery(q: string): void {
    this.rerenderVault(false, { query: q });
  }
  setFilter(f: UiState["filter"]): void {
    this.rerenderVault(true, { filter: f });
  }
  selectTool(name: string): void {
    this.rerenderVault(false, { selected: name });
    setTimeout(() => document.querySelector<HTMLElement>(`[data-tool-btn="${name}"]`)?.focus(), 0);
  }
  fallbackSelect(name: string | null): void {
    this.ui({ selected: name });
  }
  openTool(name: string): void {
    this.ui({ selected: name });
  }

  async loadSource(name: string): Promise<string[] | null> {
    const cached = this.stores.vault.get().sources[name];
    if (cached !== undefined) return cached;
    const lines = await this.services.data.toolSource(name);
    this.stores.vault.update((v) => ({ ...v, sources: { ...v.sources, [name]: lines } }));
    return lines;
  }
  async readSource(name: string): Promise<void> {
    const lines = await this.loadSource(name);
    if (lines) this.ui({ dialog: { kind: "reader", name, lines } });
  }

  useTool(name: string): void {
    window.location.hash = "workbench";
    this.ui({ draft: USE_PRESETS[name] ?? fill(COPY.vault.usePrefill, { name }) });
    setTimeout(() => {
      const ta = document.getElementById("ask") as HTMLTextAreaElement | null;
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
    }, 30);
  }

  removeTool(name: string): void {
    if (this.stores.ui.get().confirmRemove !== name) {
      this.ui({ confirmRemove: name });
      return;
    }
    this.stores.vault.update((v) => ({ ...v, tools: dropTool(v.tools, name) }));
    void this.services.data.removeTool(name);
    this.rerenderVault(false, { selected: null });
  }

  toggleAskExec(): void {
    const on = !this.stores.settings.get().askExec;
    this.stores.settings.set({ askExec: on });
    void this.services.data.setAskBeforeExec(on);
  }

  togglePop(open?: boolean): void {
    this.ui({ popOpen: open ?? !this.stores.ui.get().popOpen });
  }
  setSpeed(speed: number): void {
    this.ui({ speed });
  }

  async reset(): Promise<void> {
    this.services.demo?.reset(this.services.lastRunNumber);
    for (const p of this.players.values()) p.dispose();
    this.players.clear();
    const data = this.services.data;
    const [tools, settings, past] = await Promise.all([data.vault(), data.settings(), data.sessions()]);
    const current = await data.newSession(1);
    const fresh = initialStates({ tools, settings, sessions: past.sessions, runs: past.runs, current, count: 1 });
    const ui = this.stores.ui.get();
    this.stores.runs.dispatch({ type: "reset", state: fresh.runs });
    this.stores.session.dispatch({ type: "reset", state: fresh.session });
    this.stores.vault.dispatch({ type: "reset", state: fresh.vault });
    this.stores.settings.dispatch({ type: "reset", state: fresh.settings });
    this.stores.ui.dispatch({
      type: "reset",
      state: {
        ...fresh.ui, view: ui.view, viewEnter: ui.viewEnter, speed: ui.speed, live: ui.live, booted: true, titleAnimate: true,
        benchKey: ui.benchKey + 1, vaultRender: ui.vaultRender + 1,
      },
    });
  }
}
```

- [ ] **Step 5: Write `frontend/src/App.tsx`**

The shell is lines 596–691: `.app` with the header and the four view sections, then `#modal-root`. Each container reads the stores with the selectors rule and passes callbacks to the Workbench.

```tsx
import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import { Header } from "./components/Header";
import { ModalRoot } from "./components/dialogs/ModalRoot";
import { SessionsView } from "./components/sessions/SessionsView";
import { SettingsView } from "./components/settings/SettingsView";
import { VaultView } from "./components/vault/VaultView";
import { Bench } from "./components/workbench/Bench";
import { Conversation } from "./components/workbench/Conversation";
import { Idle } from "./components/workbench/Idle";
import { earlierData, Panel } from "./components/workbench/panels/Panel";
import { SUGGESTIONS } from "./demo/data";
import { usePointerGlow } from "./hooks/usePointerGlow";
import { COPY, fill } from "./lib/copy";
import type { Workbench } from "./app/workbench";
import { curSession, shownSession } from "./store/sessionOps";
import { StoresProvider, useRuns, useSession, useSettings, useStores, useUi, useVault, type Stores } from "./store/stores";
import type { View } from "./store/types";
import { findTool } from "./store/vaultOps";

export function App({ stores, workbench }: { stores: Stores; workbench: Workbench }) {
  return (
    <StoresProvider stores={stores}>
      <Shell wb={workbench} />
    </StoresProvider>
  );
}

function Shell({ wb }: { wb: Workbench }) {
  usePointerGlow();
  const busy = useUi((u) => u.busy);
  const wasBusy = useRef(busy);
  useEffect(() => {
    wb.showView(window.location.hash.slice(1) || "workbench");
    const onHash = () => wb.showView(window.location.hash.slice(1));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [wb]);
  const stores = useStores();
  useEffect(() => stores.ui.set({ booted: true }), [stores]);
  useEffect(() => {
    // setBusy(false) refocuses the composer on wide screens (line 1505).
    if (wasBusy.current && !busy && window.matchMedia("(min-width: 821px)").matches) document.getElementById("ask")?.focus({ preventScroll: true });
    wasBusy.current = busy;
  }, [busy]);
  return (
    <>
      <div className="app">
        <HeaderC wb={wb} />
        <div className="views">
          <ViewSection name="workbench" label={COPY.nav.workbench}>
            <div className="wb">
              <ConversationC wb={wb} />
              <BenchC wb={wb} />
            </div>
          </ViewSection>
          <ViewSection name="vault" label={COPY.nav.vault}>
            <VaultC wb={wb} />
          </ViewSection>
          <ViewSection name="sessions" label={COPY.nav.sessions}>
            <div className="sessions">
              <div className="sessions-in" id="sessions-in">
                <SessionsC wb={wb} />
              </div>
            </div>
          </ViewSection>
          <ViewSection name="settings" label={COPY.nav.settings}>
            <div className="settings">
              <div className="settings-in" id="settings-in">
                <SettingsC wb={wb} />
              </div>
            </div>
          </ViewSection>
        </div>
      </div>
      <div id="modal-root">
        <ModalC wb={wb} />
      </div>
    </>
  );
}
```

Finish the file with these containers (all short; write them out in full):

- `ViewSection({ name, label, children })`: `<section className="view" id={\`view-${name}\`} aria-label={label} hidden={view !== name} ref={ref}>`; a `useLayoutEffect` on `viewEnter` that, when `view === name && viewEnter > 0`, removes `enter`, reads `offsetWidth` and adds `enter` (showView, line 2083; the class then stays, as in the reference).
- `HeaderC`: `Header` with `mode={wb.mode}`, `busy`, `badge`, `view`, `model` (settings), `popOpen`, `speed`, `onTogglePop={(o) => wb.togglePop(o)}`, `onSpeed={(s) => wb.setSpeed(s)}`, `onReset={() => void wb.reset()}`.
- `ConversationC`: `const ss = useSession((s) => s)`; `shown = shownSession(ss)`; `cur = curSession(ss)`; title `shown.name`; `readOnly = ss.viewId ? { name: shown.name, started: shown.started } : null`; `empty = !ss.viewId && shown.messages.length === 0`; `viewingN` = the viewed run's `n`; composer `value={draft}`, `busy`, `disabled={busy || !!ss.viewId}`, `hint` (`hintPast` with `cur.name`, else `hintBusy` while busy, else `hintIdle`), `onChange={(v) => wb.setDraft(v)}`, `onSubmit={() => void wb.submitDraft()}`; `onRun={(n) => wb.viewRun(n)}`; `onSuggest={(i) => void wb.submit(SUGGESTIONS[i]!.q)}`; `live` from `ui.live`; `animateTitle` from `ui.titleAnimate`.
- `BenchC`: renders `<main className="bench" id="bench" aria-label={COPY.bench.aria}>`. No viewed run: `<Idle key={\`idle-${benchKey}\`} count={tools.length} weatherKeySet={!!env.OPENWEATHERMAP_API_KEY} askExec={askExec} onSuggest={(i) => void wb.submit(SUGGESTIONS[i]!.q)} />`. Otherwise `<Bench key={\`${run.id}:${benchKey}\`} run={run} live={busy && run.id === currentRunId && (run.status === "running" || run.status === "waiting")} panel={<Panel run={run} isCurrent={run.id === currentRunId} tool={findTool(tools, run.toolName)} earlier={earlierData(runsOfShown, run, !!viewId)} onAsk={(q) => void wb.submit(q)} onOpenTool={(n) => wb.openTool(n)} onRun={(n) => wb.viewRun(n)} />} onTab={(t) => wb.selectTab(t)} onStop={() => wb.stop()} onOpenTool={(n) => wb.openTool(n)} />`, where `runsOfShown = useMemo(() => shownSession(ss).runIds.map((id) => byId[id]).filter(Boolean), [ss, byId])`.
- `VaultC`: `VaultView` with the ui fields (`stagger`, `renderKey={vaultRender}`), `source={sources[selected] ?? null}`, an effect that calls `wb.loadSource(selected)` when `selected` has no cached entry, and the callbacks `wb.setQuery`, `wb.setFilter`, `wb.selectTool`, `wb.fallbackSelect`, `wb.readSource`, `wb.useTool`, `wb.removeTool`, `wb.openTool`.
- `SessionsC`: `SessionsView` with `sessions`, `runsById`, `curId`, `onOpen={(id) => wb.openSession(id)}`.
- `SettingsC`: `SettingsView` with `askExec`, `env`, `model`, `onToggleAsk={() => wb.toggleAskExec()}`.
- `ModalC`: `<ModalRoot dialog={dialog} demo={wb.mode === "demo"} onApproval={(a) => wb.answerApproval(a)} onKey={(r) => wb.answerKey(r)} onClose={() => wb.closeReader()} />` (renders nothing when `dialog` is null).

Keep every selector to a slice (`(s) => s.byId`, `(u) => u.busy`, …) and derive with `useMemo`.

- [ ] **Step 6: Replace `frontend/src/main.tsx`**

```tsx
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Workbench } from "./app/workbench";
import { resolveMode } from "./mode";
import { createServices } from "./services";
import "./styles.css";

// Boot sequence (line 2292): header drops in, then the columns rise; the class goes after 1.4 s.
document.body.classList.add("booting");
setTimeout(() => document.body.classList.remove("booting"), 1400);

// No StrictMode: its double-run effects would replay the one-shot decode animations in development.
void createServices(resolveMode()).then(({ stores, services }) => {
  createRoot(document.getElementById("root")!).render(<App stores={stores} workbench={new Workbench(stores, services)} />);
});
```

- [ ] **Step 7: Run the tests, then try it**

Run: `npx vitest run src/app src/App.test.tsx && npm run lint && npm run typecheck && npm run build`
Expected: PASS; build prints `✓ built`.

Run: `npm run dev`, open `http://localhost:5173/?demo`, click the first suggestion and watch the Caesar run end to end; then Reset from Demo controls.
Expected: the run animates like the published demo; Reset returns to the idle bench with "Session 1".

- [ ] **Step 8: Commit**

```bash
git add frontend/src/mode.ts frontend/src/services.ts frontend/src/vite-env.d.ts frontend/src/app frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/main.tsx
git commit -m "[Feat]: Wire the workbench controller, demo services and the app shell"
```

---

### Task 16: End-to-end flow parity in jsdom

**Files:**
- Create: `frontend/src/test/flowHarness.tsx`
- Test: `frontend/src/app/flows.test.tsx`

**Interfaces:**
- Consumes: `flow`, `allFlows`, `expectParity`, `FIXED_NOW`, `FlowAction` (Task 2), `createServices`, `Workbench`, `App` (Task 15), `setReducedMotion` (Task 1).
- Produces: `runFlowInApp(actions: FlowAction[], regionsFor: (name: string) => string[]): Promise<Record<string, Record<string, string | null>>>`.

This is the parity suite's backbone: all 18 flows from `scripts/parity-flows.mjs` are replayed against the React app in demo mode, under the same clock and reduced motion, and every snapshot region is compared with the reference's.

Harness semantics (they mirror the generator's, Task 2):

- Fake timers (`setTimeout`, `clearTimeout`, `setInterval`, `clearInterval`, `Date`) at `FIXED_NOW`; reduced motion on.
- `submit`: `fireEvent.change(#ask, { target: { value } })`, then, in a second `act`, `fireEvent.submit(#composer)`.
- `click`: `el.click()` inside `act`. `fill`: `fireEvent.change(el, { target: { value } })`. `key`: `fireEvent.keyDown(document.activeElement ?? document.body, { key })`.
- `hash`: set `location.hash`, then advance timers until `#view-<name>` isn't hidden (jsdom fires `hashchange` from a timer).
- `until cond`: loop: evaluate the pending `snapAt`/`at` hooks, then `cond`; if `cond` is true stop; else `await act(() => vi.advanceTimersToNextTimerAsync())`; fail after 20 000 steps or when no timer is left.
- Hooks fire once, the first time their `cond` is true at a timer boundary: `snapAt` snapshots the regions; `at` clicks its selectors in order. That is the moment the reference is about to `wait()`.
- A snapshot is `{ [selector]: element.outerHTML | null }` over the same regions as the reference's (the snap's `regions` or the default list).

- [ ] **Step 1: Write the harness** `frontend/src/test/flowHarness.tsx`

```tsx
import { act, fireEvent, render } from "@testing-library/react";
import { App } from "../App";
import { Workbench } from "../app/workbench";
import { createServices } from "../services";
import type { FlowAction } from "./parity";

type Regions = Record<string, string | null>;

const evalCond = (cond: string): boolean => Boolean(new Function(`return (${cond});`)());
const el = (sel: string): HTMLElement => {
  const e = document.querySelector<HTMLElement>(sel);
  if (!e) throw new Error(`no element ${sel}`);
  return e;
};
const grab = (sels: string[]): Regions => Object.fromEntries(sels.map((s) => [s, document.querySelector(s)?.outerHTML ?? null]));

export async function runFlowInApp(actions: FlowAction[], regionsFor: (name: string) => string[]): Promise<Record<string, Regions>> {
  window.location.hash = "";
  const { stores, services } = await createServices("demo");
  const host = document.body.appendChild(document.createElement("div"));
  const view = render(<App stores={stores} workbench={new Workbench(stores, services)} />, { container: host });
  await act(async () => {});
  const snaps: Record<string, Regions> = {};
  const hooks: { cond: string; name?: string; click?: string[]; done: boolean }[] = [];

  const fireHooks = async () => {
    for (const h of hooks) {
      if (h.done || !evalCond(h.cond)) continue;
      h.done = true;
      if (h.name) snaps[h.name] = grab(regionsFor(h.name));
      for (const sel of h.click ?? []) await act(async () => el(sel).click());
    }
  };
  const until = async (cond: () => boolean) => {
    for (let i = 0; i < 20000; i++) {
      await fireHooks();
      if (cond()) return;
      if (vi.getTimerCount() === 0) throw new Error("flow stuck: no timers left and the condition is false");
      await act(() => vi.advanceTimersToNextTimerAsync());
    }
    throw new Error("flow did not settle");
  };

  try {
    for (const a of actions) {
      switch (a.do) {
        case "submit":
          await act(async () => void fireEvent.change(el("#ask"), { target: { value: a.text } }));
          await act(async () => void fireEvent.submit(el("#composer")));
          break;
        case "click":
          await act(async () => el(a.sel).click());
          break;
        case "fill":
          await act(async () => void fireEvent.change(el(a.sel), { target: { value: a.value } }));
          break;
        case "key":
          await act(async () => void fireEvent.keyDown(document.activeElement ?? document.body, { key: a.key }));
          break;
        case "hash": {
          const name = a.value.slice(1);
          await act(async () => {
            window.location.hash = a.value;
          });
          await until(() => !document.getElementById(`view-${name}`)?.hidden);
          break;
        }
        case "until":
          await until(() => evalCond(a.cond));
          break;
        case "snap":
          snaps[a.name] = grab(regionsFor(a.name));
          break;
        case "snapAt":
          hooks.push({ cond: a.cond, name: a.name, done: false });
          break;
        case "at":
          hooks.push({ cond: a.cond, click: a.click, done: false });
          break;
      }
      await fireHooks();
    }
  } finally {
    view.unmount();
    host.remove();
  }
  return snaps;
}
```

- [ ] **Step 2: Write the failing test** `frontend/src/app/flows.test.tsx`

```tsx
import { allFlows, expectParity, FIXED_NOW, flow } from "../test/parity";
import { runFlowInApp } from "../test/flowHarness";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
});
afterEach(() => vi.useRealTimers());

describe.each(allFlows())("flow %s", (name) => {
  test("every snapshot matches the reference, region by region", async () => {
    const f = flow(name);
    const ours = await runFlowInApp(f.actions, (snapName) => Object.keys(f.snaps[snapName]?.regions ?? {}));
    expect(Object.keys(ours).sort()).toEqual(Object.keys(f.snaps).sort());
    for (const [snapName, s] of Object.entries(f.snaps)) {
      for (const [sel, html] of Object.entries(s.regions)) {
        const mine = ours[snapName]![sel] ?? null;
        if (html === null) {
          expect(mine, `${name}/${snapName} ${sel}`).toBeNull();
          continue;
        }
        try {
          expectParity(mine ?? "", html);
        } catch (err) {
          throw new Error(`${name}/${snapName} ${sel}: ${(err as Error).message}`);
        }
      }
    }
  });
});
```

- [ ] **Step 3: Run it**

Run: `npx vitest run src/app/flows.test.tsx`
Expected at first: some failures. Each message names the flow, snapshot and region, then shows the two normalised strings. Fix the component, the player or the demo transport until every flow passes. Never edit `fixtures.json`, the cases or the flows to make a test pass. If a difference comes from the reference itself (like ruling 10), stop and report it to the controller instead of working around it.

Run again until: PASS (18 tests).

- [ ] **Step 4: Run everything**

Run: `npm run lint && npm run typecheck && npm test && npm run build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/test/flowHarness.tsx frontend/src/app/flows.test.tsx
git commit -m "[Feat]: Replay every reference flow against the app and compare the DOM"
```

(If Step 3 needed fixes in earlier files, commit them first, separately, as `[Fix]: …` with a sentence saying what differed from the reference.)

---

### Task 17: Progress note and final verification

**Files:**
- Modify: `PROGRESS.md` (repo root: a new section before `## Session log`, and a session-log entry at the end)

- [ ] **Step 1: Add the stage section to `PROGRESS.md`** (before `## Session log`)

```markdown
## Web app stage 04a — Frontend, demo mode ✅

- [x] `frontend/`: React 18 + TypeScript (strict) + Vite 5, Vitest + Testing Library, ESLint. Scripts: `dev`, `build`, `typecheck`, `lint`, `test`, `extract`, `fixtures`, `e2e` (lands in 04b).
- [x] `src/styles.css`, the vault data and the two bundled tool sources are generated verbatim from `docs/superpowers/specs/reference/workbench-demo/artifact-body.html` (`npm run extract`), and tests check them byte for byte.
- [x] DOM parity: `npm run fixtures` runs the reference in headless Chromium and records its renderer outputs (53 cases) and live DOM at checkpoints of 18 scripted flows. Components are compared with them after normalisation (`src/test/normalize.ts`), and `src/app/flows.test.tsx` replays every flow against the app.
- [x] Runs go through one path: `Transport` → `Player` (pacing from the reference) → stores → components. Demo mode (`/?demo` or `VITE_DEMO=1`) uses `DemoTransport`, the reference's scripted flows emitting contract events; golden event logs for the five fake-graph flows are in `src/transport/__golden__/`.
- [x] Seams for 04b: `Transport` (`src/transport/types.ts`), `Player` (`src/transport/player.ts`, with the §6 minimum dwells behind `momentDwell`), `DataSource` (`src/data/source.ts`), `createServices(mode)` (`src/services.ts`).

**Notes**:
- Controller ruling: demo mode shows the reference's literal "34 lines" for the weather tool's reused Code tab; live mode computes the count.
- Proposed contract addition for stage 2: `forge.code.tests` (the number of tests written), so the Tests tab shows its count while the code reveals.
```

And at the end of the session log:

```markdown
- **2026-09-30** — Web app stage 04a (frontend, demo mode) on branch `feat/web-04-frontend`. The Workbench demo ported to React with DOM, style and copy parity against the reference file, running entirely in demo mode through the real event player. Part B (live transport, visual/e2e/axe, CI) follows on the same branch.
```

- [ ] **Step 2: Run the full frontend suite from a clean install**

Run: `cd frontend && rm -rf node_modules dist && npm ci && npm run lint && npm run typecheck && npm test && npm run build`
Expected: lint and typecheck print no errors; every test file passes; build prints `✓ built`.

- [ ] **Step 3: Check the fixtures are current**

Run: `npm run fixtures && git status --short src/test/parity/fixtures.json`
Expected: no output from `git status` (regenerating gives the committed file byte for byte).

- [ ] **Step 4: Check the Python side is untouched and green**

Run (repo root): `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: pytest passes with the same counts as before this stage; ruff reports nothing.

- [ ] **Step 5: Commit**

```bash
git add PROGRESS.md
git commit -m "[Docs]: Record stage 04a, the frontend in demo mode"
```

