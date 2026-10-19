import { defineConfig, devices } from '@playwright/test';

const port = process.env.E2E_PORT ?? '8080';

/**
 * E2E smoke test for the *user-facing* stack (docker-compose.yml).
 *
 * global-setup starts the published-image compose stack (on E2E_PORT),
 * global-teardown tears it down. The tests then drive a real browser.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 180_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }]],
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  use: {
    baseURL: `http://localhost:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
