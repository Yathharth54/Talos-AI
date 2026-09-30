# Stage 4: frontend (the Workbench demo, made real)

Date: 2026-09-30
Status: draft for review
Parent: `2026-09-30-talos-web-app-overview-design.md`
Depends on: stage 2 (API and event contract). It can start against `TALOS_FAKE_GRAPH=1`.

## 1. The rule

The approved demo is the design. The real frontend must look, read, move and behave exactly like it. The only differences allowed are the ones listed in §8.

The source of truth is committed in this repo:

- `docs/superpowers/specs/reference/workbench-demo/artifact-body.html`: the exact file published as https://claude.ai/artifact/6EtEykFd7rGvb77U7nwz54 (version 5, 30 Sep 2026), byte for byte.
- `docs/superpowers/specs/reference/workbench-demo/index.html`: the same body wrapped in a doctype, charset and viewport, so it opens directly in a browser. The artifact viewer adds the same wrapper.
- `docs/superpowers/specs/reference/workbench-demo/assets/`: `apple-touch-icon.png` and `hero-mark.webp`, copied from `site/assets/`.

The static design canvas holds the earlier comps and the kit sheet: https://claude.ai/artifact/5fEc3XDosLchkVF95Hzqe6 ("Workbench, worked through" and "Workbench kit").

When this spec and the reference file disagree, the reference file wins, and this spec gets fixed.

## 2. Stack and layout

