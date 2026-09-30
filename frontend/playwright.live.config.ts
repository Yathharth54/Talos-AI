import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e/live",
  fullyParallel: false,
  workers: 1, // one active run at a time across the app (stage 2 §4); state carries between files
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/live" }]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:8765",
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce", // the player caps every dwell at 40 ms (spec 04 §6), so runs finish fast
    permissions: ["clipboard-read", "clipboard-write"],
    trace: "retain-on-failure",
  },
  projects: [
    { name: "live-desktop", testIgnore: /mobile/ },
    { name: "live-mobile", testMatch: /07-a11y\.spec\.ts/, use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: "uv run python frontend/e2e/serve_backend.py",
    cwd: "..",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: false, // always a fresh database, vault and .env
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    stdout: "pipe",
  },
});
