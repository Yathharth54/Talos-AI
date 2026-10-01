import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist",
      "node_modules",
      "src/test/parity/fixtures.json",
      ".e2e-tmp",
      "test-results",
      "playwright-report",
      "e2e/visual/__screenshots__",
    ],
  },
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
    files: ["e2e/**/*.ts", "playwright.*.config.ts"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  {
    files: ["e2e/live/fixtures.ts"],
    // Playwright fixtures call `use(...)`, which the React hooks rule mistakes for React's `use`.
    rules: { "react-hooks/rules-of-hooks": "off" },
  },
  {
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: { "no-undef": "off", "no-global-assign": "off" },
  },
);
