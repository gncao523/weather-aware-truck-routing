import { defineConfig, devices } from "@playwright/test";

const PORT = 5174;

/**
 * Browser tests run against the Vite dev server with every /api call mocked
 * (see e2e/fixtures.ts), so they are fast, deterministic and spend no quota on
 * the free routing/weather APIs. Set PW_CHANNEL=chrome to use an installed
 * Chrome instead of Playwright's bundled Chromium.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        channel: process.env.PW_CHANNEL || undefined,
        // MapLibre needs WebGL; SwiftShader provides it in headless CI.
        launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
