import { defineConfig, devices } from '@playwright/test';

const port = process.env.RESTORER_E2E_PORT || '8879';
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL, actionTimeout: 15_000, navigationTimeout: 30_000, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: {
    command: '../.venv/bin/python ../tests/browser_server.py',
    url: `${baseURL}/api/health`,
    reuseExistingServer: false,
    timeout: 45_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 20_000 },
  },
});
