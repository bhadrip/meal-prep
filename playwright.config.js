const { defineConfig, devices } = require('@playwright/test');
const firstPort = Number(process.env.PLAYWRIGHT_PORT || 18765);
const profiles = [['chromium', 'Desktop Chrome'], ['android', 'Pixel 7'], ['iphone', 'iPhone 13']];
const origin = index => `http://127.0.0.1:${firstPort + index}`;

module.exports = defineConfig({
  testDir: './ui-tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: origin(0),
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Each browser profile gets fresh demo state; one browser's edits must not alter another's fixtures.
  projects: profiles.map(([name, device], index) => ({ name, use: { ...devices[device], baseURL: origin(index) } })),
  webServer: profiles.map((_, index) => ({
    command: `backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port ${firstPort + index}`,
    url: `${origin(index)}/api/health`,
    reuseExistingServer: false,
    timeout: 30000,
    env: {
      APP_BASE_URL: origin(index),
      SUPABASE_URL: '',
      SUPABASE_ANON_KEY: '',
      AUTH_REQUIRED: 'false',
    },
  })),
});