- React 18 with TypeScript (strict) and `.tsx` components, built with Vite 5. No component library, no CSS framework, no CSS-in-JS. Styling is the demo's stylesheet, applied through the demo's class names.
- State: one `useReducer` store per concern, exposed through context: `runs` (the demo's run objects), `session`, `vault`, `settings` and `ui` (view, dialog, busy). No Redux or Zustand.
- Only three external resources, as in the demo: Google Fonts (Michroma, Instrument Sans 400/500/600, JetBrains Mono 400/500) and the two images.
- `frontend/` at the repo root:

```
frontend/
  index.html                 # <div id="root">, the Google Fonts link, <title>Talos Workbench</title>
  vite.config.ts             # React plugin, dev proxy /api → 127.0.0.1:8000
  package.json               # scripts: dev, build, typecheck, lint, test, e2e
  public/assets/             # apple-touch-icon.png, hero-mark.webp
  src/
    styles.css               # the demo's <style> block, verbatim (§3), imported once in main.tsx
    main.tsx                 # createRoot, providers, the booting class on <body>
    App.tsx                  # <Header/>, the four views, <ModalRoot/>; hash router
    lib/
      format.ts              # fmtTime, fmtClock, fmtShort, fmtDay, sameDay, nowIso, splitArgs, argNames, pyStr
      highlight.ts           # highlight(): returns the same HTML strings as the demo
      motion.ts              # scramble, countUp, wrapWords, still (reduced motion), GLYPHS
      copy.ts                # every user-facing string not coming from the server (§7)
    hooks/
      useScramble.ts         # runs scramble() on a ref when its text changes (idle heading, session title, saved banner name, log labels)
      useCountUp.ts          # idle tool count
      useRestartAnimation.ts # remove class, force reflow, re-add: for flash, panel-in, view enter, detail swap, link flow
      useTabIndicator.ts     # placeInd(): slides .tab-ind from the previous tab to the selected one
      useFocusTrap.ts        # dialogs: trap Tab, Esc handling, restore focus
      usePointerGlow.ts      # sets --mx/--my on .try cards
    store/
      runs.ts                # reducer mirroring the demo's run object: nodes, links, caption, tabs, code, tests, attempts, smoke, call, banner, log
      session.ts, vault.ts, settings.ts, ui.ts
    components/
      Header.tsx             # brand + busy ring, nav with vault badge, DemoControls (demo mode only), GitHub pill
      workbench/
        Conversation.tsx     # head (title, New session / Back to now), messages, composer
        Message.tsx          # You / Talos message; Talos: thinking (orbit spinner), streamed words, note, chip, "View this run"
        Composer.tsx
        Bench.tsx            # rail, head, strip + caption, banner, tabs, panel; or <Idle/>
        Idle.tsx
        Strip.tsx            # nodes and links, including the packet and the retry loop
        Tabs.tsx
        panels/CodePanel.tsx, TestsPanel.tsx, AttemptsPanel.tsx, CallPanel.tsx, HistoryPanel.tsx, LogPanel.tsx, Earlier.tsx
        Banner.tsx
      dialogs/ApprovalDialog.tsx, KeyDialog.tsx, ReaderDialog.tsx, ModalRoot.tsx
      vault/VaultView.tsx, VaultTable.tsx, VaultDetail.tsx
      sessions/SessionsView.tsx, SessionCard.tsx
      settings/SettingsView.tsx
    transport/
      types.ts               # the event contract as TypeScript types (overview §4)
      live.ts                # REST calls + EventSource per run, with Last-Event-ID reconnect
      demo.ts                # DemoTransport: the demo's scripted flows, emitting contract events (§8.3)
      player.ts              # queue with pacing (§6); dispatches store actions
    demo/
      data.ts                # VAULT_DATA, seeded sessions, CAESAR/WEATHER metadata, source text
```

### 2.1 How React keeps the demo's DOM

The demo builds its markup with template strings. The React port must produce the same DOM: same elements, same nesting, same class names, same attributes (including `aria-*`, `data-*`, `role`, `hidden`), and same text.

- Each component's JSX is transcribed from the matching demo function (`stripHtml` → `Strip`, `callHtml` → `CallPanel`, and so on). Class names are kept literally. `class` becomes `className` and `for` becomes `htmlFor`, and nothing else changes.
- `highlight()` returns HTML strings exactly as in the demo. Code rows use `dangerouslySetInnerHTML` for the highlighted line only. The input is always escaped first by `esc()`, as in the demo. The same applies to server `html` fields (overview §4.3 allowlist), which are sanitised with a small allowlist sanitiser before they are inserted.
- Animations in the demo fire because an element gets a class or is newly inserted. React must reproduce the same moments:
  - Keyed elements that the demo re-creates, such as a new log line or a new message, are new React keys, so their CSS entry animation runs once.
  - Elements whose class changes, such as step state, keep a stable key and get the new `className`. The CSS animation then triggers the same way it does in the demo.
  - One-shot restarts (code-line flash, `panel-in`, `view.enter`, `v-detail.swap`, `link.flow`) go through `useRestartAnimation`, which does what the demo does by hand.
  - Imperative effects (`scramble`, `countUp`, tab indicator, pointer glow, the orbit spinner status swap, word-by-word fade) run in `useEffect`/`useLayoutEffect` on refs, with the same timings.
  - The demo re-renders the whole code or test panel on each reveal tick. React renders the same result from store state; tests that were drawn once keep the `done` class, as the demo does with `x.drawn`.
- Every demo function named in the reference file maps to one component, hook or store action. §4's inventory and §9's parity tests cover them.

## 3. Styles

- `src/styles.css` is the reference file's `<style>` content copied verbatim, in the same order, with no edits, no reformatting and no preprocessing.
- A unit test extracts the `<style>` block from `artifact-body.html` and asserts it equals `styles.css` after normalising line endings. Any intentional style change must update the reference file too, with the owner's sign-off.
- Tokens (for reference only; the CSS is the source):

| Token | Value | Use |
|---|---|---|
| `--ink` | `#000` | page |
| `--ink-2` | `#050505` | bench surface, inputs, dialogs |
| `--ink-3` | `#0B0906` | active step fill |
| `--bone` | `#ECE6DA` | primary text, solid buttons |
| `--bone-2` | `#C9C2B6` | secondary text |
| `--stone` | `#9A938A` | labels, captions |
| `--dim` | `#7D776F` | hints |
| `--sig` | `#8A847B` | signature arguments |
| `--gutter-num` | `#5E5953` | code line numbers |
| `--gold` | `#D6B27A` | forge work only: forging, testing, just saved, model-call pips, web tools |
| lines | bone at 10%, 16%, 30%, 50% | borders and connectors |

- Fonts: `--display` Michroma (wordmark, screen titles, idle heading), `--sans` Instrument Sans (everything else), `--mono` JetBrains Mono (code, signatures, run log, env var names).
- Shape: 10 px radius for steps and code blocks, 16 px for panels, dialogs and cards, pills (999 px) for all buttons and text inputs, 44 px minimum touch height.

## 4. Screens and states (inventory)

Each item names the reference function that renders it. Parity tests (§9) cover every item.

**Shell**
1. Header: round mark with a busy ring (spins while a run is going), `TALOS` wordmark, nav (Workbench, Vault with a pulsing gold new-tool badge, Sessions, Settings), model name, Demo controls (demo mode only, §8.1), GitHub pill.
2. Boot sequence: header drops in, then the chat column and the bench rise, staggered.

**Workbench** (two columns, 3:4; 2:3 below 1180 px; stacked below 820 px)

3. Idle bench (`renderIdle`): mark with two orbit rings (one carrying a gold dot) and a scan line; heading `Ask for something it can't do yet` decoding from glyphs; tool count counting up; four suggestion cards with a cursor-following glow and lift; setup line with a Settings link.
4. Empty conversation (`renderEmptyConvo`).
5. Planning: `Reading your request`, Planner active (halo pulse and ignite ring), Run log tab showing the typed `talos ›` command.
6. Forging, attempt 1: code revealing line by line with a gold caret, Forger active, caption, log `forge`.
7. Testing: tests ticking with running dots and drawn check marks; a failing test flashes and shows its assertion line.
8. Retry: Forger–Tester link with the backwards packet, attempt 2 code with the changed line flashed and scrolled into view, the code note.
9. Smoke test panel, running then done.
10. Human check passed straight through (dashed step).
11. Learn: saved banner with the gold sweep and the name decoding, Vault badge on.
12. Executing: arguments filling in one by one, result appearing.
13. Answer: words fading in from blur, note, chip, "View this run" link.
14. Reuse run: vault strip variant, warm gold log frame, `0 tools forged`, tool record row.
15. Tool failure: shaking failed step, error panel, flagged argument, failure meter, "Ask again with shift 7" and "Open in vault" actions.
16. Pruned: the removed banner after 2 failures in a row.
17. Approval dialog (`approvalDialog`): backdrop, dialog rise, "Don't run" focused, Esc cancels.
18. Declined run.
19. API key dialog (`keyDialog`): masked input, the empty-submit error `Paste the key first, or choose Skip.`, Skip and Save key.
20. Key skipped, then the tool failing without its key.
21. Stopped run.
22. Viewing an earlier run from "View this run" or from the list in the Run log tab.
23. Reading an old session: the read-only note, "Back to now", locked composer with its hint.
24. Busy composer: `Working`, hint `Stop the run to ask something else`.

**Vault** (`renderVault`, `renderDetail`)

25. Table with staggered rows: gold names for web tools, `New this session` tag, zero counts dimmed, clock time for today and a date otherwise.
26. Search and filter pills (All, Uses the web, Has failed) with counts, and the empty result.
27. Detail pane with a cross-fade on selection: description, signature box, keyword chips, facts, failure meter, source preview (14 px, soft wrap, bottom fade), "Read full file", "Use in a question", "Remove from vault" with the confirm step.
28. Reader dialog (`readerDialog`): wide, 15 px code, Copy with its fallback, closes on Esc, Close, or a click outside.

**Sessions** (`renderSessions`, `sessCard`)

29. Day groups (Today, then dates), cards with the time, run count, forged count, `Now` badge, up to 3 queries with forged/reused/failed marks, tool chips, and Open or Continue.

**Settings** (`renderSettings`)

30. Safety switch "Ask before running code", the Keys list, and the Forging facts.

## 5. Data: where each view gets it in live mode

| View / element | Source |
|---|---|
| Tool count (idle), vault counts, table, detail | `GET /api/vault`, `GET /api/vault/{name}` (source comes from the API, not `<script type="text/plain">`) |
| Setup line, Settings page, key rows | `GET /api/settings`; switch → `PATCH /api/settings` |
| Session title, conversation | `GET /api/sessions/{id}` (messages rendered with the same markup as `sessionHtml`) |
| Sessions page | `GET /api/sessions` |
| New session | `POST /api/sessions` |
| Send | `POST /api/sessions/{id}/messages`, then open the run's event stream |
| A run's bench and log | its event stream, live or replayed from `seq` 0 |
| Stop | `POST /api/runs/{id}/stop` |
| Dialog answers | `POST /api/runs/{id}/resume` |
| Remove from vault | `DELETE /api/vault/{name}`, only after the two-step confirm |
| `New this session` tag | `created_at` at or after the current session's `created_at` |

The session with the newest `updated_at` opens on load, or a new one is created if there is none. "New session" creates one. The demo's rule of discarding empty sessions carries over: an empty session isn't listed and is reused.

## 6. Event player and pacing

`player.ts` turns events into store actions. Each action has the same effect as the demo renderer call named here, which is how its component was specified:

| Event | Store action (equivalent demo call) |
|---|---|
| `run.started` | new run object, `addYou`, `addTalos`, `initStrip` with the provisional variant, `renderBench` |
| `log.cmd` | `typeCmd` |
| `strip.set` | `initStrip(variant)`, `renderBench`, `setLabel`, `setSig` |
| `node.started` / `node.finished` | `setNode(step, state, label)` |
| `link.flow` | `flow(from, to)`; for forger→tester during a retry, also `retrying(true/false)` |
| `caption` | `setCaption` |
| `log.line` / `log.pop` / `log.status` | `log` / `run.log.pop()` then `redrawLog` / `logStatus` + `logTone` |
| `talos.status` | `talos.status` |
| `forge.code` | attempt 1: `revealCode`; later attempts: replace lines, set `changed` and `flash`, `setTab("code")` |
| `forge.tests` | `runTests`-style reveal of the given results |
| `forge.attempt` | update `run.attempts`, `refreshTabs` |
| `forge.smoke` | set `run.smoke`, `renderPanel` |
| `vault.saved` | `setBanner({kind: "saved"})`, badge on |
| `vault.failure` | health meter; if `pruned`, `setBanner({kind: "removed"})` |
| `call.args` / `call.result` / `call.error` | `run.call` fill-in with the per-argument reveal, `renderPanel` |
| `interrupt` | `approvalDialog` or `keyDialog`; the answer goes to `/resume`, and Esc or cancel goes to `/stop` |
| `answer.delta` | append to a hidden buffer; `answer.done` renders with `talos.say` |
| `answer.done` | `talos.say(html, note)`, `talos.chip(...)` |
| `run.finished` | status, summary, `setActions`, `updateRail`, "View this run" link, `setBusy(false)` |

**Pacing.** Events go through a queue. Each one is applied no sooner than the previous one's minimum dwell, taken from the demo's `wait()` calls at speed 1:

| Moment | Minimum dwell |
|---|---|
| command typing | 22 ms per step, 40 steps max |
| Planner active | 900 ms |
| after `vault no match` | 400 ms |
| code reveal | 24 ms per tick, about 45 ticks per file |
| retry code shown before re-test | 1300 ms |
| each test | 360 ms running, then 90 ms |
| after a failed attempt | 700 ms |
| smoke | 800 ms running, then 400 ms |
| Human check pass-through | 450 ms |
| Learn active | 600 ms, then 900 ms after the banner |
| each argument | 260 ms, then 450 ms before the result |
| vault step (reuse) | 500 ms, then 350 ms |
| each answer word | 34 ms |

- If the backend is slower, the player just waits for the next event.
- When replaying a finished run ("View this run", or opening a past session), the player skips pacing and renders the final state, as `renderBench(run)` does in the demo.
- Reduced motion: every dwell is capped at 40 ms, as in the demo's `wait()`.

## 7. Copy

- All strings are verbatim from the reference file. `copy.ts` holds those the frontend owns: suggestion cards, idle heading and lede, dialog text, vault and settings copy, empty states, composer hints, the session read-only note.
- A unit test asserts every `copy.ts` string appears in `artifact-body.html`.
- Strings from the server (captions, log lines, chips, summaries) are checked by the backend test in overview §4.5.
- A few server strings have no counterpart in the reference file because the demo never needed them. They live in `talos/web/copy.py` `NEW_COPY` and render like any other server string: `{n} sub-tasks. Talos works through them in order.` (caption) and `{n} sub-tasks` (plan log line) for multi-sub-task plans; `The Forger used all {max} attempts. Nothing was saved to the vault.` and `gave up after {n} attempts` when a forge runs out of attempts; `{passed} of {total} passed` on the last failed attempt; `failed` for a failed smoke test; `Attempt {n} failed a test. Trying again` after attempt 2+; `{k} tools forged`; `1 tool forged, 1 attempt`; `Done in 1 attempt. No API key was needed, so Human check passed straight through.`; `Done in {attempts}. Your key is saved to .env.`

## 8. Allowed differences from the demo

### 8.1 Demo controls

The "Demo controls" button and popover (speed and Reset) render only in demo mode (§8.3). In live mode the header shows the model name and the GitHub pill only.

### 8.2 Live-mode copy that has to change because it says "demo"

| Demo text | Live text |
|---|---|
| `This demo keeps the key in memory only.` (key dialog footer) | removed; the rest of the sentence stays |
| weather result `Not called in this demo` and its answer | the real tool result and the real answer |
| `The demo only runs simple print() calls.` | the real stdout |
| unknown-query flow (`This demo can't plan that one…`) | the real planner handles every query |
| `Source lives at … This demo only bundles the source of tools it forges.` | never shown; the API returns source for every tool |
| seeded sessions (Fibonacci tools, Edit distance, Base64 round trip) | real history from `GET /api/sessions` |

Nothing else changes: layout, spacing, colours, motion, focus behaviour and all other copy stay as they are.

### 8.3 Demo mode is kept

`/?demo` (or building with `VITE_DEMO=1`) runs with no backend, including the seeded sessions, speed control and Reset.

`transport/demo.ts` is the reference file's scripted flows (`flowCaesar`, `executeCaesar`, `flowPython`, `flowWeather`, `flowVaultList`, `flowChat`, `flowUnknown`, `forgeTool`, `humanCheck`, `learn`, `planner`). They're rewritten to emit contract events instead of calling renderer functions, keeping every step, value and string. They go through the same `player.ts` as live runs, so demo mode also exercises the real rendering path. The demo's vault and session mutations become store actions.

Demo mode is the baseline for the parity tests, and it keeps the approved experience runnable forever.

## 9. Tests

- Unit (Vitest + React Testing Library):
  - `styles.css` equals the reference `<style>` block.
  - `copy.ts` strings exist in the reference.
  - `highlight()` output for the real `caesar_cipher.py` matches the reference function's output. The fixture is generated once by running the reference function.
  - `wrapWords`, `splitArgs`, `argNames`, `caesar`, `classify`, `parseCaesar`.
  - The player's pacing math under normal and reduced motion.
  - DOM parity per component: for a set of fixed run states, render the component and compare its `outerHTML` with the reference function's output for the same state (for example `Strip` vs `stripHtml(run)`), after normalising attribute order and whitespace. The reference outputs are generated once from `artifact-body.html` in a headless browser and stored as fixtures.
- Visual parity (Playwright): demo mode against the reference `index.html`, same seeded state, at 1440×900 and 390×844, with animations frozen (`prefers-reduced-motion: reduce` plus a CSS override that jumps to animation end). One screenshot per inventory item in §4 that is reachable by script. The pixel-diff threshold is 0.1%.
- End-to-end (Playwright, live mode against `TALOS_FAKE_GRAPH=1` and Postgres):
  - The Caesar forge, reuse and failure (with prune after 2) flows.
  - Approve and decline.
  - Key save and key skip.
  - Stop during a run and during a pause.
  - Reload during a pause, then the dialog comes back and resuming works.
  - Sessions page, open an old session, back to now.
  - Vault search, filters, read full file, remove.
  - Settings switch changes whether the approval dialog appears.
- Accessibility (axe via Playwright) on each view: no serious violations. Keyboard-only run-through of the Caesar flow and both dialogs.

## 10. Acceptance

- Demo mode is visually identical to the reference file at both sizes. The parity suite is green.
- Live mode with real keys runs the Caesar question end to end with every animation from the demo.
- Everything in §9 passes in CI (stage 3 §6).
- The owner reviews live mode side by side with the published demo and signs off.
