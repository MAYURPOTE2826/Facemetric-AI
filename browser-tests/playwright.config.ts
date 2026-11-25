import { defineConfig } from "@playwright/test";

/**
 * Real-browser verification. Starts an ISOLATED stack:
 *   API  http://127.0.0.1:8100  (browser-tests/server/run_test_backend.py: temp encrypted data dir, stubbed provider)
 *   Web  http://127.0.0.1:3100  (the real Next.js app from ../frontend, proxying /api to the test API)
 * It uses the Microsoft Edge that is installed on the machine (no browser download). Override with PFI_BROWSER=chrome.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  expect: { timeout: 60_000 },  // the first request to each page compiles it in Next dev mode
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: `results/results-${process.env.PFI_BROWSER ?? "msedge"}${process.env.PFI_MOBILE ? "-mobile" : ""}.json` }]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    // PFI_BROWSER: msedge (default) | chromium (Playwright's bundled build) | firefox | chrome (only if Google Chrome is installed).  PFI_MOBILE=1 emulates a 390x844 touch phone viewport.
    ...(process.env.PFI_BROWSER === "firefox" ? { browserName: "firefox" as const } : process.env.PFI_BROWSER === "chromium" ? { browserName: "chromium" as const } : { channel: process.env.PFI_BROWSER ?? "msedge" }),
    ...(process.env.PFI_MOBILE ? { viewport: { width: 390, height: 844 }, isMobile: process.env.PFI_BROWSER === "firefox" ? false : true, hasTouch: process.env.PFI_BROWSER === "firefox" ? false : true } : {}),
    headless: true,
    screenshot: "off",
    trace: "off",
  },
  webServer: [
    {
      command: "..\\backend\\.venv\\Scripts\\python.exe server\\run_test_backend.py",
      url: "http://127.0.0.1:8100/api/health",
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: "npx next dev -p 3100",
      cwd: "../frontend",
      env: { API_URL: "http://127.0.0.1:8100" },
      url: "http://127.0.0.1:3100",
      timeout: 240_000,
      reuseExistingServer: false,
    },
  ],
});
