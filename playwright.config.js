const { defineConfig, devices } = require('@playwright/test');
const port = process.env.PLAYWRIGHT_PORT || '18765';
const baseURL = `http://127.0.0.1:${port}`;

module.exports = defineConfig({
  testDir: './ui-tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: `backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port ${port}`,
    url: `${baseURL}/api/health`,
    reuseExistingServer: false,
    timeout: 30000,
    env: {
      APP_BASE_URL: baseURL,
      SUPABASE_URL: '',
      SUPABASE_ANON_KEY: '',
      AUTH_REQUIRED: 'false',
    },
  },
});
