import { defineConfig, devices } from "@playwright/test";

const sizes = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } } as const;
const base = {
  ...devices["Desktop Chrome"],
  deviceScaleFactor: 1,
  reducedMotion: "reduce" as const,
  timezoneId: "UTC",
  locale: "en-GB",
};
const REF = "http://127.0.0.1:4599/index.html";
const DEMO = "http://127.0.0.1:4173/?demo";

export default defineConfig({
  testDir: "e2e/visual",
  outputDir: "test-results/visual", // apart from the live suite's, which empties its own on start
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/visual" }]],
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.001, animations: "disabled", caret: "hide", scale: "css" },
  },
  projects: [
    ...(["desktop", "mobile"] as const).map((s) => ({
      name: `ref-${s}`,
      use: { ...base, viewport: sizes[s], baseURL: REF },
    })),
    ...(["desktop", "mobile"] as const).map((s) => ({
      name: `demo-${s}`,
      use: { ...base, viewport: sizes[s], baseURL: DEMO },
    })),
  ],
  webServer: [
    {
      command: "python3 -m http.server 4599 --bind 127.0.0.1 --directory ../docs/superpowers/specs/reference/workbench-demo",
      url: "http://127.0.0.1:4599/index.html",
      reuseExistingServer: !process.env.CI,
      stdout: "ignore",
    },
    {
      command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173/",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
