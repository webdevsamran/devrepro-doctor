import { defineConfig, devices } from '@playwright/test'

/**
 * Browser-driven coverage for the console.
 *
 * `PRODUCT_GAPS.md` recorded the absence of this as gap 5, and an earlier
 * version of that file claimed Playwright smoke tests existed when they never
 * had. The vitest suite renders components in jsdom, which is the right tool
 * for logic and the wrong one for the things that actually break here: a lazy
 * route that fails to resolve, a CSS variable that is referenced and never
 * defined, a focus ring drawn on an invisible element, a table whose columns
 * stop lining up below 640px. None of those fail in jsdom, because jsdom does
 * not lay anything out.
 *
 * One browser on purpose. The value is "every route renders and is reachable",
 * not cross-engine rendering parity, and three engines would triple the CI
 * minutes for a claim this project is not making.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: 'http://localhost:4183',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
  // The production build, not the dev server: code splitting, minification and
  // the real asset graph are exactly what a route-level smoke test should be
  // exercising, and a dev-only failure would be a false negative.
  webServer: {
    command: 'npm run build && npx vite preview --port 4183 --strictPort',
    url: 'http://localhost:4183',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
