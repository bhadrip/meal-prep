const { test, expect } = require('@playwright/test');

const USER_ID = '3f7b623c-5ba4-4c02-9456-4bd71bdc70d5';
const SESSION_ID = '4f933a9d-388b-43bd-92b8-b2af303408b1';

async function mockSignedInApp(page, token) {
  await page.addInitScript(({ sessionId }) => {
    window.posthogCalls = [];
    window.posthog = {
      __loaded: true,
      init: (key, config) => window.posthogCalls.push({ type: 'init', key, config }),
      identify: (id) => window.posthogCalls.push({ type: 'identify', id }),
      capture: (event, properties) => window.posthogCalls.push({ type: 'capture', event, properties }),
      get_session_id: () => sessionId,
      reset: () => window.posthogCalls.push({ type: 'reset' }),
    };
  }, { sessionId: SESSION_ID });
  await page.route('**/api/auth/config', (route) => route.fulfill({ json: {
    supabaseUrl: 'https://example.supabase.co', supabaseAnonKey: 'public-test-key',
    authRequired: true, posthogProjectToken: token, posthogHost: 'https://us.i.posthog.com',
  } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.supabase = { createClient: () => ({ auth: {
      getSession: async () => ({ data: { session: { access_token: 'signed-token', user: { id: '${USER_ID}', email: 'cook@example.test' } } }, error: null }),
    } }) };`,
  }));
}

test('identified web navigation reaches PostHog and carries its session into API calls', async ({ page }) => {
  await mockSignedInApp(page, 'test-project-token');
  const apiHeaders = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/app/')) apiHeaders.push(request.headers());
  });

  await page.goto('/app');
  await expect(page.locator('#view-title')).toHaveText('Overview');
  await expect.poll(() => page.evaluate(() => window.posthogCalls.some(
    (call) => call.type === 'capture' && call.event === 'app_viewed' && call.properties.view === 'overview',
  ))).toBe(true);

  await page.locator('[data-view="plan"]:visible').first().click();
  await expect(page.locator('#view-title')).toHaveText('Weekly plan');
  await expect.poll(() => page.evaluate(() => window.posthogCalls.some(
    (call) => call.type === 'capture' && call.event === 'app_viewed' && call.properties.view === 'plan',
  ))).toBe(true);

  const calls = await page.evaluate(() => window.posthogCalls);
  expect(calls.find((call) => call.type === 'identify').id).toBe(USER_ID);
  expect(calls.find((call) => call.type === 'init').key).toBe('test-project-token');
  expect(calls.find((call) => call.type === 'init').config.session_recording.maskTextSelector).toBe('*');
  expect(calls.find((call) => call.type === 'init').config.session_recording.blockSelector).toContain('img');
  expect(calls.find((call) => call.type === 'init').config.session_recording.recordBody).toBe(false);
  expect(calls.filter((call) => call.type === 'capture').every(
    (call) => call.properties.entry_point === 'web' && !JSON.stringify(call).includes('cook@example.test'),
  )).toBe(true);
  expect(apiHeaders.some((headers) => headers['x-posthog-session-id'] === SESSION_ID)).toBe(true);
});

test('missing project token leaves the signed-in app usable without capture', async ({ page }) => {
  await mockSignedInApp(page, '');
  await page.goto('/app');
  await expect(page.locator('#view-title')).toHaveText('Overview');
  await page.locator('[data-view="plan"]:visible').first().click();
  await expect(page.locator('#view-title')).toHaveText('Weekly plan');
  expect(await page.evaluate(() => window.posthogCalls)).toEqual([]);
});

test('email code sign-in records stages and joins the Supabase user timeline', async ({ page }) => {
  await page.addInitScript(({ sessionId }) => {
    const record = (call) => {
      const calls = JSON.parse(sessionStorage.getItem('analytics-test-calls') || '[]');
      calls.push(call);
      sessionStorage.setItem('analytics-test-calls', JSON.stringify(calls));
    };
    window.posthog = {
      __loaded: true,
      init: () => {},
      identify: (id) => record({ type: 'identify', id }),
      capture: (event, properties, options) => record({ type: 'capture', event, properties, options }),
      get_session_id: () => sessionId,
      reset: () => record({ type: 'reset' }),
    };
  }, { sessionId: SESSION_ID });
  await page.route('**/api/auth/config', (route) => route.fulfill({ json: {
    supabaseUrl: 'https://example.supabase.co', supabaseAnonKey: 'public-test-key',
    authRequired: true, posthogProjectToken: 'test-project-token', posthogHost: 'https://us.i.posthog.com',
  } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.supabase = { createClient: () => ({ auth: {
      getSession: async () => ({ data: { session: JSON.parse(sessionStorage.getItem('fake-session') || 'null') }, error: null }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signInWithOtp: async () => ({ error: null }),
      verifyOtp: async () => {
        const session = { access_token: 'signed-token', user: { id: '${USER_ID}', email: 'cook@example.test' } };
        sessionStorage.setItem('fake-session', JSON.stringify(session));
        return { data: { session }, error: null };
      },
    } }) };`,
  }));

  await page.goto('/login');
  await page.locator('#email').fill('cook@example.test');
  await page.getByRole('button', { name: 'Send code' }).click();
  await expect(page.locator('#code-form')).toBeVisible();
  await page.locator('#code').fill('12345678');
  await page.getByRole('button', { name: 'Verify code' }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.locator('#view-title')).toHaveText('Overview');
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('analytics-test-calls') || '[]')
    .some((call) => call.event === 'app_viewed'))).toBe(true);

  const calls = await page.evaluate(() => JSON.parse(sessionStorage.getItem('analytics-test-calls') || '[]'));
  expect(calls.map((call) => call.event).filter(Boolean)).toEqual(expect.arrayContaining([
    'sign_in_started', 'sign_in_completed', 'app_viewed',
  ]));
  expect(calls.find((call) => call.type === 'identify').id).toBe(USER_ID);
  expect(calls.find((call) => call.event === 'sign_in_completed').options.send_instantly).toBe(true);
  expect(JSON.stringify(calls)).not.toContain('cook@example.test');
});
