const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './ui-tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:18765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18765',
    url: 'http://127.0.0.1:18765/api/health',
    reuseExistingServer: false,
    timeout: 30000,
    env: {
      APP_BASE_URL: 'http://127.0.0.1:18765',
      SUPABASE_URL: '',
      SUPABASE_ANON_KEY: '',
      AUTH_REQUIRED: 'false',
    },
  },
});
